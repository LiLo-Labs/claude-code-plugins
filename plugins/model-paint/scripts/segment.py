"""Split a model into a small set of described regions for a language model to label.

Handing an LLM 2000 raw triangles and asking which ones are "the horns" does not
work. Handing it thirty regions, each described as "medium paired tapering cone,
upper right, protruding", does. This script does the deterministic half of that
trade: geometry in, described regions out, no judgment calls.

Two cuts, in order:

1. Connected components. Flexi models are dozens of separate interlocking bodies,
   and a body is almost always a whole anatomical part -- a link, a limb, a horn
   modelled as its own shell. Components are never merged with each other; doing
   so would fuse parts that the slicer and the print treat as independent.

2. Concave creases inside a component. Anatomy attaches at valleys: the groove
   where a horn meets the skull, the socket around an eye, the seam between belly
   plates. Convex ridges are almost always *inside* a feature (the spine of a
   horn, the facets of a low-poly claw), so the convex threshold defaults high
   enough that only a near fold-back cuts. This asymmetry is the whole reason the
   segmentation lands on features instead of shattering into facets.

Adjacency is computed from a rounded copy of the vertex coordinates because STL
stores every triangle with its own unwelded vertices; without that copy the face
graph has no edges at all. The copy is used for connectivity only. The mesh
itself is read, never written, never repaired, never re-indexed -- the face
indices in the output address the triangles exactly as they sit in the file.
"""

import argparse
import heapq
import json
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib.threemf import ThreeMF

DEFAULT_CONCAVE_ANGLE = 30.0
DEFAULT_CONVEX_ANGLE = 115.0
DEFAULT_MIN_FACES = 8
DEFAULT_MAX_SEGMENTS = 60

# Relative to the model's bounding diagonal: coincident vertices in a float32 STL
# are bit-identical, so this only has to survive rounding, not close gaps.
WELD_TOLERANCE = 1e-6

# Triangulated quads on a smooth surface produce diagonals that register as
# concave by a millionth of a degree. Anything under this is flat, not a valley.
FLAT_ANGLE = 0.5

# Orca/Bambu bed convention, and the one the shape hints are phrased in.
AXES = {"right": "+X", "back": "+Y", "up": "+Z", "front": "-Y"}


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------

def load_objects(path):
    """Read ``[{object_id, part, vertices, triangles}]`` without touching geometry."""
    if path.lower().endswith(".3mf"):
        archive = ThreeMF(path)
        objects = []
        for obj in archive.mesh_objects():
            objects.append({
                "object_id": obj.object_id,
                "part": obj.part,
                "vertices": np.asarray(obj.vertices, dtype=np.float64),
                "triangles": np.asarray(obj.triangles, dtype=np.int64),
            })
        if not objects:
            raise ValueError("no mesh objects found in %s" % path)
        return objects

    import trimesh

    mesh = trimesh.load(path, process=False, force="mesh")
    if not hasattr(mesh, "faces") or len(mesh.faces) == 0:
        raise ValueError("no triangles found in %s" % path)
    return [{
        "object_id": "1",
        "part": None,
        "vertices": np.asarray(mesh.vertices, dtype=np.float64),
        "triangles": np.asarray(mesh.faces, dtype=np.int64),
    }]


# --------------------------------------------------------------------------
# face graph
# --------------------------------------------------------------------------

def face_geometry(vertices, triangles):
    """Unit normals, areas, and centroids. Degenerate faces get a zero normal."""
    a = vertices[triangles[:, 0]]
    b = vertices[triangles[:, 1]]
    c = vertices[triangles[:, 2]]
    cross = np.cross(b - a, c - a)
    lengths = np.linalg.norm(cross, axis=1)
    areas = 0.5 * lengths
    safe = np.where(lengths > 0.0, lengths, 1.0)[:, None]
    normals = np.where(lengths[:, None] > 0.0, cross / safe, 0.0)
    centroids = (a + b + c) / 3.0
    return normals, areas, centroids


