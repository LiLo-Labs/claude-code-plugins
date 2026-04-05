# Notes Plugin Design Spec

A Claude Code plugin that provides a `/notes` slash command for capturing thoughts as a checklist during conversations — especially while agents are running — and surfacing them to Claude at the right time.

## Problem

When agents are running, the user has thoughts and ideas they don't want to forget. There's no lightweight way to capture these so Claude sees them at the right moment. Notes get lost or the user has to interrupt their flow.

## Solution

A plugin with four components:

1. **Shell script** (`notes.sh`) — deterministic CRUD for notes stored as JSON
2. **Command** (`notes.md`) — `/notes` slash command that delegates to the script
3. **Skill** (`SKILL.md`) — teaches Claude when to check notes and how to mark them done
4. **Hook** (`session-start.sh`) — auto-displays pending notes at conversation start

## Storage

### Format

```json
{
  "notes": [
    {
      "id": 1,
      "text": "consider using webhooks instead of polling",
      "tags": ["architecture", "api"],
      "done": false,
      "created": "2026-04-03T14:30:00Z"
    }
  ],
  "next_id": 2
}
```

### Locations

- **Project-scoped:** `~/.claude/projects/<project-path>/notes.json`
- **Global:** `~/.claude/notes.json`

IDs are monotonically increasing and never reused within a file, so `done 3` always refers to the same note even after others are cleared.

## Commands

All commands are handled by `/notes <subcommand> [args]`:

| Subcommand | Description |
|------------|-------------|
| `add "text" #tag1 #tag2` | Add an unchecked note with optional tags (project-scoped by default) |
| `add --global "text" #tag1` | Add to global notes |
| `show` | Display all project notes with IDs, checkbox status, tags, relative timestamps |
| `show --global` | Show global notes |
| `show --tag X` | Filter by tag |
| `show --done` | Show only completed notes |
| `show --pending` | Show only unchecked notes |
| `done N` | Mark note N as done |
| `undo N` | Uncheck note N |
| `clear` | Remove all done notes |
| `clear N` | Remove a specific note by ID |
| `clear --all` | Remove all notes |

### Display Format

```
Project Notes (~/my-project)
  [ ] #1  consider using webhooks instead of polling  #architecture #api  (2h ago)
  [x] #2  check if rate limiting exists               #api               (1h ago)
  [ ] #3  ask about caching strategy                  #performance       (30m ago)

Global Notes
  [ ] #1  update dotfiles backup script               #devtools          (1d ago)
```

## Shell Script (`notes.sh`)

Handles all JSON file manipulation. No LLM in the loop for CRUD operations.

**Responsibilities:**
- Parse subcommands and arguments
- Read/write JSON files atomically
- Resolve project path for project-scoped notes (`~/.claude/projects/` convention)
- Format output for display
- Handle edge cases (missing files, invalid IDs, empty state)

**Project path resolution:** Uses the same path-hashing convention as Claude Code's project settings (the current working directory path encoded into the `~/.claude/projects/` directory structure).

## Skill (`SKILL.md`)

Behavioral instructions for Claude with three trigger points:

### 1. Conversation Start
- Read both project and global notes files
- Surface pending (unchecked) items as context
- Don't act on them unprompted — acknowledge: "You have N pending notes — I'll keep these in mind."

### 2. After Agents Return
- Check for pending notes before continuing work
- Notes captured while agents were running are likely relevant to what just completed
- Surface any new notes added since last check

### 3. Marking Notes Done
- When Claude directly addresses or resolves a noted concern, mark it done via `notes.sh`
- Tell the user: "Marked note #3 as done — we addressed the caching strategy."
- Claude should NOT mark notes done speculatively — only when the concern is clearly resolved

### Skill Trigger
The skill description should reference `/notes` and note-checking so it's invoked when relevant. It should NOT trigger on every message — only at the three checkpoints above.

## Hook (`session-start.sh`)

Runs at session start. Calls `notes.sh show --pending` for both project and global scope. Outputs to stdout so it appears in the conversation context.

If there are no pending notes, outputs nothing (silent).

## Plugin Structure

```
plugins/notes/
  .claude-plugin/
    plugin.json
  commands/
    notes.md
  skills/
    notes/
      SKILL.md
  scripts/
    notes.sh
  hooks/
    hooks.json
    session-start.sh
  README.md
```

### plugin.json

```json
{
  "name": "notes",
  "description": "Capture thoughts as a checklist during conversations and surface them to Claude at the right time",
  "version": "1.0.0",
  "author": {
    "name": "LiloLabs"
  }
}
```

## Future Considerations (not in v1)

- **Linking notes** — connecting related notes together
- **Note priorities** — urgent vs. nice-to-have
- **Archiving** — move done notes to an archive rather than deleting
- **Search** — full-text search across all notes
