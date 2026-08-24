"""Classify every triangle into candidate parts, with the thresholds exposed.

This is the deterministic half of feature finding. It computes four measurements
and cuts them at percentiles, then hands the result to something that can look at
a render and say "you missed the barnacles on the left rib" -- because that
judgement is not available from any threshold.

Measurements, and what each one is for:

  thickness   distance through the solid. Thin means a protrusion: horn, spike,
              tube worm, encrusting growth. Thick means body: skull, shell, rock.
  roughness   mean dihedral angle diffused over a few rings. Bumpy regions score
              high, which is what separates barnacle crust from a smooth shell.
  occlusion   how much sky the triangle sees. Low means exposed, high means down
              inside a crack or a barnacle's opening. This is what makes
              "inside versus outside" paintable.
  height      normalised Z. Cheap, and on a based model it separates the ground
              from the thing standing on it.

Every threshold is a percentile and every one is a flag, because the right values
differ per model and the caller is expected to iterate. Re-running is cheap: about
twenty seconds on 600k triangles including occlusion.

Nothing here is written back to the model. The welded mesh used for adjacency is
an in-memory copy; face order and count are untouched, so index i still means
triangle i in the original file.
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import signals                                     # noqa: E402


def load_mesh(path):
    import trimesh

    if path.lower().endswith(".3mf"):
        from paintlib.threemf import ThreeMF
        objects = ThreeMF(path).mesh_objects()
        if not objects:
            raise SystemExit("detect: no mesh objects in %s" % path)
        obj = max(objects, key=lambda o: o.triangle_count)
        mesh = trimesh.Trimesh(vertices=np.asarray(obj.vertices),
                               faces=np.asarray(obj.triangles), process=False)
    else:
        mesh = trimesh.load(path, process=False, force="mesh")
    welded = mesh.copy()
    welded.merge_vertices()
    if len(welded.faces) != len(mesh.faces):
        raise SystemExit("detect: welding changed the face count; refusing to continue")
    return welded


def occlusion(mesh, samples=12, seed=7):
    """Fraction of a cosine-weighted hemisphere that hits the model again."""
    try:
        mesh.ray
    except Exception:
        return np.zeros(len(mesh.faces))

    normals = mesh.face_normals
    scale = float(np.linalg.norm(np.ptp(mesh.vertices, axis=0))) or 1.0
    origins = mesh.triangles_center + normals * (scale * 1e-5)

    helper = np.tile(np.array([0.0, 0.0, 1.0]), (len(normals), 1))
    helper[np.abs(normals[:, 2]) > 0.9] = np.array([1.0, 0.0, 0.0])
    tangent = np.cross(normals, helper)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-12)
    bitangent = np.cross(normals, tangent)

    # Seeded so two runs on the same model give the same answer; a plan that
    # changed because of ray jitter would be impossible to iterate on.
    rng = np.random.default_rng(seed)
    hits = np.zeros(len(normals))
    for _ in range(max(1, int(samples))):
        first, second = rng.random(len(normals)), rng.random(len(normals))
        radius, theta = np.sqrt(first), 2.0 * np.pi * second
        direction = (tangent * (radius * np.cos(theta))[:, None]
                     + bitangent * (radius * np.sin(theta))[:, None]
                     + normals * np.sqrt(np.maximum(0.0, 1.0 - first))[:, None])
        direction /= np.maximum(np.linalg.norm(direction, axis=1, keepdims=True), 1e-12)
        hits += mesh.ray.intersects_first(ray_origins=origins,
                                          ray_directions=direction) >= 0
    return hits / float(max(1, int(samples)))


def classify(mesh, options):
    pairs = mesh.face_adjacency
    angles = mesh.face_adjacency_angles
    count = len(mesh.faces)

    thickness = signals.local_thickness(
        mesh.vertices, mesh.faces, mesh.face_normals, mesh.triangles_center)
    rough = signals.surface_roughness(pairs, angles, count, rounds=options.rough_rounds)
    occl = occlusion(mesh, options.occlusion_samples)

    centres = mesh.triangles_center
    height = centres[:, 2]
    height = (height - height.min()) / max(np.ptp(height), 1e-9)

    labels = np.zeros(count, dtype=np.int32)          # 0 = main body
    if thickness is not None and np.isfinite(thickness).any():
        finite = np.isfinite(thickness)
        cutoff = float(np.nanpercentile(thickness[finite], options.thin_percentile))
        thin = np.zeros(count, dtype=bool)
        thin[finite] = thickness[finite] <= cutoff
    else:
        thin = np.zeros(count, dtype=bool)

    labels[thin & (height < options.base_height)] = 1      # ground / base
    labels[thin & (height >= options.base_height)] = 3     # protrusions up high
    crust = (~thin) & (rough >= np.percentile(rough, options.rough_percentile))
    labels[crust] = 2                                      # encrusting texture

    return labels, {"thickness": thickness, "roughness": rough,
                    "occlusion": occl, "height": height}


def cluster_counts(labels, pairs, minimum):
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    out = {}
    for value in np.unique(labels):
        mask = labels == value
        both = mask[pairs[:, 0]] & mask[pairs[:, 1]]
        if not both.any():
            out[int(value)] = 0
            continue
        graph = coo_matrix((np.ones(int(both.sum())),
                            (pairs[both, 0], pairs[both, 1])),
                           shape=(len(labels), len(labels)))
        _, sub = connected_components(graph, directed=False)
        sizes = np.bincount(sub, weights=mask.astype(float)).astype(int)
        out[int(value)] = int((sizes >= minimum).sum())
    return out


DEFAULT_NAMES = {0: "main body", 1: "base / ground", 2: "encrusting texture",
                 3: "protrusions"}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="STL or 3MF")
    parser.add_argument("--output", required=True, help="directory for features.npz and parts.json")
    parser.add_argument("--thin-percentile", type=float, default=26.0)
    parser.add_argument("--rough-percentile", type=float, default=93.0)
    parser.add_argument("--rough-rounds", type=int, default=2)
    parser.add_argument("--base-height", type=float, default=0.42,
                        help="normalised Z below which a thin region is ground")
    parser.add_argument("--occlusion-samples", type=int, default=12)
    parser.add_argument("--min-cluster", type=int, default=150)
    parser.add_argument("--names", default=None,
                        help="JSON mapping label -> name, e.g. '{\"2\":\"barnacles\"}'")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        parser.error("no such file: %s" % args.input)
    if os.path.realpath(args.input) == os.path.realpath(args.output):
        parser.error("--output would overwrite the input model")

    mesh = load_mesh(args.input)
    labels, found = classify(mesh, args)
    areas = mesh.area_faces
    total = float(areas.sum()) or 1.0
    counts = cluster_counts(labels, mesh.face_adjacency, args.min_cluster)

    names = dict(DEFAULT_NAMES)
    if args.names:
        names.update({int(k): v for k, v in json.loads(args.names).items()})

    os.makedirs(args.output, exist_ok=True)
    np.savez_compressed(
        os.path.join(args.output, "features.npz"),
        vertices=mesh.vertices.astype(np.float32),
        faces=mesh.faces.astype(np.int32),
        normals=mesh.face_normals.astype(np.float32),
        labels=labels.astype(np.int32),
        occlusion=found["occlusion"].astype(np.float32),
        roughness=found["roughness"].astype(np.float32),
        thickness=np.nan_to_num(found["thickness"], nan=-1.0).astype(np.float32)
        if found["thickness"] is not None else np.zeros(len(labels), np.float32))

    pairs = mesh.face_adjacency
    left, right = labels[pairs[:, 0]], labels[pairs[:, 1]]
    crossing = left != right
    shares = {}
    if crossing.any():
        keys = np.stack([np.minimum(left[crossing], right[crossing]),
                         np.maximum(left[crossing], right[crossing])], axis=1)
        unique, tally = np.unique(keys, axis=0, return_counts=True)
        grand = float(tally.sum())
        for (a, b), n in zip(unique, tally):
            shares[(int(a), int(b))] = float(n) / grand

    parts = []
    for value in sorted(np.unique(labels)):
        value = int(value)
        neighbours = {str(other): round(share, 4)
                      for (a, b), share in shares.items()
                      for other in ([b] if a == value else [a] if b == value else [])}
        parts.append({
            "id": str(value),
            "name": names.get(value, "part %d" % value),
            "area": round(float(areas[labels == value].sum() / total), 4),
            "faces": int((labels == value).sum()),
            "pieces": counts.get(value, 0),
            "median_occlusion": round(float(np.median(found["occlusion"][labels == value])), 3),
            "neighbours": neighbours,
        })

    document = {"source": os.path.abspath(args.input),
                "settings": {"thin_percentile": args.thin_percentile,
                             "rough_percentile": args.rough_percentile,
                             "rough_rounds": args.rough_rounds,
                             "base_height": args.base_height,
                             "min_cluster": args.min_cluster},
                "parts": parts}
    with open(os.path.join(args.output, "parts.json"), "w") as handle:
        json.dump(document, handle, indent=2)
        handle.write("\n")

    print("%d triangles, %d parts" % (len(labels), len(parts)))
    for part in parts:
        print("  %-2s %-22s %7d faces  %5.1f%% area  %4d piece(s)  occlusion %.2f"
              % (part["id"], part["name"], part["faces"], 100 * part["area"],
                 part["pieces"], part["median_occlusion"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