def weld(vertices, tolerance):
    """Index vertices by rounded position so that coincident corners agree."""
    if tolerance <= 0.0:
        tolerance = 1e-9
    keys = np.round(vertices / tolerance).astype(np.int64)
    _unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    return np.asarray(inverse).reshape(-1)


def face_pairs(triangles, welded):
    """Pairs of faces sharing an edge, as an (N, 2) array."""
    faces = welded[triangles]
    edges = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    owners = np.tile(np.arange(len(triangles), dtype=np.int64), 3)
    edges = np.sort(edges, axis=1)

    keep = edges[:, 0] != edges[:, 1]          # collapsed edges join nothing
    edges, owners = edges[keep], owners[keep]
    if len(edges) == 0:
        return np.zeros((0, 2), dtype=np.int64)

    order = np.lexsort((edges[:, 1], edges[:, 0]))
    edges, owners = edges[order], owners[order]
    # Chaining consecutive owners of the same edge is exact for manifold edges and
    # still connects the faces meeting at a non-manifold one.
    same = np.all(edges[1:] == edges[:-1], axis=1)
    pairs = np.stack([owners[:-1][same], owners[1:][same]], axis=1)
    return pairs[pairs[:, 0] != pairs[:, 1]]


def signed_dihedral(normals, centroids, pairs):
    """Dihedral angle per pair in degrees: positive convex, negative concave."""
    if len(pairs) == 0:
        return np.zeros(0)
    na, nb = normals[pairs[:, 0]], normals[pairs[:, 1]]
    angle = np.degrees(np.arccos(np.clip(np.sum(na * nb, axis=1), -1.0, 1.0)))
    # With outward normals, the neighbor's centroid falls behind this face's
    # normal plane exactly when the fold is convex.
    offset = centroids[pairs[:, 1]] - centroids[pairs[:, 0]]
    concave = np.sum(na * offset, axis=1) > 0.0
    degenerate = (np.linalg.norm(na, axis=1) == 0.0) | (np.linalg.norm(nb, axis=1) == 0.0)
    angle = np.where(degenerate, 0.0, angle)
    return np.where(concave, -angle, angle)


def components(count, pairs):
    """Union-find labels, renumbered so that labels are 0..k-1 in face order."""
    parent = list(range(count))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs.tolist():
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    labels = np.empty(count, dtype=np.int64)
    seen = {}
    for i in range(count):
        root = find(i)
        if root not in seen:
            seen[root] = len(seen)
        labels[i] = seen[root]
    return labels


# --------------------------------------------------------------------------
# region growing
# --------------------------------------------------------------------------

def _neighbor_counts(labels, pairs):
    """``{region: {region: shared boundary edges}}`` across cut edges."""
    adjacency = {}
    if len(pairs) == 0:
        return adjacency
    left, right = labels[pairs[:, 0]], labels[pairs[:, 1]]
    cut = left != right
    for a, b in zip(left[cut].tolist(), right[cut].tolist()):
        adjacency.setdefault(a, {})[b] = adjacency.setdefault(a, {}).get(b, 0) + 1
        adjacency.setdefault(b, {})[a] = adjacency.setdefault(b, {}).get(a, 0) + 1
    return adjacency


def _pick_target(adjacency, sizes, region):
    """Absorb into the neighbor we share the most boundary with, largest wins ties.

    Shared boundary beats raw size because a sliver is continuous with the surface
    it runs along; the largest region in the component may be nowhere near it.
    """
    best = None
    for other, shared in adjacency.get(region, {}).items():
        key = (shared, sizes[other], -other)
        if best is None or key > best[0]:
            best = (key, other)
    return best[1] if best else None


