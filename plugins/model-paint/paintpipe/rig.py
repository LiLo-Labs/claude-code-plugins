"""The observation rig: many angles, many lightings, ONE coordinate system.

Every belief in this pipeline is formed by looking at a picture, and every
picture is taken by this module. That is the point of it existing: if two
stages build their own cameras, their claims are expressed in two different
places and nothing can be compared, fused or contradicted. Here there is one
camera builder, one ray cast per pose, and one routing table from a pixel back
to the surface -- so "the agent pointed here" means the same thing in the
naming pass, the recovery ladder and the colour critic.

THE COORDINATE SYSTEM IS THE BASE REGION, NOT THE PIXEL AND NOT THE FACE.

    pixel -> hit_id -> face -> tree["base"] region -> merge-tree node

`hit_id` is a routing key (see render.py) and a face is a fact about the
tessellation, so neither is a place a belief can live. Base regions are the
scale-space index's own partition of the surface: they tile it completely,
they are the same regions from every camera, and their edges are relief edges
and concave junctions found in 3D. A claim expressed as a set of base regions
therefore has a boundary the geometry drew, from any angle, at no cost.

This is what replaces flood fill. A flood needed a barrier map, an allowance
and a stopping rule, and every one of those was a number somebody chose; the
regions are already there and already bounded. Nothing in this module grows,
dilates, floods or draws.

LIGHTING IS PART OF THE MEASUREMENT, NOT DECORATION.

A barnacle field under flat light is a grey texture; under a raking light it
is a field of discrete shadows, and the agent can count it. So each pose is
lit several ways and each lighting is a separate look. The lights are built in
the CAMERA's screen basis rather than the object's, because an object-fixed
raking light degenerates: `render.RIGS["raking_b"]` keys off the object's
front, the grazing projection cancels the component along the view axis, and
from any camera facing the front the key light is annihilated -- that rig
returns flat ambient and reads as a genuine look while carrying no relief
information at all. A screen-basis light cannot degenerate, because it is
defined perpendicular to the view direction by construction.

Casting is shared: lights cannot move a silhouette, so one pose is cast once
and relit for every lighting. Four lightings on twelve poses is twelve casts,
not forty-eight.
"""

import hashlib
import os

import numpy as np

from . import render as render_module


# Lightings are defined by where the key sits in the camera's own screen basis,
# as (right, up) weights, plus how much of the light is ambient. `None` is the
# unlit channel: pure albedo, for reading shape without shadow.
#
# The three raking directions are not decoration either. Relief throws shadow
# ALONG the light, so a ridge running parallel to the key light casts nothing
# and stays invisible; three keys at different screen angles guarantee no
# orientation of detail hides in every look. The shell's weed fronds run one
# way and its ribs run across them, and a single raking angle found one family
# and missed the other.
LIGHTINGS = {
    "flat":      {"key": None, "ambient": 1.00},
    "raking_l":  {"key": (-0.94, 0.22), "ambient": 0.30, "strength": 0.78},
    "raking_t":  {"key": (0.12, 0.96), "ambient": 0.30, "strength": 0.78},
    "raking_tr": {"key": (0.72, 0.66), "ambient": 0.30, "strength": 0.78},
    # A soft three-quarter key, closest to how a person would photograph the
    # print on a desk. It is the reference look for naming, because it is the
    # one whose shading a model has seen a million of in training.
    "studio":    {"key": (0.42, 0.58), "ambient": 0.34, "strength": 0.70,
                  "toward_viewer": 0.55},
}

# The default identify loop: four poses' worth of angular spread at each of
# three elevations, each lit two ways. Azimuth alone is not spread -- two
# cameras at the same elevation see the same foreshortening and the same
# self-occlusion pattern, so agreeing with each other means less than it looks.
# Elevation and roll change what the silhouette is made of, which is what makes
# a second look an independent test rather than a repeat.
DEFAULT_ELEVATIONS = ((14.0, 0.0), (40.0, 25.0), (-22.0, -18.0))
DEFAULT_LIGHTINGS = ("studio", "raking_l")


class Pose:
    """One camera position, cast once, ready to be lit any number of ways."""

    def __init__(self, name, camera, geometry):
        self.name = name
        self.camera = camera
        self.geometry = geometry

    @property
    def hit_id(self):
        return self.geometry["hit_id"]

    @property
    def visible(self):
        return self.geometry["visible"]


