---
name: blender-status
description: Check the Blender connection, the configured mesh backend and what it costs
---

Call the `blender` MCP tool `blender_status`, then `list_backends`.

Report three things plainly:

1. **Is Blender reachable.** If not, give the three setup steps from the error
   verbatim and stop — do not try other tools.
2. **Which backend would be used** for a generation right now, and what it costs
   per attempt. If a local backend is configured, say generation is free.
3. **What is missing**, if the user has no backend at all — and remind them that
   procedural modelling through `execute_python` needs no backend and is the
   better route for hard-surface and modular work anyway.
