"""Give an agent eyes: render a model from several angles and keep the pick maps.

This is step one of a visual-first pipeline. The agent looks at these images and
says what it sees -- "a cluster of barnacles on the upper right rib", "the spiral
aperture in the centre", "six tube worms along the left of the base". Because
every view ships with a face-index-per-pixel map, those observations can be turned
into triangle selections by select_region.py rather than staying as prose.

The geometric signals are computed once here and cached alongside, so selection
and colouring never recompute them.

    python3 inspect_model.py --input model.stl --output work/
    -> work/views/<name>.png, work/session.npz, work/summary.json
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from paintlib import raster, signals                              # noqa: E402
from detect_features import load_mesh, occlusion                  # noqa: E402

DEFAULT_VIEWS = ["front", "back", "left", "right", "top", "iso", "iso2"]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="STL or 3MF")
    parser.add_argument("--output", required=True, help="session directory")
    parser.add_argument("--views", default=",".join(DEFAULT_VIEWS))
    parser.add_argument("--size", type=int, default=900, help="pixels per view")
    parser.add_argument("--occlusion-samples", type=int, default=12)
    args = parser.parse_args()

    if not os.path.exists(args.input):
        parser.error("no such file: %s" % args.input)

    mesh = load_mesh(args.input)
    faces = len(mesh.faces)
    print("%s: %d triangles" % (os.path.basename(args.input), faces))

    pairs, angles = mesh.face_adjacency, mesh.face_adjacency_angles
    thickness = signals.local_thickness(mesh.vertices, mesh.faces,
                                        mesh.face_normals, mesh.triangles_center)
    rough = signals.surface_roughness(pairs, angles, faces)
    occl = occlusion(mesh, args.occlusion_samples)
    height = mesh.triangles_center[:, 2]
    height = (height - height.min()) / max(np.ptp(height), 1e-9)

    views_dir = os.path.join(args.output, "views")
    os.makedirs(views_dir, exist_ok=True)
    grey = np.tile(np.array([0.82, 0.82, 0.85]), (faces, 1))

    names = [name.strip() for name in args.views.split(",") if name.strip()]
    picks = {}
    for name in names:
        if name not in raster.VIEWS:
            sys.stderr.write("inspect: unknown view %r, skipping\n" % name)
            continue
        elevation, azimuth = raster.VIEWS[name]
        image, pick = raster.render_view(mesh, grey, elevation, azimuth, args.size)
        raster.save_png(os.path.join(views_dir, "%s.png" % name), image)
        picks[name] = pick.astype(np.int32)
        print("  %-6s %d px on model" % (name, int((pick >= 0).sum())))

    np.savez_compressed(
        os.path.join(args.output, "session.npz"),
        vertices=mesh.vertices.astype(np.float32),
        faces=mesh.faces.astype(np.int32),
        normals=mesh.face_normals.astype(np.float32),
        areas=mesh.area_faces.astype(np.float32),
        pairs=pairs.astype(np.int32),
        angles=angles.astype(np.float32),
        thickness=(np.nan_to_num(thickness, nan=-1.0).astype(np.float32)
                   if thickness is not None else np.full(faces, -1.0, np.float32)),
        roughness=rough.astype(np.float32),
        occlusion=occl.astype(np.float32),
        height=height.astype(np.float32),
        **{"pick_%s" % name: pick for name, pick in picks.items()})

    def spread(values):
        finite = values[np.isfinite(values) & (values >= 0)]
        if not finite.size:
            return None
        return {"p10": round(float(np.percentile(finite, 10)), 3),
                "median": round(float(np.median(finite)), 3),
                "p90": round(float(np.percentile(finite, 90)), 3)}

    summary = {
        "source": os.path.abspath(args.input),
        "triangles": faces,
        "extent_mm": [round(float(v), 2) for v in np.ptp(mesh.vertices, axis=0)],
        "views": list(picks),
        "view_size": args.size,
        "signals": {"thickness_mm": spread(np.asarray(
                        thickness if thickness is not None else np.full(faces, -1.0))),
                    "roughness": spread(rough),
                    "occlusion": spread(occl)},
        "hint": ("Look at views/*.png. Name what you see and give a pixel "
                 "coordinate for each feature, then use select_region.py to turn "
                 "that into triangles and check the highlight it renders."),
    }
    with open(os.path.join(args.output, "summary.json"), "w") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")
    print("session written to %s" % os.path.abspath(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
