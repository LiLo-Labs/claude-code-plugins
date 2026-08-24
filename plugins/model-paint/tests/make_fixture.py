"""Generate a synthetic creature mesh so the pipeline can be tested without
depending on any particular real model. Body + two horns + two eyes gives us
separable features to exercise segmentation against."""

import sys

import numpy as np
import trimesh


def build():
    body = trimesh.creation.icosphere(subdivisions=3, radius=20.0)

    horns = []
    for side in (-1.0, 1.0):
        horn = trimesh.creation.cone(radius=4.0, height=14.0, sections=24)
        horn.apply_translation([side * 7.0, 0.0, 17.0])
        horns.append(horn)

    eyes = []
    for side in (-1.0, 1.0):
        eye = trimesh.creation.icosphere(subdivisions=2, radius=3.5)
        eye.apply_translation([side * 8.0, -17.0, 6.0])
        eyes.append(eye)

    # Concatenate rather than boolean-union: keeps every original triangle intact,
    # which is the point of the fixture.
    return trimesh.util.concatenate([body] + horns + eyes)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "creature.stl"
    mesh = build()
    mesh.export(out)
    print("%s: %d vertices, %d triangles" % (out, len(mesh.vertices), len(mesh.faces)))
