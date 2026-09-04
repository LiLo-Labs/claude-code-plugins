---
name: blender-agent
description: Hand a whole asset to a headless Claude that drives Blender unattended
---

Run this task unattended: **$ARGUMENTS**

```bash
python3 -m blendpipe.agent "$ARGUMENTS"
```

Run it from the plugin directory, or add the plugin root to `PYTHONPATH`.

This is the same loop as `/blender-make`, handed to a separate `claude -p`
process that drives Blender on its own — modelling, unwrapping, texturing,
rendering, reading its own renders, and measuring — until it has a report. Use
it when you want the whole asset produced in one go rather than stepping through
it in conversation.

It runs on the user's subscription, so it costs nothing beyond what they already
pay. The run lands in `~/.blendpipe/runs/<timestamp>-agent/` with the prompt,
the report, and a manifest carrying turn count, wall time and the API-equivalent
figure.

**No guardrails run inside it.** The spend ceiling and the verify-before-export
hook are plugin hooks, and the agent attaches the MCP server directly rather
than loading the plugin, so nothing blocks it. `verify_geometry` still measures
and still reports — it just cannot refuse. That is deliberate: unattended work
should not deadlock on a gate with nobody there to clear it. It also means
`generate_mesh` is uncapped in this mode, so do not hand it a task that will
generate in a loop.

When it returns:

1. **Read the renders it produced** before repeating its claims. It was told to
   look at them, and it usually has, but its report is a claim and the image is
   the evidence.
2. **Show the user the report and the measurements together**, including the
   "what is still wrong" section. Do not summarise that part away — it is the
   most useful thing in the report.
3. If the result needs work, run it again with a task that names the specific
   defect rather than restating the original brief.