def merge_regions(labels, pairs, min_faces, max_segments):
    """Absorb undersized regions, then trim the count down to ``max_segments``."""
    sizes = {}
    for label in labels.tolist():
        sizes[label] = sizes.get(label, 0) + 1
    adjacency = _neighbor_counts(labels, pairs)
    parent = {label: label for label in sizes}

    def resolve(label):
        while parent[label] != label:
            parent[label] = parent[parent[label]]
            label = parent[label]
        return label

    def absorb(source, target):
        for other, shared in adjacency.get(source, {}).items():
            if other == target:
                continue
            adjacency.setdefault(target, {})[other] = \
                adjacency[target].get(other, 0) + shared
            adjacency[other][target] = adjacency[other].get(target, 0) + shared
            adjacency[other].pop(source, None)
        adjacency.get(target, {}).pop(source, None)
        adjacency.pop(source, None)
        sizes[target] += sizes.pop(source)
        parent[source] = target

    def drain(should_stop):
        heap = [(size, label) for label, size in sizes.items()]
        heapq.heapify(heap)
        while heap:
            size, label = heapq.heappop(heap)
            if label not in sizes or sizes[label] != size or should_stop(size):
                if should_stop(size):
                    return
                continue
            target = _pick_target(adjacency, sizes, label)
            if target is None:
                continue                       # a lone body has nothing to join
            absorb(label, target)
            heapq.heappush(heap, (sizes[target], target))

    drain(lambda size: size >= min_faces)
    if max_segments and len(sizes) > max_segments:
        drain(lambda _size: len(sizes) <= max_segments)

    remap = {label: resolve(label) for label in parent}
    merged = np.array([remap[label] for label in labels.tolist()], dtype=np.int64)

    # Renumber in face order so ids do not depend on dict iteration.
    order = {}
    for label in merged.tolist():
        order.setdefault(label, len(order))
    return np.array([order[label] for label in merged.tolist()], dtype=np.int64)


def segment_object(vertices, triangles, options, budget):
    """Region label per face, plus the face graph the descriptors reuse."""
    normals, areas, centroids = face_geometry(vertices, triangles)
    scale = float(np.linalg.norm(vertices.max(axis=0) - vertices.min(axis=0))) or 1.0
    welded = weld(vertices, scale * WELD_TOLERANCE)
    pairs = face_pairs(triangles, welded)
    angles = signed_dihedral(normals, centroids, pairs)

    body_labels = components(len(triangles), pairs)
    cut = ((angles < 0.0) & (-angles > options.concave_angle)) | \
          ((angles > 0.0) & (angles > options.convex_angle))
    labels = components(len(triangles), pairs[~cut])
    labels = merge_regions(labels, pairs, options.min_faces, budget)
    return {
        "labels": labels,
        "components": body_labels,
        "pairs": pairs,
        "angles": angles,
        "areas": areas,
        "centroids": centroids,
    }


# --------------------------------------------------------------------------
# descriptors
# --------------------------------------------------------------------------

def _round(value, digits=4):
    return round(float(value), digits)


def _principal(points):
    """Extents along the PCA axes, longest first, with the longest axis."""
    if len(points) < 3:
        span = points.max(axis=0) - points.min(axis=0) if len(points) else np.zeros(3)
        return np.sort(span)[::-1], np.array([1.0, 0.0, 0.0])
    centered = points - points.mean(axis=0)
    _values, vectors = np.linalg.eigh(np.cov(centered.T))
    projected = centered @ vectors
    extents = projected.max(axis=0) - projected.min(axis=0)
    order = np.argsort(extents)[::-1]
    return extents[order], vectors[:, order[0]]


