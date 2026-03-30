# Code Canvas Plugin Integration Design

**Date:** 2026-03-30
**Status:** Draft
**Scope:** SKILL.md, hooks, context generator, server extensions

## Overview

This spec defines the plugin integration layer that makes Claude aware of the design canvas. It adds:

1. A single `/canvas` skill (SKILL.md) covering all commands
2. Lifecycle hooks (SessionStart, PostCompact, PreToolUse, PostToolUse, Stop)
3. A shared Node.js library for event reading, context generation, and API calls
4. Server extensions for batch events, state endpoint, and file-to-node mapping
5. Proactive lifecycle behaviors so the canvas stays current automatically

## File Structure

```
code-canvas-plugin/
├── .claude-plugin/
│   └── plugin.json              # Existing — add skills pointer
├── skills/
│   └── canvas/
│       └── SKILL.md             # Single skill: all /canvas commands
├── hooks/
│   ├── hooks.json               # Event → script mappings
│   ├── lib/
│   │   ├── canvas-client.js     # Shared: read events, compute summaries, API calls
│   │   └── glob-match.js        # Minimal glob matching (zero npm deps)
│   ├── session-start.js         # SessionStart + PostCompact handler
│   ├── pre-tool-use.js          # PreToolUse (EnterPlanMode) handler
│   ├── post-tool-use.js         # PostToolUse (Write/Edit) handler
│   └── stop.js                  # Stop handler (server shutdown)
├── server/                      # Existing — add batch endpoint, state endpoint, SIGTERM handling
├── client/                      # Existing — add files display in DetailPanel
└── ...
```

Zero npm dependencies in hooks/. The server remains dependency-free.

## hooks.json

```json
{
  "description": "Code Canvas plugin hooks — context injection, file tracking, server lifecycle",
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|clear|compact",
        "hooks": [{
          "type": "command",
          "command": "node \"${CLAUDE_PLUGIN_ROOT}/hooks/session-start.js\"",
          "async": false,
          "timeout": 15
        }]
      }
    ],
    "PostCompact": [
      {
        "matcher": "",
        "hooks": [{
          "type": "command",
          "command": "node \"${CLAUDE_PLUGIN_ROOT}/hooks/session-start.js\"",
          "async": false,
          "timeout": 15
        }]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "EnterPlanMode",
        "hooks": [{
          "type": "command",
          "command": "node \"${CLAUDE_PLUGIN_ROOT}/hooks/pre-tool-use.js\"",
          "async": false,
          "timeout": 5
        }]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [{
          "type": "command",
          "command": "node \"${CLAUDE_PLUGIN_ROOT}/hooks/post-tool-use.js\"",
          "async": true,
          "timeout": 10
        }]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [{
          "type": "command",
          "command": "node \"${CLAUDE_PLUGIN_ROOT}/hooks/stop.js\"",
          "async": true,
          "timeout": 5
        }]
      }
    ]
  }
}
```

**Rationale:**
- SessionStart and PostCompact share the same script (both inject L0 + instructions)
- PostToolUse is async — file-to-node matching must not block Claude's response
- PreToolUse is sync — suggestion must appear before Claude enters plan mode
- Stop is async — cleanup must not block session exit
- 15s timeout for SessionStart allows auto-starting the server if needed

## Shared Library: hooks/lib/canvas-client.js

### Server lifecycle

- `ensureServer(projectDir, pluginRoot)` — Check `.code-canvas/.server-info` for PID, verify with `/api/health` ping. If dead or missing, spawn server as detached child process (`node <pluginRoot>/server/index.js` with cwd set to `projectDir`), poll health for up to 10s, return port. The server discovers its own port and writes `.server-info`.
- `getServerUrl(projectDir)` — Read `.server-info`, return `http://localhost:<port>` or null.
- `stopServer(projectDir)` — Read PID from `.server-info`, send SIGTERM, delete file.

### Event reading (file-based, no server needed)

- `readEvents(projectDir)` — Parse `.code-canvas/events.jsonl` line by line, return event array.
- `replayState(events)` — Apply events in order, return `{ nodes: Map, edges: Map, comments: [], decisions: [], views: [] }`. Same replay logic as the client's EventStore but server-side. Must handle all event types including the `files` field on `node.created`/`node.updated`.

### Context generation

- `generateL0(state)` — ~200 tokens. Format:
  ```
  Design Canvas: <project name>
  Nodes: N (X done, Y in-progress, Z planned)
  Edges: N connections
  Views: <comma-separated view names>
  Comments: N unresolved
  Decisions: N recorded
  Last activity: <relative timestamp>
  ```

