---
name: canvas
description: Use when the user asks to create, view, update, or interact with a design canvas, or when working on architecture/design tasks in a project with .code-canvas/
user-invocable: true
---

# Code Canvas

Visual design knowledge graph. Maps architecture, flows, pipelines, and decisions as an interactive node-and-edge diagram in the browser. Event-sourced — every change is an immutable event in `.code-canvas/events.jsonl`.

## Bootstrap

The plugin auto-creates `.code-canvas/` and starts the server at session start. To populate an empty canvas:

1. Read the project's specs, docs, or codebase structure
2. Design nodes (components/modules), edges (dependencies/data flows), and at least one view
3. POST all events via the batch endpoint: `curl -X POST http://localhost:<port>/api/events/batch -H 'Content-Type: application/json' -d '[...events...]'`
4. Open the canvas: `open http://localhost:<port>`

The server URL is provided in the session context above. If you need to restart it manually:
```
node "${CLAUDE_PLUGIN_ROOT}/server/index.js" --project-dir .
```

## Commands

| Command | Behavior |
|---------|----------|
| `/canvas` | Open canvas in browser (auto-start server if needed) |
| `/canvas generate` | Read spec/codebase, POST node/edge/view events to build canvas |
| `/canvas update` | Compare canvas state to codebase, update node statuses |
| `/canvas diff [since]` | Read events after ISO timestamp, summarize what changed |
| `/canvas comments` | List unresolved comments with targets |
| `/canvas story` | Narrate decision history from `decision.recorded` events |
| `/canvas export md` | Generate markdown summary of current state |

## Event Schema

All events use envelope: `{ id, ts, type, actor, data }`

| Type | Data fields |
|------|-------------|
| `node.created` | `nodeId, label, subtitle, parent, depth, category, confidence, status, files[]` |
| `node.updated` | `nodeId, changes: { ...changed fields }` |
| `node.deleted` | `nodeId` |
| `node.status` | `nodeId, status, prev` |
| `edge.created` | `edgeId, from, to, label, edgeType, color` |
| `edge.updated` | `edgeId, changes: { ...changed fields }` |
| `edge.deleted` | `edgeId` |
| `decision.recorded` | `nodeId, type (decision\|workaround), chosen, alternatives[], reason` |
| `comment.added` | `commentId, target, targetLabel, text, actor` |
| `comment.resolved` | `commentId` |
| `comment.reopened` | `commentId` |
| `comment.deleted` | `commentId` |
| `view.created` | `viewId, name, description, tabNodes[], tabConnections[]` |
| `view.updated` | `viewId, changes: { ...changed fields }` |

## Node Model

- **depth:** `system | domain | module | interface`
- **status:** `done | in-progress | planned | placeholder`
- **confidence:** `0-3`
- **files:** Glob patterns for file-to-node tracking (e.g., `["src/lib/events.*", "server/index.js"]`)
- **category:** User-defined grouping (e.g., `"arch"`, `"flow"`, `"data"`)

## API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/events` | GET | Fetch all events |
| `/api/events` | POST | Append single event |
| `/api/events/batch` | POST | Append multiple events (JSON array) |
| `/api/state` | GET | Current replayed state (?level=L0\|L1) |
| `/api/layouts/:viewId` | GET/PUT | Node positions per view |
| `/api/health` | GET | Server health |

## Generating a Canvas

When running `/canvas generate`, analyze the codebase and create a meaningful architecture map:

**Nodes:** Each node is an architectural component. Include `files` glob patterns so the plugin can auto-track edits.

**Edges:** Every node on a tab MUST have at least one connection. If a node has no edges, it doesn't belong on that tab. Edges show real relationships: data flows, dependencies, API calls.

**Views/Tabs:** Each tab tells a different story about the system. Don't dump everything on one tab.
- Think about what perspectives matter: data flow, component hierarchy, deployment, domain boundaries
- Each tab has a `description` explaining what this diagram shows (displayed as a header overlay)
- A node can appear on multiple tabs with different connections
- Keep tabs focused: 4-8 nodes per tab is ideal, 10+ gets cluttered

**Layout:** Use `row`/`col` grid coordinates. Column 0 is leftmost. Keep columns 0-2 for most diagrams (wider spreads require zooming out). Place connected nodes adjacent to each other.

**Status:** Use `node.status` events after creation to set the real status. The default is `planned` — explicitly set `done`, `in-progress`, etc.

## Guidelines

- Use `actor: "claude"` when posting events
- Generate meaningful IDs: `n_<slug>`, `e_<from>_<to>`, `v_<slug>`
- Populate `files` patterns on nodes when the file mapping is clear
- Prefer updating existing nodes over creating duplicates
- After completing significant work, proactively update the canvas: change node statuses, record decisions with `decision.recorded`, update file patterns, add comments noting deviations
- When making or recommending a design/architecture decision, record it on the canvas with alternatives and reasoning