class View:
    """One pose under one lighting: the unit an agent is actually shown.

    Carries its own PNG path and, through its pose, the routing table that
    turns any pixel it contains back into a place on the surface.
    """

    def __init__(self, pose, lighting, image, path=None):
        self.pose = pose
        self.lighting = lighting
        self.image = image
        self.path = path

    @property
    def name(self):
        return "%s-%s" % (self.pose.name, self.lighting)

    @property
    def pixels(self):
        return int(self.pose.camera.pixels)


def poses(mesh, up, pixels=900, elevations=DEFAULT_ELEVATIONS, per_ring=4,
          zoom=1.0, centre=None, cavity_taps=0, log=None):
    """Cameras spread over azimuth, elevation and roll; each cast exactly once.

    `zoom` and `centre` frame a detail. A zoom is a real camera move and not a
    crop: the rays are recast, so a close look resolves detail the wide look
    never sampled. That is the entire reason a second, closer look is worth
    paying for.
    """
    from . import preview

    axis = np.asarray(up, dtype=float)
    axis = axis / max(np.linalg.norm(axis), 1e-12)
    if centre is None:
        centre = mesh.vertices.mean(axis=0)
    centre = np.asarray(centre, dtype=float)
    radius = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0 * 1.06
    radius = radius / max(float(zoom), 1e-6)

    out = []
    for elevation, roll in elevations:
        for index, direction in enumerate(
                preview.orbit(per_ring, elevation, start_deg=elevation * 1.7,
                              up=axis)):
            # Roll tips the camera's up vector out of the object's up. Two
            # views of one instance then differ in which way the detail runs
            # across the frame, so a shape read is not simply repeated.
            spun = axis
            if abs(roll) > 1e-6:
                angle = np.radians(roll)
                side = np.cross(axis, np.asarray(direction, dtype=float))
                norm = np.linalg.norm(side)
                if norm > 1e-9:
                    spun = axis * np.cos(angle) + (side / norm) * np.sin(angle)
            camera = render_module.Camera(direction, spun, centre, radius,
                                          pixels)
            name = "e%+03d-a%02d" % (int(round(elevation)), index)
            geometry = render_module.geometry_bundle(mesh, camera,
                                                     cavity_taps=cavity_taps)
            out.append(Pose(name, camera, geometry))
            if log:
                log("    pose %s: %d visible px"
                    % (name, int(geometry["visible"].sum())))
    return out


def plan_poses(mesh, tree, up, pixels=900, target_views=3, budget=12,
               candidates=48, scout_pixels=256, elevations=None, log=None):
    """Choose WHERE to look so that everything is seen enough times.

    Recall in the survey is bounded by how often a feature is visible, not by
    the consensus gate: an instance seen from two poses can never clear a
    two-vote threshold with any margin, and dropping it is the correct
    response to thin evidence rather than a bug to be tuned away. Measured on
    the dragon, a fixed ring grid left most dorsal spikes visible in two or
    three of twelve looks, and 48 of 61 climbs were discarded for want of
    agreement.

    So stop guessing the number of views and cover the surface instead. Scout
    cheaply from many directions, then greedily take the direction that most
    reduces the REMAINING deficit -- area still short of `target_views` looks
    -- until the deficit is gone or the budget is spent. Greedy set cover is
    the right tool and gets within a known factor of optimal; more usefully,
    it stops on its own when the model is covered, so an easy model buys fewer
    views and a self-occluding one buys more.

    Scouting is depth only, at low resolution, with no lighting and no model
    calls, so a 48-direction scout costs a fraction of one full pose.
    """
    from . import render as render_module

    base = region_of_face(tree)
    areas = np.zeros(int(tree["regions"]), dtype=float)
    face_area = np.asarray(mesh.area_faces, dtype=float)
    np.add.at(areas, base, face_area)

    axis = np.asarray(up, dtype=float)
    axis = axis / max(np.linalg.norm(axis), 1e-12)
    centre = mesh.vertices.mean(axis=0)
    radius = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0 * 1.06

    directions = render_module.fibonacci_directions(int(candidates))
    seen_sets = []
    for direction in directions:
        camera = render_module.Camera(direction, axis, centre, radius,
                                      int(scout_pixels))
        geometry = render_module.geometry_bundle(mesh, camera, cavity_taps=0)
        hit = geometry["hit_id"]
        found = hit[hit >= 0]
        if not len(found):
            seen_sets.append(np.array([], dtype=np.int64))
            continue
        regions, counts = np.unique(base[found], return_counts=True)
        seen_sets.append(regions[counts >= 3].astype(np.int64))

    covered = np.zeros(int(tree["regions"]), dtype=int)
    chosen, deficits = [], []
    for _pick in range(int(budget)):
        deficit = np.clip(target_views - covered, 0, None) * areas
        remaining = float(deficit.sum())
        deficits.append(remaining)
        if remaining <= 0:
            break
        gains = [float(deficit[regions].sum()) if len(regions) else 0.0
                 for regions in seen_sets]
        best = int(np.argmax(gains))
        if gains[best] <= 0:
            break
        chosen.append(best)
        covered[seen_sets[best]] += 1
        seen_sets[best] = np.array([], dtype=np.int64)   # never picked twice

    report = coverage_report(covered, areas, target_views)
    if log:
        log("  coverage: %d poses chosen from %d scouted; %.1f%% of the "
            "surface (%.1f%% of regions) reaches %d+ looks%s"
            % (len(chosen), candidates, 100.0 * report["area_share_met"],
               100.0 * report["region_share_met"], target_views,
               ("; %d regions (%.1f%% of area) are unreachable from outside"
                % (report["unreachable_regions"],
                   100.0 * report["unreachable_area_share"]))
               if report["unreachable_regions"] else ""))
    return [directions[i] for i in chosen], covered, areas