- `generateL1(state)` — ~500-1000 tokens. Full structure:
  ```
  Nodes:
  - <id>: <label> [<status>] (<depth>) files: <patterns>
  Edges:
  - <from> → <to>: <label>
  Views:
  - <name>: <node count> nodes, <connection count> connections
  Unresolved comments:
  - <target>: "<text>" (<actor>)
  ```

### File-to-node matching

- `findNodesForFile(filePath, nodes)` — Iterate all nodes, check `filePath` against each node's `files` glob patterns using `glob-match.js`. Return array of matching node IDs.

### API helpers

- `postEvent(serverUrl, event)` — POST to `/api/events`, return response.
- `postEvents(serverUrl, events)` — POST to `/api/events/batch`, return `{ appended: N }`.

## hooks/lib/glob-match.js

Minimal glob matcher (~30 lines, zero dependencies):
- Supports `*` (any non-slash segment), `**` (any path depth), `?` (single char)
- `globMatch(pattern, filePath)` — Returns boolean
- Converts glob to regex: `*` → `[^/]*`, `**` → `.*`, `?` → `.`
- Anchored match (full path must match)

## Hook Behaviors

### session-start.js (SessionStart + PostCompact)

1. Find project dir: walk up from cwd looking for `.code-canvas/`
2. If not found → output `{}` to stdout and exit 0 (not a canvas project)
3. Read events.jsonl directly, replay state
4. Generate L0 summary
5. Ensure server is running (auto-start if needed)
6. Output JSON with `hookSpecificOutput.additionalContext`:

```
## Code Canvas Active

<L0 summary>

### Commands
- `/canvas` — Open canvas in browser
- `/canvas generate` — Generate canvas from spec/codebase
- `/canvas update` — Sync canvas with implementation progress
- `/canvas diff [since]` — Show changes since timestamp
- `/canvas comments` — List unresolved comments
- `/canvas story` — Decision history narrative
- `/canvas export md` — Export as markdown

### API
Server: http://localhost:<port>
POST /api/events — append event (JSON body with {type, actor, data})
POST /api/events/batch — append multiple events (JSON array)
GET /api/events — fetch all events
GET /api/state — current state (?level=L0|L1)

### Proactive Canvas Maintenance
After completing significant work, update the canvas:
- Change node statuses to reflect progress
- Record decisions with alternatives and reasoning
- Update file patterns when creating/restructuring files
- Add comments noting deviations from the plan
```

### pre-tool-use.js (PreToolUse → EnterPlanMode)

1. Find `.code-canvas/` — output `{}` and exit 0 if absent
2. Read events, replay state
3. If canvas has nodes:
   > "A design canvas exists for this project with N nodes across M views. Consider reviewing it before planning. Use `/canvas` to open in browser."
4. If canvas is empty:
   > "This project has a design canvas but it's empty. Use `/canvas generate` to populate it from a spec or codebase analysis."

### post-tool-use.js (PostToolUse → Write/Edit)

1. Read tool result from stdin (JSON with file path)
2. Extract the file path that was written/edited
3. Find `.code-canvas/` — exit 0 silently if absent
4. Read events.jsonl, replay state
5. Match file path against node glob patterns via `findNodesForFile()`
6. For each matching node where status is `planned`:
   - Ensure server is running
   - POST `node.status` event: `{ nodeId, status: "in-progress", prev: "planned" }` with `actor: "system"`
7. No stdout output (async hook, no context injection)

### stop.js (Stop)

1. Find `.code-canvas/.server-info` — exit if absent
2. Read PID, verify process exists
3. Send SIGTERM to server process
4. Delete `.server-info`
5. Exit cleanly

## SKILL.md

```yaml
---
name: canvas
description: Use when the user asks to create, view, update, or interact with a design canvas, or when working on architecture/design tasks in a project with .code-canvas/
user-invocable: true
---
```

**Body (~400 words) covers:**

### Overview
Code Canvas is a visual design knowledge graph. It maps architecture, flows, pipelines, and decisions as an interactive node-and-edge diagram in the browser. The canvas is event-sourced — every change is an immutable event in `.code-canvas/events.jsonl`.

### Commands

| Command | Behavior |
|---------|----------|
| `/canvas` | Open canvas in browser (auto-start server if needed) |
| `/canvas generate` | Read spec/codebase, POST node/edge/view events to build canvas |
| `/canvas update` | Compare canvas state to codebase, update node statuses |
| `/canvas diff [since]` | Read events after ISO timestamp, summarize what changed |
| `/canvas comments` | List unresolved comments with targets |
| `/canvas story` | Narrate decision history from `decision.recorded` events |
| `/canvas export md` | Generate markdown summary of current state |

### Event Schema