def _taper(points, axis):
    """Width of the narrow end over the wide end along ``axis`` (1.0 = no taper)."""
    if len(points) < 12:
        return 1.0
    centered = points - points.mean(axis=0)
    along = centered @ axis
    radial = np.linalg.norm(centered - np.outer(along, axis), axis=1)
    low, high = along.min(), along.max()
    if high - low <= 0.0:
        return 1.0
    bins = np.clip(((along - low) / (high - low) * 5.0).astype(int), 0, 4)
    first = radial[bins == 0]
    last = radial[bins == 4]
    if len(first) == 0 or len(last) == 0:
        return 1.0
    wide, narrow = float(first.mean()), float(last.mean())
    if wide < narrow:
        wide, narrow = narrow, wide
    return narrow / wide if wide > 0.0 else 1.0


def _protrusion(segment_points, segment_centroid, reference):
    """``(protrusion, reach, offset)`` against the parent body.

    Two things have to hold for a feature to read as protruding: its center sits
    off the parent's center (offset), and it reaches as far out in that direction
    as the parent's silhouette does (reach). A horn scores high on both. A
    recessed eye disc scores high on offset and low on reach, which is the
    distinction between "sticks out" and "sunk into the flank".
    """
    points, center, radius = reference
    away = segment_centroid - center
    distance = float(np.linalg.norm(away))
    if radius <= 0.0 or distance < 1e-9:
        return 0.0, 1.0, 0.0
    direction = away / distance
    hull_reach = float(np.max((points - center) @ direction))
    segment_reach = float(np.max((segment_points - center) @ direction))
    if hull_reach <= 0.0:
        return 0.0, 1.0, 0.0
    reach = min(max(segment_reach / hull_reach, 0.0), 1.0)
    offset = min(distance / radius, 1.0)
    return reach * offset, reach, offset


def _reference(points, areas, centroids, face_indices):
    """Support geometry for protrusion: vertices, area-weighted center, mean radius."""
    weights = areas[face_indices]
    total = float(weights.sum())
    if total > 0.0:
        center = (centroids[face_indices] * weights[:, None]).sum(axis=0) / total
    else:
        center = points.mean(axis=0)
    radius = float(np.linalg.norm(points - center, axis=1).mean())
    return points, center, radius


def _position_words(position):
    words = []
    if position[2] >= 0.65:
        words.append("upper")
    elif position[2] <= 0.35:
        words.append("lower")
    if position[1] <= 0.35:
        words.append("front")
    elif position[1] >= 0.65:
        words.append("back")
    if position[0] <= 0.35:
        words.append("left")
    elif position[0] >= 0.65:
        words.append("right")
    return " ".join(words) or "center"


def _size_word(diagonal, model_diagonal):
    fraction = diagonal / model_diagonal if model_diagonal else 0.0
    if fraction >= 0.5:
        return "large"
    if fraction >= 0.2:
        return "medium"
    if fraction >= 0.07:
        return "small"
    return "tiny"


def _form_word(extents, taper, convexity):
    elongation = max(extents[0], 1e-9) / max(extents[1], 1e-9)
    flatness = max(extents[1], 1e-9) / max(extents[2], 1e-9)
    if flatness >= 4.0:
        return "flat blade" if elongation >= 2.0 else "flat plate"
    if taper <= 0.35:
        # One end collapses to a point: horns, spikes, claws and teeth all do this,
        # and it reads as a cone long before the region is formally elongated.
        return "long tapering spike" if elongation >= 2.5 else "tapering cone"
    if elongation >= 2.5:
        return "long shaft"
    if elongation >= 1.5:
        return "tapering lobe" if taper <= 0.6 else "elongated lobe"
    if convexity >= 0.9:
        if elongation < 1.2 and flatness < 1.3:
            return "rounded ball"
        return "shallow dome" if flatness >= 1.8 else "rounded lump"
    if convexity <= 0.6:
        return "creased or hollow patch"
    return "irregular patch"


