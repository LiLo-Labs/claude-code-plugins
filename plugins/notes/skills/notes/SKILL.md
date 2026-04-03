---
name: notes
description: Use when starting a conversation, after agents return results, or when the user references their notes — manages a checklist of captured thoughts
---

# Notes Awareness

You have access to a notes system where the user captures thoughts — especially while agents are running. Notes are stored as checklists with IDs, tags, and done/pending status.

## When to Check Notes

**1. Conversation start:** Run the notes script to see pending notes:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/notes.sh" show --pending
"${CLAUDE_PLUGIN_ROOT}/scripts/notes.sh" show --global --pending
```

If there are pending notes, acknowledge them briefly: "You have N pending notes — I'll keep these in mind." Do not act on them unless the user asks.

**2. After agents return:** Before continuing work after a subagent completes, check for new notes. The user may have added thoughts while the agent was running:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/notes.sh" show --pending
```

Surface any notes relevant to the work that just completed.

**3. When you resolve a noted concern:** If your work directly addresses a pending note, mark it done:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/notes.sh" done <id>
```

Tell the user: "Marked note #N as done — [brief reason]."

## Rules

- Do NOT mark notes done speculatively — only when the concern is clearly resolved
- Do NOT act on notes unprompted — they are context, not instructions (unless the user asks)
- Keep acknowledgments brief — one line, not a summary of each note
- If no pending notes exist, say nothing about notes
