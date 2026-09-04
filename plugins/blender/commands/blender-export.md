---
name: blender-export
description: Verify then export the scene or selected objects to a target format
---

Export: **$ARGUMENTS**

Run `verify_geometry` first — the export guard will block you otherwise, and it
is right to. Choose the format for the destination:

| Target | Format |
|---|---|
| web, three.js, modern pipelines | `.glb` |
| Unity, Unreal | `.fbx` |
| static prop, no rig | `.obj` |
| 3D printing | `.stl`, after a `print` preset verify |

Apply transforms before exporting. Afterwards, report the path, the file size
and the polycount that actually left, not the one in the cage.
