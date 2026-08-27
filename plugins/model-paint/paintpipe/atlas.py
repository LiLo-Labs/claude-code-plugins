"""Part atlas: prove the field isolates features, and address them by hierarchy.

Two different questions get confused when the only output is a finished paint scheme:

    can it FIND the parts?          -- a question about the label field
    does it look good in 4 inks?    -- a question about the limiter and the printer

A realistic scheme answers neither cleanly, because a good colour choice can hide a bad
boundary and a four-filament collapse can bury a good one. So this module renders the
field on its own terms: every part in a maximally distinct colour, no naturalism, no
palette. If a feature has been isolated, it shows as a clean shape in its own hue; if it
has smeared across the body, that shows too and no colour choice can disguise it.

THE PARTS ARE A TREE. The identity agent already returns `parent` on every part (§4.2,
§10) -- "eye sockets" under "head", "clawed feet" under "front legs" -- and that makes
the field addressable at any level: colour one sub-part, or colour a parent and every
child beneath it as one mass. Nothing needs re-segmenting to switch between them, because
both are queries against the same continuous field (I3).
"""

import numpy as np


# Twelve hues that stay distinguishable from each other and in both themes. This is a
# categorical palette for INSPECTION, not a paint scheme; nothing here is printable and
# nothing here is meant to look like the object.
DISTINCT = [
    (0.90, 0.10, 0.12), (0.13, 0.44, 0.90), (0.15, 0.72, 0.28), (0.98, 0.62, 0.05),
    (0.62, 0.22, 0.86), (0.05, 0.76, 0.78), (0.94, 0.36, 0.66), (0.55, 0.48, 0.10),
    (0.30, 0.30, 0.85), (0.85, 0.45, 0.20), (0.20, 0.60, 0.50), (0.75, 0.15, 0.45),
    (0.40, 0.75, 0.15), (0.10, 0.35, 0.55), (0.90, 0.75, 0.15), (0.55, 0.10, 0.25),
]
NEUTRAL = (0.82, 0.81, 0.79)


def hierarchy(vocabulary):
    """`{label: parent}` and the roots, from the identity agent's own part tree."""
    parent = {}
    for part in vocabulary or []:
        name = part.get("label")
        if not name:
            continue
        above = (part.get("parent") or "").strip()
        parent[name] = above if above and above != name else None
    # A parent that was never itself declared is treated as a root of its own.
    for name, above in list(parent.items()):
        if above and above not in parent:
            parent[above] = None
    return parent


def root_of(parent, label, guard=16):
    """Walk up to the top of the tree, defensively bounded against a cycle."""
    seen = 0
    while parent.get(label) and seen < guard:
        label = parent[label]
        seen += 1
    return label


def descendants(parent, label):
    """A label and everything beneath it."""
    out = {label}
    changed = True
    while changed:
        changed = False
        for child, above in parent.items():
            if above in out and child not in out:
                out.add(child)
                changed = True
    return out


def committed_labels(field, posterior, labels, tip_radius_mm, policy):
    """One label per vertex, committed at the nozzle's scale (§11), plus what is claimed.

    Uses the same consolidation the limiter uses, so the atlas shows the boundaries that
    would actually be printed rather than a prettier version of them.
    """
    from . import limiter
    claimed = posterior.max(axis=0) > 0
    owner = np.argmax(posterior, axis=0)
    settled = limiter.consolidate(field, owner, claimed, tip_radius_mm, policy)
    return settled, claimed


def colour_by_part(settled, claimed, labels):
    """Every part its own hue. The direct test of isolation."""
    table = np.array([DISTINCT[i % len(DISTINCT)] for i in range(len(labels))])
    out = np.tile(np.asarray(NEUTRAL), (len(settled), 1))
    out[claimed] = table[settled[claimed]]
    return out, {label: DISTINCT[i % len(DISTINCT)] for i, label in enumerate(labels)}


def colour_by_root(settled, claimed, labels, parent):
    """Each top-level part and everything under it in ONE colour.

    The same field, asked a coarser question. No re-segmentation happens between this and
    `colour_by_part` -- that is what it means for scale to be a query parameter.
    """
    roots = []
    for label in labels:
        top = root_of(parent, label)
        if top not in roots:
            roots.append(top)
    index = np.array([roots.index(root_of(parent, label)) for label in labels])
    table = np.array([DISTINCT[i % len(DISTINCT)] for i in range(len(roots))])
    out = np.tile(np.asarray(NEUTRAL), (len(settled), 1))
    out[claimed] = table[index[settled[claimed]]]
    return out, {root: DISTINCT[i % len(DISTINCT)] for i, root in enumerate(roots)}


def highlight(settled, claimed, labels, wanted, colour=(0.95, 0.20, 0.10)):
    """One subtree in colour, everything else neutral. Addressing a single part."""
    keep = {labels.index(name) for name in wanted if name in labels}
    out = np.tile(np.asarray(NEUTRAL), (len(settled), 1))
    mask = claimed & np.isin(settled, list(keep) or [-1])
    out[mask] = np.asarray(colour)
    return out, int(mask.sum())


def isolation_report(field, settled, claimed, labels):
    """How cleanly each part is isolated: its area, and how scattered it is.

    `pieces` counts connected components of the part on the surface. A feature that has
    been found cleanly is one or a few pieces -- twelve barnacle colonies, two eye
    sockets. A part smeared across the body comes back as hundreds, and that number says
    so without anyone having to look at a render and decide.
    """
    import scipy.sparse as sparse
    mesh = field.substrate
    area = field.vertex_area
    edges = mesh.edges_unique
    rows = []
    total = max(field.total_area_mm2, 1e-9)
    for index, label in enumerate(labels):
        mine = claimed & (settled == index)
        count = int(mine.sum())
        if count == 0:
            rows.append({"part": label, "area_mm2": 0.0, "area_pct": 0.0,
                         "pieces": 0, "largest_piece_pct": 0.0})
            continue
        inside = mine[edges[:, 0]] & mine[edges[:, 1]]
        keep = edges[inside]
        graph = sparse.coo_matrix(
            (np.ones(len(keep)), (keep[:, 0], keep[:, 1])),
            shape=(len(mesh.vertices), len(mesh.vertices)))
        pieces, tag = sparse.csgraph.connected_components(graph, directed=False)
        sizes = np.bincount(tag[mine], weights=area[mine])
        rows.append({"part": label,
                     "area_mm2": round(float(area[mine].sum()), 2),
                     "area_pct": round(100 * float(area[mine].sum()) / total, 3),
                     "pieces": int((np.bincount(tag[mine]) > 0).sum()),
                     "largest_piece_pct": round(
                         100 * float(sizes.max()) / max(float(sizes.sum()), 1e-9), 1)})
    return rows