def coverage(poses, tree, base=None, min_pixels=4):
    """How many poses actually see each base region. The audit for plan_poses."""
    if base is None:
        base = region_of_face(tree)
    counted = np.zeros(int(tree["regions"]), dtype=int)
    for pose in poses:
        regions, _counts = visible_regions(pose, base, min_pixels=min_pixels)
        counted[regions] += 1
    return counted


def coverage_report(counted, areas, target_views):
    """One statistic, computed the same way by the plan and by the audit.

    The plan and the audit disagreed by 27 points on the dragon -- 92.3%
    against 65.3% -- and neither number was wrong: one was area-weighted and
    the other counted regions, so a model with many small regions and a few
    large ones reads completely differently through the two. Two numbers that
    are both called "coverage" and cannot be compared is worse than either
    alone, because it hides whether the plan delivered what it promised.

    Area-weighted is the honest default here: consensus is about whether a
    FEATURE was seen enough times, and a feature's chance of being seen scales
    with how much surface it presents, not with how many regions it was cut
    into.
    """
    counted = np.asarray(counted)
    areas = np.asarray(areas, dtype=float)
    total = float(areas.sum())
    met = counted >= target_views
    unreachable = counted == 0
    return {
        "target_views": int(target_views),
        "area_share_met": float(areas[met].sum() / max(total, 1e-9)),
        "region_share_met": float(met.mean()),
        "median_views": int(np.median(counted)),
        "unreachable_regions": int(unreachable.sum()),
        # Surface no camera outside the model can reach is a fact about the
        # object, not a shortfall in the plan: a print-in-place model has real
        # interior faces between its joints, and counting them against
        # coverage makes every articulated model look uncovered forever.
        "unreachable_area_share": float(areas[unreachable].sum()
                                        / max(total, 1e-9)),
    }


def frame_on(mesh, faces, margin=1.35):
    """Where to put the camera to see THESE faces properly, and how wide.

    A whole-object view spends its pixels on the whole object. A barnacle in a
    520px view of a 190mm shell is about ten pixels across, and no number of
    rounds lets anyone draw a boundary they cannot see -- the limit is the
    render, not the loop. So when the work is a small part, the camera goes to
    the part, which is what a person does when they bring a model up to their
    eye for the fine bits.

    The margin keeps some surroundings in shot, because a boundary is a
    statement about two things and the neighbour has to be visible to place it.
    """
    faces = np.asarray(faces, dtype=np.int64)
    if not len(faces):
        return None, None
    corners = mesh.vertices[mesh.faces[faces].ravel()]
    low, high = corners.min(axis=0), corners.max(axis=0)
    centre = 0.5 * (low + high)
    radius = float(np.max(high - low)) / 2.0 * float(margin)
    whole = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0 * 1.06
    return centre, min(max(radius, whole * 0.02), whole)