def shape_hint(segment, paired, model_diagonal):
    """The one line a language model actually reads for this region."""
    words = [_size_word(segment["bbox_diagonal"], model_diagonal)]
    if paired:
        words.append("paired")
    words.append(_form_word(segment["principal_extent"], segment["taper"],
                            segment["convexity"]))
    hint = " ".join(words) + ", " + _position_words(segment["position"])
    if segment["covers_component"]:
        hint += ", separate body"
    if segment["protrusion"] >= 0.8:
        return hint + ", protruding"
    if segment["center_offset"] >= 0.5 and segment["surface_reach"] <= 0.85:
        return hint + ", recessed"
    if segment["protrusion"] <= 0.3:
        return hint + ", central mass"
    return hint + ", flush"


def describe(vertices, triangles, graph, face_indices, reference, model):
    """Everything about one region except its id and its symmetry partner."""
    areas, centroids = graph["areas"], graph["centroids"]
    faces = np.asarray(face_indices, dtype=np.int64)
    corners = np.unique(triangles[faces].reshape(-1))
    points = vertices[corners]

    weights = areas[faces]
    total_area = float(weights.sum())
    if total_area > 0.0:
        centroid = (centroids[faces] * weights[:, None]).sum(axis=0) / total_area
    else:
        centroid = points.mean(axis=0)

    low, high = points.min(axis=0), points.max(axis=0)
    extent = high - low
    span = np.where(model["extent"] > 0.0, model["extent"], 1.0)
    position = (centroid - model["min"]) / span

    inside = graph["_interior"]
    interior = inside.get(int(graph["labels"][faces[0]]), (0, 0.0, 0, 0))
    edge_count, angle_sum, convex_count, boundary = interior
    curvature = angle_sum / edge_count if edge_count else 0.0
    convexity = convex_count / edge_count if edge_count else 1.0

    extents, axis = _principal(points)
    taper = _taper(points, axis)
    protrusion, reach, offset = _protrusion(points, centroid, reference)

    return {
        "face_count": int(len(faces)),
        "face_indices": [int(i) for i in faces],
        "area": _round(total_area, 3),
        "bbox": {"min": [_round(v, 3) for v in low], "max": [_round(v, 3) for v in high]},
        "extent": [_round(v, 3) for v in extent],
        "bbox_diagonal": _round(float(np.linalg.norm(extent)), 3),
        "centroid": [_round(v, 3) for v in centroid],
        "position": [_round(v, 3) for v in position],
        "principal_extent": [_round(v, 3) for v in extents],
        "elongation": _round(extents[0] / max(extents[1], 1e-9), 3),
        "flatness": _round(extents[1] / max(extents[2], 1e-9), 3),
        "taper": _round(taper, 3),
        "protrusion": _round(protrusion, 3),    # reach x offset, 0 buried, 1 a tip
        "surface_reach": _round(reach, 3),      # 1 = out on the parent silhouette
        "center_offset": _round(offset, 3),     # 1 = a body radius off the parent center
        "curvature": _round(curvature, 2),      # mean signed dihedral, degrees
        "convexity": _round(convexity, 3),      # share of interior edges not concave
        "open_edges": int(boundary),
    }


def _interior_stats(labels, pairs, angles, region_count):
    """Per region: interior edge count, angle sum, non-concave count, boundary edges."""
    stats = {index: [0, 0.0, 0, 0] for index in range(region_count)}
    if len(pairs) == 0:
        return {index: tuple(value) for index, value in stats.items()}
    left, right = labels[pairs[:, 0]], labels[pairs[:, 1]]
    same = left == right
    for label, angle in zip(left[same].tolist(), angles[same].tolist()):
        entry = stats[label]
        entry[0] += 1
        entry[1] += angle
        if angle > -FLAT_ANGLE:
            entry[2] += 1
    for label in left[~same].tolist():
        stats[label][3] += 1
    for label in right[~same].tolist():
        stats[label][3] += 1
    return {index: tuple(value) for index, value in stats.items()}


# --------------------------------------------------------------------------
# symmetry
# --------------------------------------------------------------------------

