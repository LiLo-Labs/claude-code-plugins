"""Compare two model files and report whether they are the same object.

Written because two files that were supposed to be the same model were not: a
repair step silently altered several thousand triangles, dropped a component, and
re-oriented the result. Nothing warned about it, and a paint plan built against
one file is meaningless against the other, because both are indexed by triangle
number.

The rule this enforces: geometry in equals geometry out, placement included. Any
divergence is a failure, not a note.

    python3 verify.py --a original.stl --b painted.3mf
    python3 verify.py --a before.3mf --b after.3mf --paint-may-differ

Exit status is 0 when the two files carry the same object, 1 when they do not.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib.threemf import ThreeMF, geometry_matches  # noqa: E402


def _load_mesh(path):
    """Load any supported model as (vertices, faces), never mutating it.

    Vertices are welded on an in-memory copy only. Welding is safe here because
    it renumbers vertex indices without touching face count or face order, so
    face i still refers to the same triangle in space -- which is what component
    analysis needs and what STL, storing every triangle independently, denies us.
    The welded copy is never written anywhere.
    """
    import numpy as np
    import trimesh

    if path.lower().endswith(".3mf"):
        model = ThreeMF(path)
        vertices, faces, offset = [], [], 0
        for obj in model.mesh_objects():
            vertices.extend(obj.vertices)
            faces.extend((a + offset, b + offset, c + offset)
                         for a, b, c in obj.triangles)
            offset += len(obj.vertices)
        return np.asarray(vertices, dtype=float), np.asarray(faces, dtype=np.int64)

    mesh = trimesh.load(path, process=False, force="mesh")
    return np.asarray(mesh.vertices, dtype=float), np.asarray(mesh.faces, dtype=np.int64)


def _components(vertices, faces):
    import numpy as np
    import trimesh
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    welded = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    welded.merge_vertices()
    adjacency = welded.face_adjacency
    count = len(welded.faces)
    if not len(adjacency):
        return np.zeros(count, dtype=np.int64), 1
    graph = coo_matrix(
        (np.ones(len(adjacency)), (adjacency[:, 0], adjacency[:, 1])),
        shape=(count, count))
    total, labels = connected_components(graph, directed=False)
    return labels, total


def describe(path):
    import numpy as np

    vertices, faces = _load_mesh(path)
    labels, total = _components(vertices, faces)
    sizes = np.sort(np.bincount(labels))[::-1]
    lo, hi = vertices.min(axis=0), vertices.max(axis=0)
    return {
        "path": path,
        "vertices": len(vertices),
        "faces": len(faces),
        "components": int(total),
        "component_sizes": sizes.tolist(),
        "extents": (hi - lo).tolist(),
        "origin": lo.tolist(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--a", required=True, help="reference model")
    parser.add_argument("--b", required=True, help="model to compare against it")
    parser.add_argument("--paint-may-differ", action="store_true",
                        help="both inputs are 3MF and only paint is allowed to differ")
    args = parser.parse_args()

    for path in (args.a, args.b):
        if not os.path.exists(path):
            parser.error("no such file: %s" % path)

    if args.paint_may_differ:
        if not (args.a.lower().endswith(".3mf") and args.b.lower().endswith(".3mf")):
            parser.error("--paint-may-differ requires two 3MF files")
        same, detail = geometry_matches(args.a, args.b)
        print("%s: %s" % ("IDENTICAL" if same else "DIFFERENT", detail))
        return 0 if same else 1

    left, right = describe(args.a), describe(args.b)
    differences = []
    for key, label in (("faces", "triangle count"),
                       ("vertices", "vertex count"),
                       ("components", "separate bodies")):
        if left[key] != right[key]:
            differences.append("%s: %s vs %s" % (label, left[key], right[key]))

    if left["component_sizes"] != right["component_sizes"]:
        pairs = list(zip(left["component_sizes"], right["component_sizes"]))
        changed = [i for i, (x, y) in enumerate(pairs) if x != y]
        differences.append("component sizes differ in %d of %d bodies"
                           % (len(changed), min(len(left["component_sizes"]),
                                                len(right["component_sizes"]))))

    extents_left = [round(v, 2) for v in left["extents"]]
    extents_right = [round(v, 2) for v in right["extents"]]
    if extents_left != extents_right:
        differences.append("bounding box: %s vs %s (rotated or rescaled)"
                           % (extents_left, extents_right))

    for entry in (left, right):
        print("%s\n  %d triangles, %d vertices, %d separate bodies, bbox %s mm"
              % (entry["path"], entry["faces"], entry["vertices"], entry["components"],
                 [round(v, 1) for v in entry["extents"]]))

    if not differences:
        print("\nIDENTICAL: same triangles, same bodies, same placement.")
        return 0

    print("\nDIFFERENT -- these files are not the same object:")
    for item in differences:
        print("  - %s" % item)
    print("\nA paint plan built against one of these is not valid for the other,\n"
          "because paint is stored per triangle index.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