def poses_from(mesh, directions, up, pixels=900, roll_cycle=(0.0, 22.0, -18.0),
               centre=None, radius=None, log=None):
    """Cast the chosen directions. Roll still cycles, for the reason it always did:
    two looks that differ only in azimuth see the same foreshortening, so rolling
    makes the second an independent test of a shape rather than a repeat.

    `centre` and `radius` frame a detail instead of the whole piece. That is a
    real camera move: the pixel footprint changes with it, so a part that was
    ten pixels across becomes hundreds and its boundary becomes something that
    can actually be drawn.
    """
    from . import render as render_module

    axis = np.asarray(up, dtype=float)
    axis = axis / max(np.linalg.norm(axis), 1e-12)
    if centre is None:
        centre = mesh.vertices.mean(axis=0)
    centre = np.asarray(centre, dtype=float)
    if radius is None:
        radius = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0 * 1.06
    out = []
    for index, direction in enumerate(directions):
        roll = roll_cycle[index % len(roll_cycle)]
        spun = axis
        if abs(roll) > 1e-6:
            side = np.cross(axis, np.asarray(direction, dtype=float))
            norm = np.linalg.norm(side)
            if norm > 1e-9:
                angle = np.radians(roll)
                spun = axis * np.cos(angle) + (side / norm) * np.sin(angle)
        camera = render_module.Camera(direction, spun, centre, radius, pixels)
        geometry = render_module.geometry_bundle(mesh, camera, cavity_taps=0)
        out.append(Pose("c%02d" % index, camera, geometry))
        if log:
            log("    pose c%02d: %d visible px"
                % (index, int(geometry["visible"].sum())))
    return out


def light(pose, lighting):
    """Apply one lighting to an already-cast pose. Never moves a silhouette."""
    spec = LIGHTINGS[lighting]
    visible = pose.geometry["visible"]
    lit = np.zeros(visible.shape)
    if not visible.any():
        return lit
    value = np.full(int(visible.sum()), float(spec["ambient"]))
    key = spec.get("key")
    if key is not None:
        camera = pose.camera
        # Built in the screen basis, so it is perpendicular to the view axis by
        # construction and cannot be cancelled by the grazing projection the
        # object-fixed rigs use.
        direction = camera.right * float(key[0]) + camera.up * float(key[1])
        direction = direction - camera.forward * float(
            spec.get("toward_viewer", 0.08))
        direction = direction / max(np.linalg.norm(direction), 1e-12)
        normal = pose.geometry["normal"][visible]
        value = value + float(spec.get("strength", 0.75)) * np.clip(
            normal @ direction, 0.0, 1.0)
    lit[visible] = np.clip(value, 0.0, 1.0)
    return lit


def observe(mesh, up, out_dir, pixels=900, elevations=DEFAULT_ELEVATIONS,
            per_ring=4, lightings=DEFAULT_LIGHTINGS, zoom=1.0, centre=None,
            prefix="view", tree=None, target_views=3, budget=12, log=None):
    """The rig: every pose under every lighting, written as PNGs.

    Returns (views, poses). Views are what an agent is shown; poses are what a
    claim is resolved against, and several views share one pose, so a point
    made in a raking look and a point made in a studio look land in exactly
    the same place.
    """
    os.makedirs(out_dir, exist_ok=True)
    if tree is not None and zoom == 1.0 and centre is None:
        # Covered rather than gridded. Only for the whole-model rig: a zoomed
        # or re-centred rig is framing a detail, where the question is not
        # "has everything been seen" and coverage of the whole surface is the
        # wrong objective.
        directions, _covered, _areas = plan_poses(
            mesh, tree, up, pixels=pixels, target_views=target_views,
            budget=budget, log=log)
        made = poses_from(mesh, directions, up, pixels=pixels, log=log)
    else:
        made = poses(mesh, up, pixels=pixels, elevations=elevations,
                     per_ring=per_ring, zoom=zoom, centre=centre, log=log)
    views = []
    for pose in made:
        for lighting in lightings:
            image = light(pose, lighting)
            path = os.path.join(out_dir, "%s-%s-%s.png"
                                % (prefix, pose.name, lighting))
            write_png(image, pose.visible, path)
            views.append(View(pose, lighting, image, path))
    if log:
        log("  rig: %d poses x %d lightings = %d views at %dpx"
            % (len(made), len(lightings), len(views), pixels))
    return views, made