def pair_by_symmetry(segments, mirror_x, model_diagonal):
    """Match each segment to its near-mirror across the model's X midplane.

    Eyes, horns, claws and fins come in pairs, and a confirmed pair is the single
    strongest hint that a region is a feature rather than background surface.
    """
    tolerance = 0.02 * model_diagonal
    candidates = []
    for i, a in enumerate(segments):
        mirrored = np.array([2.0 * mirror_x - a["centroid"][0],
                             a["centroid"][1], a["centroid"][2]])
        for j in range(i + 1, len(segments)):
            b = segments[j]
            # Mirror-instanced features match exactly; sculpted ones drift a
            # little, so size only has to be close. Position does the real work.
            if abs(a["face_count"] - b["face_count"]) > 0.1 * max(
                    a["face_count"], b["face_count"]):
                continue
            if abs(a["area"] - b["area"]) / max(a["area"], b["area"], 1e-9) > 0.05:
                continue
            distance = float(np.linalg.norm(mirrored - np.array(b["centroid"])))
            if distance <= tolerance:
                candidates.append((distance, i, j))

    taken = set()
    for _distance, i, j in sorted(candidates, key=lambda item: (item[0], item[1], item[2])):
        if i in taken or j in taken:
            continue
        taken.add(i)
        taken.add(j)
        segments[i]["symmetry"] = "paired"
        segments[j]["symmetry"] = "paired"
        segments[i]["symmetry_partner"] = segments[j]["id"]
        segments[j]["symmetry_partner"] = segments[i]["id"]

    for index, segment in enumerate(segments):
        if index in taken:
            continue
        segment["symmetry_partner"] = None
        straddles = (segment["bbox"]["min"][0] < mirror_x < segment["bbox"]["max"][0]
                     and abs(segment["centroid"][0] - mirror_x) <= tolerance)
        segment["symmetry"] = "on_midplane" if straddles else "unique"


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def analyze(path, options):
    objects = load_objects(path)

    all_points = np.concatenate([obj["vertices"][np.unique(obj["triangles"])]
                                 for obj in objects])
    model_min, model_max = all_points.min(axis=0), all_points.max(axis=0)
    model = {
        "min": model_min,
        "max": model_max,
        "extent": model_max - model_min,
        "diagonal": float(np.linalg.norm(model_max - model_min)) or 1.0,
    }
    mirror_x = float((model_min[0] + model_max[0]) / 2.0)

    results = []
    flat = []
    total_components = 0
    total_triangles = sum(len(obj["triangles"]) for obj in objects) or 1
    for obj in objects:
        vertices, triangles = obj["vertices"], obj["triangles"]
        # The segment budget is shared out by triangle count, so a multi-object
        # file still lands near the cap overall rather than per object.
        budget = None
        if options.max_segments:
            budget = max(1, int(round(
                options.max_segments * len(triangles) / total_triangles)))
        graph = segment_object(vertices, triangles, options, budget)
        labels = graph["labels"]
        region_count = int(labels.max()) + 1 if len(labels) else 0
        graph["_interior"] = _interior_stats(labels, graph["pairs"], graph["angles"],
                                             region_count)
        component_count = int(graph["components"].max()) + 1 if len(labels) else 0
        total_components += component_count

        faces_by_region = {}
        for face, label in enumerate(labels.tolist()):
            faces_by_region.setdefault(label, []).append(face)
        faces_by_component = {}
        for face, label in enumerate(graph["components"].tolist()):
            faces_by_component.setdefault(label, []).append(face)

        # Protrusion needs something to protrude from. A component holding several
        # regions is that reference; a component that is a single region is a body
        # in its own right, so it is measured against the whole model instead.
        regions_per_component = {}
        for label, faces in faces_by_region.items():
            component = int(graph["components"][faces[0]])
            regions_per_component[component] = regions_per_component.get(component, 0) + 1

        model_reference = _reference(
            vertices[np.unique(triangles)], graph["areas"], graph["centroids"],
            np.arange(len(triangles)))
        component_references = {}

        described = []
        for label in sorted(faces_by_region,
                            key=lambda key: (-len(faces_by_region[key]),
                                             faces_by_region[key][0])):
            faces = faces_by_region[label]
            component = int(graph["components"][faces[0]])
            if regions_per_component[component] > 1:
                if component not in component_references:
                    component_faces = np.asarray(faces_by_component[component])
                    corners = np.unique(triangles[component_faces].reshape(-1))
                    component_references[component] = _reference(
                        vertices[corners], graph["areas"], graph["centroids"],
                        component_faces)
                reference = component_references[component]
            else:
                reference = model_reference

            entry = describe(vertices, triangles, graph, faces, reference, model)
            entry["object_id"] = obj["object_id"]
            entry["part"] = obj["part"]
            entry["component"] = component
            entry["covers_component"] = len(faces) == len(faces_by_component[component])
            described.append(entry)

        results.append({
            "object_id": obj["object_id"],
            "part": obj["part"],
            "triangle_count": int(len(triangles)),
            "component_count": component_count,
            "segments": described,
        })
        flat.extend(described)

    width = max(2, len(str(len(flat))))
    for index, segment in enumerate(flat, start=1):
        segment["id"] = "s" + str(index).zfill(width)
    pair_by_symmetry(flat, mirror_x, model["diagonal"])
    for segment in flat:
        segment["shape_hint"] = shape_hint(
            segment, segment["symmetry"] == "paired", model["diagonal"])

    ordered_keys = ["id", "object_id", "part", "component", "shape_hint", "face_count",
                    "area", "centroid", "position", "extent", "bbox",
                    "bbox_diagonal", "principal_extent", "elongation", "flatness",
                    "taper", "protrusion", "surface_reach", "center_offset",
                    "curvature", "convexity", "open_edges",
                    "covers_component", "symmetry", "symmetry_partner",
                    "face_indices"]
    for entry in results:
        entry["segments"] = [
            {key: segment[key] for key in ordered_keys} for segment in entry["segments"]]

    document = {
        "source": os.path.abspath(path),
        "units": "mm",
        "axes": AXES,
        "parameters": {
            "concave_angle": options.concave_angle,
            "convex_angle": options.convex_angle,
            "min_faces": options.min_faces,
            "max_segments": options.max_segments,
        },
        "objects": results,
        "summary": {
            "object_count": len(results),
            "triangle_count": sum(entry["triangle_count"] for entry in results),
            "component_count": total_components,
            "segment_count": len(flat),
            "bbox": {"min": [_round(v, 3) for v in model_min],
                     "max": [_round(v, 3) for v in model_max]},
            "extent": [_round(v, 3) for v in model["extent"]],
            "mirror_plane_x": _round(mirror_x, 3),
            "symmetry_pairs": sum(1 for s in flat if s["symmetry"] == "paired") // 2,
            "segments": [{
                "id": s["id"],
                "object_id": s["object_id"],
                "face_count": s["face_count"],
                "shape_hint": s["shape_hint"],
                "symmetry_partner": s["symmetry_partner"],
            } for s in flat],
        },
    }
    return document