| Type | Data fields |
|------|-------------|
| `node.created` | `nodeId, label, subtitle, parent, depth, category, confidence, status, files[]` |
| `node.updated` | `nodeId, ...changed fields` |
| `node.deleted` | `nodeId` |
| `node.status` | `nodeId, status, prev` |
| `edge.created` | `edgeId, from, to, label, edgeType, color` |
| `edge.updated` | `edgeId, ...changed fields` |
| `edge.deleted` | `edgeId` |
| `decision.recorded` | `nodeId, chosen, alternatives[], reason` |
| `comment.added` | `commentId, target, targetLabel, text, actor` |
| `comment.resolved` | `commentId` |
| `view.created` | `viewId, name, description, tabNodes[], tabConnections[]` |
| `view.updated` | `viewId, ...changed fields` |

All events use envelope: `{ id, ts, type, actor, data }`

### Node Model

- **depth:** `system | domain | module | interface` (controls border color)
- **status:** `done | in-progress | planned | placeholder` (controls badge)
- **confidence:** `0-3` (visual indicator: 3=solid, 0=hatched)
- **files:** Array of glob patterns (e.g., `["src/lib/events.*", "server/index.js"]`) for file-to-node tracking
- **category:** User-defined grouping (e.g., `"arch"`, `"flow"`, `"data"`)

### API Reference

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/events` | GET | Fetch all events |
| `/api/events` | POST | Append single event |
| `/api/events/batch` | POST | Append multiple events (JSON array) |
| `/api/state` | GET | Current replayed state (?level=L0\|L1) |
| `/api/layouts/:viewId` | GET/PUT | Node positions per view |
| `/api/health` | GET | Server health |

### Guidelines

- Use `actor: "claude"` when posting events
- Generate meaningful IDs: `n_<slug>`, `e_<from>_<to>`, `v_<slug>`
- When generating from a spec, create at least one view/tab with positioned nodes (tabNodes with row/col)
- Populate `files` patterns on nodes when the file mapping is clear
- Prefer updating existing nodes over creating duplicates
- After completing significant implementation work, proactively update the canvas:
  - Change node statuses to reflect progress
  - Record decisions with `decision.recorded` including alternatives and reasoning
  - Update `files` patterns when creating or restructuring files
  - Add comments noting deviations from the original plan
- When making or recommending a design/architecture decision, record it on the canvas

## Server Extensions

### POST /api/events/batch

- Accepts: JSON array of event objects
- Appends all to events.jsonl in a single write (atomic)
- Returns: `{ appended: N }`
- Validates each event has required fields (type, actor, data)

### GET /api/state

- Returns: Full replayed state `{ nodes, edges, comments, decisions, views }`
- Optional query param `?level=L0` returns pre-formatted L0 summary string
- Optional query param `?level=L1` returns pre-formatted L1 structure string

### Node model: files field

- `node.created` and `node.updated` events accept optional `files` array (glob patterns)
- Replay logic stores `files` on the node object
- Client DetailPanel displays file patterns as a read-only list

### Graceful shutdown

- Server listens for SIGTERM
- Flushes any pending writes
- Removes `.code-canvas/.server-info`
- Exits with code 0

## Lifecycle Continuity

The canvas stays current through the full project lifecycle:

| Phase | Mechanism | What happens |
|-------|-----------|--------------|
| Session start | SessionStart hook | L0 injected, server auto-started, Claude knows canvas exists |
| Planning | PreToolUse hook | Claude reminded to check canvas before entering plan mode |
| Implementation | PostToolUse hook | File edits auto-track node status (planned → in-progress) |
| Implementation | SKILL.md guidelines | Claude proactively records decisions, updates statuses, adds comments |
| Context loss | PostCompact hook | L0 re-injected after compression so Claude doesn't forget canvas |
| Session end | Stop hook | Server gracefully shut down, .server-info cleaned |
| Next session | SessionStart hook | Fresh L0 with accumulated state — full history preserved in JSONL |

The event log is the complete project history. Every decision, status change, comment, and structural change is timestamped and attributed. No information is lost between sessions.

## plugin.json Update

Add skills pointer to existing manifest:

```json
{
  "name": "code-canvas",
  "description": "Interactive visual design knowledge graph for software architecture...",
  "version": "0.2.0",
  "skills": "./skills/canvas",
  ...existing fields...
}
```

## Testing

- **canvas-client.js:** Unit tests for `readEvents`, `replayState`, `generateL0`, `generateL1`, `findNodesForFile`, `globMatch`
- **Hook scripts:** Integration tests that verify JSON output format, silent exit when no `.code-canvas/`, correct context injection
- **Server endpoints:** Tests for `/api/events/batch` (atomic append, validation), `/api/state` (level param, full replay), SIGTERM handling
- **End-to-end:** Manual test: start session in project with `.code-canvas/`, verify L0 appears, run `/canvas generate`, verify events posted, edit a file, verify status auto-updates