def write_png(image, visible, path, background=0.97):
    """Greyscale shading on a light ground, which is what the agent reads."""
    from PIL import Image
    canvas = np.full(image.shape, float(background))
    canvas[visible] = image[visible]
    Image.fromarray((np.clip(canvas, 0.0, 1.0) * 255).astype(np.uint8)).save(path)
    return path


# ------------------------------------------------------------------ routing

def region_of_face(tree):
    """The face -> base region table. The one lookup everything else is built on."""
    return np.asarray(tree["base"], dtype=np.int64)


def point_to_region(pose, base, x, y, radius=3):
    """A pixel an agent pointed at -> the base region it names.

    The neighbourhood is not smoothing and it is not a flood. A coordinate that
    lands one pixel off a silhouette hits background and returns nothing, and
    the honest reading of that is not "no feature" but "the agent aimed at the
    thing and missed the edge by a pixel". So a miss looks in a small disc for
    the nearest surface and takes the region the majority of that disc sits on.
    A hit uses its own pixel and the disc is never consulted.

    Returns -1 when nothing within the disc is surface at all, which is a real
    answer: the agent pointed at empty space.
    """
    hit = pose.hit_id
    height, width = hit.shape
    x, y = int(round(x)), int(round(y))
    if not (0 <= x < width and 0 <= y < height):
        return -1
    if hit[y, x] >= 0:
        return int(base[hit[y, x]])
    y0, y1 = max(0, y - radius), min(height, y + radius + 1)
    x0, x1 = max(0, x - radius), min(width, x + radius + 1)
    patch = hit[y0:y1, x0:x1]
    found = patch[patch >= 0]
    if not len(found):
        return -1
    regions, counts = np.unique(base[found], return_counts=True)
    return int(regions[int(np.argmax(counts))])


def visible_regions(pose, base, min_pixels=4):
    """Which base regions this pose could actually have seen, and how well.

    Visibility is not estimated from normals -- it is read off the depth
    buffer, so it is exact. That exactness is what lets consensus be fair: a
    feature hidden in five views is judged only on the views where it showed,
    instead of being punished for the five.

    `min_pixels` drops regions that grazed the edge of a silhouette at a couple
    of pixels. Being technically visible at three pixels is not being legible,
    and counting it as a view that "could have seen it" makes every consensus
    share too harsh.
    """
    hit = pose.hit_id
    found = hit[hit >= 0]
    if not len(found):
        return np.array([], dtype=np.int64), np.array([], dtype=np.int64)
    regions, counts = np.unique(base[found], return_counts=True)
    keep = counts >= int(min_pixels)
    return regions[keep].astype(np.int64), counts[keep].astype(np.int64)


def region_faces(tree, regions):
    """The faces of a set of base regions. The inverse of the routing table."""
    base = np.asarray(tree["base"], dtype=np.int64)
    return np.flatnonzero(np.isin(base, np.asarray(list(regions),
                                                   dtype=np.int64)))


def ancestors(tree, region):
    """The chain of merge-tree nodes above one base region, innermost first.

    This is the ladder a claim climbs when a feature is bigger than the region
    the agent happened to point at. Every rung is a real node with a real
    boundary, so climbing it can never produce a shape the geometry did not
    already contain -- which is exactly what a flood could not promise.
    """
    parents = parent_table(tree)
    chain, node = [], int(region)
    seen = set()
    while node is not None and node not in seen:
        seen.add(node)
        chain.append(node)
        node = parents.get(node)
    return chain


def parent_table(tree):
    """child -> parent over the merge forest, built once and cached on the tree."""
    cached = tree.get("_parents")
    if cached is not None:
        return cached
    children = tree["children"]
    parents = {}
    for node in range(len(children)):
        left, right = children[node]
        if left >= 0:
            parents[int(left)] = node
        if right >= 0:
            parents[int(right)] = node
    tree["_parents"] = parents
    return parents


def node_regions(tree, node):
    """The base regions under one merge-tree node."""
    cache = tree.setdefault("_leaves", {})
    key = int(node)
    if key in cache:
        return cache[key]
    from . import segment3d  # noqa: F401  (puts scripts/ on sys.path)
    import index_persist
    leaves = []
    index_persist.leaves_of(tree["children"], key, int(tree["regions"]), leaves)
    out = np.asarray(sorted(set(int(v) for v in leaves)), dtype=np.int64)
    cache[key] = out
    return out


