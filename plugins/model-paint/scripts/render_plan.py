"""Render a colour plan to PNG so it can be looked at -- by a person or by an agent.

Colour choice is not a scoring problem. A plan can be maximally contrasting and
still look wrong, because "rocky base" wants to look like rock and no metric in
the plugin knows that. So the plan gets rendered and judged by something that can
see it, and the judgement drives the next iteration.

That makes this script the inner loop of the critique cycle rather than a
presentation step, which is why it is fast, deterministic, and takes its whole
input as one small JSON file.

Plan JSON accepted here:

    {"default": "#RRGGBB",                            colour for unassigned faces
     "parts": {"<part name or label>": {"outside": "#RRGGBB",
                                        "inside": "#RRGGBB",   optional
                                        "cut": 0.6}},          optional, occlusion 0..1
     "views": ["front", "iso"],                       optional
     "crops": [{"name": "detail", "centre": [x, y, z], "radius": 12}]}

Parts are addressed by NAME when a parts.json from select_region.py is supplied,
and by integer label when reading a features.npz from detect_features.py. Names are
the norm: a reusable pipeline should not know what any particular model contains,
only that a part called whatever the agent called it covers these triangles.

`inside` paints the recessed part of a region -- inside a barnacle's opening, the
floor of a crack, the shadow between coral tubes -- using the occlusion measured
in features.npz. Recesses read as shadow, so inside is normally the darker
filament. Whether a part is worth splitting at all is a judgement about what the
part is, which is the caller's business, not this script's.
"""

import argparse
import json
import os
import sys

import numpy as np


VIEWS = {
    "front": (14, -88), "back": (14, 92), "left": (12, -2), "right": (12, 178),
    "top": (78, -90), "bottom": (-70, -90), "iso": (24, -50), "iso2": (20, 130),
}


def hex_to_rgb(text):
    text = str(text).strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def face_colours(features, plan, named_parts=None):
    """Per-face RGB from the plan, splitting inside from outside where asked.

    ``named_parts`` maps a part name to its face indices, as written by
    select_region.py. When present the plan is keyed by those names; otherwise it
    falls back to the integer labels in a features.npz.
    """
    occlusion = features["occlusion"]
    count = len(occlusion)
    labels = features["labels"] if "labels" in features.files else None
    colours = np.zeros((count, 3))
    covered = np.zeros(count, dtype=bool)

    for key, spec in plan["parts"].items():
        if named_parts is not None and key in named_parts:
            mask = np.zeros(count, dtype=bool)
            mask[named_parts[key]] = True
        elif labels is not None:
            try:
                mask = labels == int(key)
            except (TypeError, ValueError):
                sys.stderr.write("render: plan names unknown part %r, skipping\n" % key)
                continue
        else:
            sys.stderr.write("render: plan names unknown part %r, skipping\n" % key)
            continue
        if not mask.any():
            continue
        outside = hex_to_rgb(spec["outside"])
        inside_hex = spec.get("inside")
        if inside_hex and spec.get("cut") is not None:
            deep = mask & (occlusion > float(spec["cut"]))
            colours[mask & ~deep] = outside
            colours[deep] = hex_to_rgb(inside_hex)
        else:
            colours[mask] = outside
        covered |= mask

    if not covered.all():
        colours[~covered] = hex_to_rgb(plan.get("default", "#BFBFC2"))
    return colours


def render(mesh_vertices, mesh_faces, normals, colours, views, crops, out_dir,
           size=900, title=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    light = np.array([0.35, -0.75, 0.55])
    light /= np.linalg.norm(light)
    shade = np.clip(normals @ light, 0.0, 1.0) * 0.58 + 0.42
    shaded = np.clip(colours * shade[:, None], 0.0, 1.0)

    panels = [(name, VIEWS[name], None) for name in views if name in VIEWS]
    for crop in crops or []:
        panels.append((crop.get("name", "detail"), VIEWS.get(crop.get("view", "iso")),
                       (np.asarray(crop["centre"], dtype=float), float(crop["radius"]))))
    if not panels:
        raise ValueError("no valid views requested")

    os.makedirs(out_dir, exist_ok=True)
    columns = min(len(panels), 3)
    rows = (len(panels) + columns - 1) // columns
    figure = plt.figure(figsize=(6.2 * columns, 6.2 * rows), dpi=size / 6.2)
    centre_all = mesh_vertices.mean(axis=0)
    radius_all = np.ptp(mesh_vertices, axis=0).max() / 2.0

    for index, (name, angles, crop) in enumerate(panels, start=1):
        axes = figure.add_subplot(rows, columns, index, projection="3d")
        axes.add_collection3d(Poly3DCollection(
            mesh_vertices[mesh_faces], facecolors=shaded, linewidths=0, shade=False))
        if crop is None:
            centre, radius = centre_all, radius_all * 1.02
        else:
            centre, radius = crop
        axes.set_xlim(centre[0] - radius, centre[0] + radius)
        axes.set_ylim(centre[1] - radius, centre[1] + radius)
        axes.set_zlim(centre[2] - radius, centre[2] + radius)
        axes.view_init(elev=angles[0], azim=angles[1])
        axes.set_axis_off()
        axes.set_box_aspect((1, 1, 1))
        axes.set_title(name, fontsize=11)

    if title:
        figure.suptitle(title, y=1.01, fontsize=13)
    figure.tight_layout()
    path = os.path.join(out_dir, "plan.png")
    figure.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(figure)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--features", required=True,
                        help="features.npz from detect_features.py, or session.npz "
                             "from inspect_model.py")
    parser.add_argument("--parts", default=None,
                        help="parts.json from select_region.py; plan keys become "
                             "part names instead of label integers")
    parser.add_argument("--plan", required=True, help="plan JSON, see module docstring")
    parser.add_argument("--output", required=True, help="directory for plan.png")
    parser.add_argument("--size", type=int, default=900, help="pixels per panel")
    parser.add_argument("--title", default=None)
    args = parser.parse_args()

    for path in (args.features, args.plan):
        if not os.path.exists(path):
            parser.error("no such file: %s" % path)

    features = np.load(args.features)
    with open(args.plan) as handle:
        plan = json.load(handle)
    if "parts" not in plan:
        parser.error("plan has no 'parts' object")

    named_parts = None
    if args.parts:
        if not os.path.exists(args.parts):
            parser.error("no such file: %s" % args.parts)
        with open(args.parts) as handle:
            named_parts = {part["name"]: np.asarray(part["face_indices"], dtype=np.int64)
                           for part in json.load(handle).get("parts", [])}
        missing = [key for key in plan["parts"] if key not in named_parts]
        if missing:
            sys.stderr.write("render: plan names %d part(s) not in %s: %s\n"
                             % (len(missing), args.parts, ", ".join(missing[:6])))

    colours = face_colours(features, plan, named_parts)
    path = render(features["vertices"], features["faces"], features["normals"],
                  colours, plan.get("views") or ["front", "iso"],
                  plan.get("crops"), args.output, args.size,
                  args.title or plan.get("title"))
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
