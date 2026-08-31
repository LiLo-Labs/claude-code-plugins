"""Write the painted 3MF, and prove the geometry never moved.

The verification is not ceremony. Every stage upstream is allowed to weld,
decimate and re-index the mesh however it likes, because none of that reaches
the print: the 3MF is built from the ORIGINAL file and only carries per-face
filament assignments. If the geometry in the written file differs from the
geometry in the file the user handed over, something has gone wrong that no
render would show.
"""

import os

import numpy as np


def write_3mf(input_path, out_dir, field, labels, chosen, filaments,
              log=print):
    """`field` is per-face labels on the substrate; `chosen` maps part -> filament."""
    import sys
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    scripts = os.path.join(here, "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        from paintlib import build as builder, orca, threemf
    except ImportError:
        log("3MF writer unavailable; skipping export")
        return {"written": False}

    from .colour import lab_to_hex

    base = os.path.join(out_dir, "base.3mf")
    painted = os.path.join(out_dir, "painted.3mf")
    builder.from_stl(input_path, base,
                     name=os.path.splitext(os.path.basename(input_path))[0])

    slot = {paint.name: index + 1 for index, paint in enumerate(filaments)}
    default = slot[filaments[-1].name]
    assignments = {}
    for face, part in enumerate(np.asarray(field)):
        if part < 0:
            continue
        want = slot.get(chosen.get(labels[int(part)], ""), default)
        if want != default:
            assignments[int(face)] = want

    archive = threemf.ThreeMF(base)
    archive.paint_object(archive.mesh_objects()[0], assignments)
    orca.set_filaments(
        archive,
        [{"index": index + 1, "name": paint.name, "hex": lab_to_hex(paint.lab)}
         for index, paint in enumerate(filaments)],
        default_filament=default)
    archive.save(painted)

    ok, why = threemf.geometry_matches(base, painted)
    log("3MF %s -- %s" % ("IDENTICAL" if ok else "DIFFERS", why))
    return {"written": True, "path": painted, "geometry_identical": bool(ok),
            "detail": why}
