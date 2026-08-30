"""Units and kinds: what the mesh is actually made of.

The naming pass votes on ATOMS -- at most a few hundred merged regions --
and on an encrusted model that is the wrong unit entirely. A shell carries
1469 discrete base regions: every barnacle cone, every limpet rosette,
every weed frond, every rib. Collapsing those into 250 atoms and voting on
the result loses the colonies before anyone is asked about them, which is
why a barnacle field could come back half painted, or a rosette label could
swallow a third of the model.

So name what the geometry actually separates. Base regions are the units.
Units that MEASURE alike are the same kind of thing -- a barnacle is a
barnacle wherever it sits -- so they cluster on their own signature
(characteristic radius, relief sign, response strength, size), and one look
per kind names every instance of it at once. Uniformity stops being a
post-hoc repair and becomes the representation: two units of one kind
cannot take different colours, because they are not separately nameable.
"""

import numpy as np


def unit_signature(mesh, tree):
    """Per-unit size and shape, area-weighted from the scale-space index."""
    base = np.asarray(tree["base"], dtype=np.int64)
    features = np.asarray(tree["features"], dtype=float)
    areas = np.asarray(mesh.area_faces, dtype=float)
    count = int(base.max()) + 1
    area = np.bincount(base, weights=areas, minlength=count)
    signature = np.zeros((count, features.shape[1]))
    for column in range(features.shape[1]):
        signature[:, column] = (
            np.bincount(base, weights=features[:, column] * areas,
                        minlength=count) / np.maximum(area, 1e-9))
    return base, area, signature


def cluster_units(mesh, tree, kinds=8, seed=7):
    """Group units into kinds of thing. Returns (base, kind_of_unit, area).

    Size and characteristic radius enter as logs because a barnacle differs
    from a rib by ratio, not by millimetres.
    """
    from scipy.cluster.vq import kmeans2
    base, area, signature = unit_signature(mesh, tree)
    table = np.column_stack([
        np.log(np.maximum(area, 1e-3)),
        np.log(np.maximum(signature[:, 0], 1e-3)),
        signature[:, 1:]])
    table = (table - table.mean(axis=0)) / np.maximum(table.std(axis=0), 1e-9)
    kinds = int(min(kinds, max(2, len(table) // 8)))
    _centroids, kind = kmeans2(table, kinds, seed=seed, minit="++", iter=60)
    return base, kind.astype(np.int64), area, signature


def kind_sheet(mesh, frame, base, kind, up, out_dir, pixels=430, columns=3):
    """One tile per kind: its units red on the whole piece, numbered.

    The agent sees WHERE a kind lives and how it repeats, which is what
    identifies it -- a barnacle field reads as a barnacle field because it
    is many small cones scattered over a host, not because of one cone.
    """
    import os
    from PIL import Image, ImageDraw
    from . import preview

    occlusion = preview.ambient_occlusion(mesh, samples=16)
    direction = preview.orbit(1, 16.0, start_deg=200.0, up=up)[0]
    tiles = []
    for number in range(int(kind.max()) + 1):
        rgb = np.tile(np.array([[0.80, 0.79, 0.77]]), (len(base), 1))
        rgb[np.isin(base, np.flatnonzero(kind == number))] = [0.88, 0.12, 0.10]
        image = preview.render_asset(mesh, rgb, direction, size=pixels,
                                     occlusion=occlusion, up=up, zoom=1.15)
        picture = Image.fromarray(image)
        draw = ImageDraw.Draw(picture)
        draw.rectangle([4, 4, 30, 24], fill=(255, 255, 255))
        draw.text((10, 8), str(number), fill=(0, 0, 0))
        tiles.append(picture)
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * pixels, rows * pixels),
                      (255, 255, 255))
    for index, picture in enumerate(tiles):
        sheet.paste(picture, ((index % columns) * pixels,
                              (index // columns) * pixels))
    path = os.path.join(out_dir, "kind-sheet.png")
    sheet.save(path)
    return path


KIND_PROMPT = """Each numbered panel shows the SAME piece with one family of \
surface units highlighted in red. The units in a panel all measure alike, so \
they are the same kind of thing wherever they appear.

The piece: %s

Name what each numbered family IS, in the piece's own terms -- what a maker \
would call it. Families that are the same substance should get the same name, \
and a family that is just the piece's own body or ground should say so \
plainly. If a panel highlights nothing coherent, name it "unclear".

Reply with ONLY a JSON object, no prose, no code fences:
{"kinds": [{"n": <number>, "name": str, "material": str, "why": str}]}"""


def name_kinds(backend, sheet_path, intent, count, key):
    """One look names every unit of every kind."""
    answer = backend._run([sheet_path], KIND_PROMPT % (intent or "a model"),
                          key)
    names = {}
    materials = {}
    for entry in (answer or {}).get("kinds", []) or []:
        try:
            number = int(entry.get("n", -1))
        except (TypeError, ValueError):
            continue
        name = str(entry.get("name", "")).strip()
        if 0 <= number < count and name:
            names[number] = name
            materials[number] = str(entry.get("material", "")).strip()
    return names, materials