EVIDENCE_BLURS = (0.0, 2.0, 5.0)


def edge_evidence(mesh, directions=None, pixels=768, lightings=("raking_l",
                                                                "raking_t",
                                                                "studio"),
                  up=(0.0, 0.0, 1.0), log=None):
    """What the camera sees as an edge, per adjacent face pair. No model calls.

    Geometry measures surfaces no camera can see; the camera notices edges a
    person would while geometry blurs across them. They fail in different
    places, which is the only good reason to combine two signals -- and on a
    soft-relief model it is the difference between a barnacle field that is one
    region and one that is hundreds.

    Three blur scales are kept SEPARATE rather than summed, because a fine
    crease between two cups and the broad edge where a ridge meets a panel are
    different scales of evidence; `index_regions.edge_weights` takes the
    maximum across them, which says "visible as an edge at SOME scale" instead
    of "visible at the one I picked".

    Several lightings for the same reason a raking light exists at all: relief
    throws shadow ALONG the light, so an edge running parallel to the key casts
    nothing and is invisible in that look however sharp it is.

    A pair no direction could see contributes NOTHING rather than a zero.
    Scoring an unseen pair as edge-free quietly merges every enclosed cavity
    into whatever surrounds it, and about a fifth of a detailed model's pairs
    are interior.
    """
    from scipy import ndimage
    from . import render as render_module

    pairs = np.asarray(mesh.face_adjacency, dtype=np.int64)
    count = len(mesh.faces)
    low = np.minimum(pairs[:, 0], pairs[:, 1]).astype(np.int64)
    high = np.maximum(pairs[:, 0], pairs[:, 1]).astype(np.int64)
    keys = low * np.int64(count) + high
    order = np.argsort(keys, kind="stable")
    sorted_keys = keys[order]

    totals = np.zeros((len(EVIDENCE_BLURS), len(pairs)), dtype=np.float64)
    seen = np.zeros(len(pairs), dtype=np.float64)

    if directions is None:
        directions = render_module.fibonacci_directions(14)
    centre = mesh.vertices.mean(axis=0)
    radius = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0 * 1.06

    for number, direction in enumerate(np.asarray(directions, dtype=float)):
        camera = render_module.Camera(direction, up, centre, radius, pixels)
        geometry = render_module.geometry_bundle(mesh, camera, cavity_taps=0)
        picks = geometry["hit_id"]
        if not (picks >= 0).any():
            continue
        pose = Pose("evidence-%02d" % number, camera, geometry)
        for lighting in lightings:
            grey = light(pose, lighting)
            for slot, sigma in enumerate(EVIDENCE_BLURS):
                field = grey if sigma <= 0 else ndimage.gaussian_filter(grey,
                                                                        sigma)
                for axis in (0, 1):
                    if axis == 0:
                        a, b = picks[:-1, :], picks[1:, :]
                        fa_, fb_ = field[:-1, :], field[1:, :]
                    else:
                        a, b = picks[:, :-1], picks[:, 1:]
                        fa_, fb_ = field[:, :-1], field[:, 1:]
                    live = (a >= 0) & (b >= 0) & (a != b)
                    if not live.any():
                        continue
                    fa = a[live].astype(np.int64)
                    fb = b[live].astype(np.int64)
                    key = (np.minimum(fa, fb) * np.int64(count)
                           + np.maximum(fa, fb))
                    slot_at = np.searchsorted(sorted_keys, key)
                    slot_at = np.clip(slot_at, 0, len(sorted_keys) - 1)
                    good = sorted_keys[slot_at] == key
                    if not good.any():
                        continue
                    target = order[slot_at[good]]
                    step = np.abs(fa_[live] - fb_[live])[good]
                    # bincount, not np.add.at. This scatter-add runs once per
                    # (view, lighting, blur, axis) over every visible pair
                    # boundary -- on a 600k-triangle model that is hundreds of
                    # calls over hundreds of thousands of indices, and add.at
                    # is unbuffered and roughly an order of magnitude slower.
                    # Same arithmetic; the difference is whether this pass
                    # costs seconds or minutes on every single run.
                    totals[slot] += np.bincount(target, weights=step,
                                                minlength=len(pairs))
                    if slot == 0 and lighting == lightings[0]:
                        seen += np.bincount(target, minlength=len(pairs))
        if log:
            log("    evidence view %d/%d: %d pairs seen so far"
                % (number + 1, len(directions), int((seen > 0).sum())))
    return {"seen": seen, "evidence": totals}