_NUMBER_LIST_RE = re.compile(r"\[[\s\d.,eE+-]*\]")


def serialize(document):
    """Indented JSON, except that lists of plain numbers stay on one line.

    Indenting a segment's face index list turns a readable payload into a
    hundred thousand lines of one integer each; the same applies, less
    dramatically, to every centroid and bounding box.
    """
    def collapse(match):
        items = [item.strip() for item in match.group(0)[1:-1].split(",")]
        return "[" + ", ".join(item for item in items if item) + "]"

    return _NUMBER_LIST_RE.sub(collapse, json.dumps(document, indent=1)) + "\n"


def print_summary(document, stream=sys.stdout):
    summary = document["summary"]
    stream.write("%s\n" % os.path.basename(document["source"]))
    stream.write("  %d object(s), %d triangles, %d component(s), %d segment(s)\n" % (
        summary["object_count"], summary["triangle_count"],
        summary["component_count"], summary["segment_count"]))
    stream.write("  extent %s mm, %d symmetry pair(s)\n" % (
        " x ".join("%g" % v for v in summary["extent"]), summary["symmetry_pairs"]))
    width = max((len(s["id"]) for s in summary["segments"]), default=3)
    for segment in summary["segments"]:
        partner = ""
        if segment["symmetry_partner"]:
            partner = "  (pairs %s)" % segment["symmetry_partner"]
        stream.write("  %-*s %7d faces  %s%s\n" % (
            width, segment["id"], segment["face_count"], segment["shape_hint"], partner))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Segment a model into described regions for feature labelling.")
    parser.add_argument("--input", required=True, help="STL or 3MF to segment")
    parser.add_argument("--output", required=True, help="path for the segments JSON")
    parser.add_argument("--max-segments", type=int, default=DEFAULT_MAX_SEGMENTS,
                        help="upper bound on segments (default %d)" % DEFAULT_MAX_SEGMENTS)
    parser.add_argument("--min-faces", type=int, default=DEFAULT_MIN_FACES,
                        help="regions smaller than this are absorbed (default %d)"
                             % DEFAULT_MIN_FACES)
    parser.add_argument("--concave-angle", type=float, default=DEFAULT_CONCAVE_ANGLE,
                        help="concave crease angle that cuts, in degrees (default %g)"
                             % DEFAULT_CONCAVE_ANGLE)
    parser.add_argument("--convex-angle", type=float, default=DEFAULT_CONVEX_ANGLE,
                        help="convex fold angle that cuts, in degrees (default %g)"
                             % DEFAULT_CONVEX_ANGLE)
    parser.add_argument("--quiet", action="store_true", help="write JSON only")
    options = parser.parse_args(argv)

    if not os.path.isfile(options.input):
        sys.stderr.write("segment: no such file: %s\n" % options.input)
        return 2
    if os.path.realpath(options.output) == os.path.realpath(options.input):
        # Writing JSON over the model would destroy it, and the whole plugin
        # rests on the input file coming back byte for byte.
        sys.stderr.write(
            "segment: --output would overwrite the input model; choose another path\n")
        return 2
    if options.max_segments is not None and options.max_segments < 1:
        sys.stderr.write("segment: --max-segments must be at least 1\n")
        return 2

    try:
        document = analyze(options.input, options)
    except Exception as error:                 # surfaced to the slash command
        sys.stderr.write("segment: cannot segment %s: %s\n" % (options.input, error))
        return 1

    directory = os.path.dirname(os.path.abspath(options.output))
    if directory and not os.path.isdir(directory):
        sys.stderr.write("segment: output directory does not exist: %s\n" % directory)
        return 2
    with open(options.output, "w") as handle:
        handle.write(serialize(document))

    summary = document["summary"]
    count = summary["segment_count"]
    largest = max((entry["face_count"] for entry in summary["segments"]), default=0)
    if count < 4 and largest >= 0.9 * summary["triangle_count"]:
        # Smooth organic models can have real feature boundaries that are broad
        # valleys rather than sharp creases; say so instead of silently returning
        # one useless region.
        sys.stderr.write(
            "segment: one region covers %d%% of the model; if features are not "
            "separating, retry with a lower --concave-angle (now %g)\n"
            % (round(100.0 * largest / max(summary["triangle_count"], 1)),
               options.concave_angle))
    if options.max_segments and count > options.max_segments:
        sys.stderr.write(
            "segment: %d segments exceeds --max-segments %d; separate bodies are "
            "never merged into each other\n" % (count, options.max_segments))
    if not options.quiet:
        print_summary(document)
        print("wrote %s" % options.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
