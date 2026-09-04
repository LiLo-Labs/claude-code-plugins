---
name: blender-check
description: Measure the geometry in the scene and report what would fail downstream
---

Check the geometry: **$ARGUMENTS**

Run `verify_geometry`. Pick the preset from the user's stated target — `game`
for an engine, `print` for a printer, `render` for stills — and default to
`game` when they have not said. Add `min_quad_ratio: 0.8` whenever clean
topology has been claimed.

Then `render_views` and read the images, because several defects are obvious in
a picture and ambiguous in a number: a hole reads instantly, a boundary-edge
count does not.

Report the verdict, then each finding with the fix that actually clears it. Be
direct about what is not usable. If the mesh is fine, say so without hedging.
