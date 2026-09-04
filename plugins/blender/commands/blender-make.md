---
name: blender-make
description: Model or generate an asset in Blender, then render, verify and report it
---

Build this in Blender: **$ARGUMENTS**

Follow the `blender` skill's loop and do not shortcut it.

1. **Decide the route first and say it in one sentence.** Procedural via
   `execute_python` for hard-surface, architectural, modular or parametric
   subjects. `generate_mesh` only for organic form. Mixed subjects get split —
   generate the creature, model the sword.
2. **If this will cost money, say the figure before spending it.** Check
   `list_backends` if you do not already know.
3. **Build it.** One coherent step per `execute_python` call, named objects,
   +Z up, real-world scale.
4. **`render_views`, then read the returned PNG paths.** Judge the silhouette
   from every angle, the scale, and whether it is what was actually asked for.
5. **`verify_geometry`.** `game` preset unless the user's target says otherwise.
   Add `min_quad_ratio: 0.8` if clean topology was promised. Fix every blocking
   finding and re-verify — never relax the budget to pass.
6. **Report** the render and the verdict together. If something is still wrong,
   say what, rather than presenting it as done.
