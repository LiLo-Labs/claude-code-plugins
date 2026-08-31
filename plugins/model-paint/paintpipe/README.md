# paintpipe

Twelve modules. Everything here is either the agent looking at the model, the
geometry giving it real edges to snap to, or getting the result into a file a
printer can read.

    cli         the one command: load, segment, paint, review, choose, export
    loop        THE METHOD -- see, paint a colour at a time, look, fix, review
    rig         where to stand and how to light it; one coordinate system
    render      depth and normals into a buffer; the only renderer
    preview     camera directions, and the model's own up axis
    segment3d   the substrate: base regions with real, feature-aligned edges
    fastscale   the scale-space index those regions are built from
    frame       units, scale, orientation; repairs that never move a vertex
    field       welds the file into a mesh with actual face adjacency
    policy      the handful of numbers that are facts about printing
    vision      the agent backend, cached on the image's own digest
    export      the painted 3MF, with the geometry proved unchanged
    colour      hex to Lab and back
    inputs      what a filament is

## What is NOT here, and why

No solver decides a boundary, fills a gap between marks, or picks how much
surface a mark means. Four such rules were built and measured against the same
real answers -- climbing the merge tree, shortest path over the border graph,
matching the surface signature, and letting a part reach as far as its own
marks are apart. All four drew distance bands or confetti, because between the
marks they were guessing.

The measurement that retired the whole family: on a shell refined to 11876
base regions, the ancestor chain above a seed on the ribs runs 0.001%, 0.106%,
0.116%, 0.125%, 0.129%, 0.130%, 0.132%, then **33.989%** of the surface. The
ribs are a large, obvious, nameable feature and there is no node that is them.
No way of choosing among nodes can produce one, however the choice is made.

So the geometry's job is to supply edges that are real, and every decision
about which of them matter belongs to the thing that can look at the model.
See `docs/failure-circumstances.md` for the rest of what was tried and what it
cost.