def face_mask(tree, regions):
    """A boolean over faces from a set of base regions."""
    base = np.asarray(tree["base"], dtype=np.int64)
    wanted = np.zeros(int(tree["regions"]), dtype=bool)
    wanted[np.asarray(list(regions), dtype=np.int64)] = True
    return wanted[base]


def best_pose(poses, tree, regions, base=None):
    """The pose that shows these regions best, and how many pixels it shows.

    A candidate is judged from the look that resolves it, not from an arbitrary
    front view. A claim about a barnacle on the far side, rendered from the
    near side, shows nothing and gets refused for being invisible rather than
    for being wrong -- which is a false refusal, and the confirm gates were
    full of them.
    """
    if base is None:
        base = region_of_face(tree)
    mask = face_mask(tree, regions)
    best, count = None, 0
    for pose in poses:
        hit = pose.hit_id
        seen = hit[hit >= 0]
        if not len(seen):
            continue
        here = int(mask[seen].sum())
        if here > count:
            best, count = pose, here
    return best, count


def highlight_image(pose, shaded, mask, tint=(0.93, 0.26, 0.16), strength=0.78):
    """Shading in grey, the candidate in colour: what a confirm gate looks at.

    The candidate keeps its own shading rather than becoming a flat silhouette,
    because a flat blob hides whether the claim followed the relief or cut
    across it -- and that is the only question the gate is being asked.
    """
    visible = pose.visible
    height, width = visible.shape
    image = np.full((height, width, 3), 0.97)
    grey = np.clip(shaded, 0.0, 1.0)
    image[visible] = grey[visible, None]
    hit = pose.hit_id
    inside = np.zeros(visible.shape, dtype=bool)
    inside[visible] = mask[hit[visible]]
    if inside.any():
        shade = grey[inside][:, None]
        image[inside] = np.clip(np.asarray(tint) * (0.45 + 0.85 * shade)
                                * strength + shade * (1.0 - strength), 0.0, 1.0)
    return image


def sheet(images, labels, path, columns=3, gap=8, background=0.93):
    """Several looks as one image, each numbered. One ask instead of N asks.

    Numbering is drawn into the tile rather than described in the prompt: an
    agent asked to count tiles left-to-right miscounts a ragged last row, and
    every answer after that is off by one silently.
    """
    from PIL import Image, ImageDraw
    tiles = [(np.clip(im, 0.0, 1.0) * 255).astype(np.uint8) if im.ndim == 3
             else (np.stack([np.clip(im, 0.0, 1.0)] * 3, axis=-1) * 255
                   ).astype(np.uint8) for im in images]
    if not tiles:
        raise ValueError("no tiles to sheet")
    size = tiles[0].shape[0]
    columns = max(1, min(columns, len(tiles)))
    rows = (len(tiles) + columns - 1) // columns
    canvas = Image.new("RGB", (columns * size + (columns + 1) * gap,
                               rows * size + (rows + 1) * gap),
                       tuple([int(background * 255)] * 3))
    draw = ImageDraw.Draw(canvas)
    for index, tile in enumerate(tiles):
        x = gap + (index % columns) * (size + gap)
        y = gap + (index // columns) * (size + gap)
        canvas.paste(Image.fromarray(tile), (x, y))
        label = str(labels[index]) if index < len(labels) else str(index + 1)
        box = draw.textbbox((0, 0), label)
        pad = 4
        draw.rectangle([x + 4, y + 4, x + 4 + (box[2] - box[0]) + 2 * pad,
                        y + 4 + (box[3] - box[1]) + 2 * pad], fill=(20, 20, 20))
        draw.text((x + 4 + pad, y + 4 + pad), label, fill=(255, 255, 255))
    canvas.save(path)
    return path


def digest(*parts):
    """A stable cache key for a look, so a re-run costs nothing."""
    key = hashlib.sha256()
    for part in parts:
        key.update(str(part).encode("utf-8"))
    return key.hexdigest()[:16]
