# Notes Plugin

A Claude Code plugin for capturing thoughts as a checklist during conversations — especially while agents are running — and surfacing them to Claude at the right time.

## Commands

| Command | Description |
|---------|-------------|
| `/notes add "text" #tag1 #tag2` | Add a note with optional tags |
| `/notes add --global "text"` | Add a global (cross-project) note |
| `/notes show` | Show all project notes |
| `/notes show --global` | Show global notes |
| `/notes show --tag X` | Filter by tag |
| `/notes show --done` / `--pending` | Filter by status |
| `/notes done N` | Mark note N as done |
| `/notes undo N` | Uncheck note N |
| `/notes clear` | Remove all done notes |
| `/notes clear N` | Remove specific note |
| `/notes clear --all` | Remove all notes |

## Storage

- **Project notes:** `~/.claude/projects/<project-path>/notes.json`
- **Global notes:** `~/.claude/notes.json`

## Behavior

- Pending notes are shown automatically at conversation start
- Claude checks for new notes after agents return
- Claude marks notes done as it addresses them
