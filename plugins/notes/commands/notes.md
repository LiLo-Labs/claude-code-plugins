---
allowed-tools: Bash(*)
description: Capture and manage thoughts as a checklist
---

## Your task

Run the notes script with the user's arguments. The script handles all subcommands.

Run: `"${CLAUDE_PLUGIN_ROOT}/scripts/notes.sh" $ARGUMENTS`

Display the output to the user exactly as returned. Do not add commentary.

If no arguments are provided, run: `"${CLAUDE_PLUGIN_ROOT}/scripts/notes.sh" show`

## Available subcommands

- `add "text" #tag1 #tag2` — add a note (project-scoped by default)
- `add --global "text"` — add a global note
- `show [--global] [--tag X] [--done] [--pending]` — display notes
- `done N` — mark note N as done
- `undo N` — uncheck note N
- `clear` — remove all done notes
- `clear N` — remove specific note
- `clear --all` — remove all notes
