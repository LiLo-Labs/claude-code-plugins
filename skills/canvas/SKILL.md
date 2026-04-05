---
name: canvas
description: Use when the user asks to create, view, update, or interact with a design canvas, or when working on architecture/design tasks in a project with .code-canvas/
user-invocable: true
---

# Code Canvas

Visual design knowledge graph. Maps architecture, flows, pipelines, and decisions as an interactive node-and-edge diagram in the browser. Event-sourced — every change is an immutable event in `.code-canvas/events.jsonl`.

## Bootstrap

When `/canvas generate` is called and no `.code-canvas/` exists yet:

1. Create the directory: `mkdir -p .code-canvas`
2. Create empty events file: `touch .code-canvas/events.jsonl`
3. Start the server: `node "${CLAUDE_PLUGIN_ROOT}/server/index.js" --project-dir .`
   - The server auto-discovers a free port (9100-9299) and writes `.code-canvas/.server-info`
   - Run in background: append `&` or use `disown`
4. Read the project's specs, docs, or codebase structure
5. Design nodes, edges, and views (see "Generating a Canvas" below)
6. POST all events: `curl -X POST http://localhost:<port>/api/events/batch -H 'Content-Type: application/json' -d '[...events...]'`
7. Open the canvas: `open http://localhost:<port>`

If `.code-canvas/` already exists, the server URL is in the session context above.

## Commands

| Command | Behavior |
|---------|----------|
| `/canvas` | Open canvas in browser (auto-start server if needed) |
| `/canvas generate` | Read spec/codebase, POST node/edge/view events to build canvas |
| `/canvas regenerate` | Wipe all events and regenerate from scratch (fresh analysis) |
| `/canvas update` | Compare canvas state to codebase, update node statuses |
| `/canvas reset` | Wipe all canvas data (events, layouts, server info). Clean slate. |
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
| `view.created` | `viewId, name, description, rendering, tabNodes[], tabConnections[]` |
| `view.updated` | `viewId, changes: { ...changed fields }` |
| `view.deleted` | `viewId` |

## Node Model

- **depth:** `system | domain | module | interface`
- **status:** `done | in-progress | planned | placeholder`
- **confidence:** `0-3`
- **files:** Glob patterns for file-to-node tracking (e.g., `["src/lib/events.*", "server/index.js"]`)
- **category:** User-defined grouping (e.g., `"arch"`, `"flow"`, `"data"`, `"actor"` for UML actors)

## Rendering Hints

Views can carry a `rendering` object with composable hints that control how nodes and edges are drawn. Claude picks hints based on what the diagram is trying to communicate.

| Hint | Values | Default | Purpose |
|------|--------|---------|---------|
| `nodeShape` | `card`, `ellipse`, `rounded`, `pill` | `card` | How nodes are drawn |
| `nodeSize` | `compact`, `standard`, `expanded` | `standard` | Node dimensions |
| `nodeContent` | Array: `label`, `subtitle`, `fields`, `status-badge` | `["label", "subtitle"]` | What to show on nodes |
| `edgeStyle` | `curve`, `straight`, `step`, `ordered-arrows` | `curve` | How edges are drawn |
| `edgeLabels` | `pill`, `inline`, `hidden` | `pill` | Edge label style |
| `layout` | `grid`, `horizontal-lanes`, `vertical-lanes`, `layered-top-down` | `grid` | Layout algorithm |

**Auto-detection:** Nodes with `category: "actor"` automatically render as UML stick figures regardless of the view's `nodeShape` hint.

**Per-node override:** Individual nodes can override the view's shape via `tabNode.shape`.

**Examples:**

UML use case diagram:
```json
{ "rendering": { "nodeShape": "ellipse" } }
```

State machine:
```json
{ "rendering": { "nodeShape": "rounded" } }
```

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

When running `/canvas generate`, analyze the codebase and create a meaningful architecture map.

### Renderer

The canvas uses **maxGraph** (the engine behind draw.io) to render diagrams. Store draw.io XML in the view's `drawioXml` field. Use the draw.io MCP (`open_drawio_xml` or `open_drawio_mermaid`) for complex diagrams, or generate XML directly for simple updates.

**Cell IDs must match node IDs** (e.g., `n_server`). This enables click-to-detail: when a user clicks a shape, the detail panel shows that node's properties, comments, and decisions.

### Nodes

Each node is an architectural component. Include `files` glob patterns so the plugin can auto-track edits.

### Views/Tabs — Reasoning About What To Show

**The number and type of tabs should NOT be predetermined.** Analyze the codebase and decide what perspectives would help a developer understand it. Consider:

- **Complexity** — A small utility needs 1 tab. A full-stack app might need 4-5.
- **Audiences** — What would a new developer need to see first? What would a senior need for deep dives?
- **Relationships** — If there are distinct subsystems that interact, each might deserve its own tab.
- **Flow** — If there's a clear data/request flow, show it as a separate sequence or flow diagram.

Examples of view types (pick what fits, don't use all):
- Architecture layers (system → domain → module)
- Data/request flow (how data moves through the system)
- Domain model (entities and relationships)
- Deployment topology (infrastructure, services)
- Component interactions (who calls whom)
- State machines (lifecycle of key entities)

**Rules:**
- Every node on a tab MUST have at least one connection
- Keep tabs focused: 4-8 nodes per tab is ideal
- Each tab has a `description` explaining what this diagram shows
- A node can appear on multiple tabs with different connections

### Draw.io XML Best Practices

- **Spacing:** Leave 60px+ gaps between shapes within swimlanes. Use 200px+ vertical gaps between swimlane layers.
- **Edge labels:** Use separate `<mxCell>` text elements positioned near edges, NOT inline `value` on edge cells. Inline edge labels often overlap shapes.
- **Edge routing:** Always specify `exitX/exitY` and `entryX/entryY` to control which side edges connect to. Use `<Array as="points">` waypoints for edges that cross between layers.
- **Shapes:** Use `rounded=1` for components, `shape=cylinder3` for data stores, `shape=document` for docs, `shape=actor` for people/systems. All shapes should have two lines of text (name + description).
- **Font:** Use fontSize=13 for shape text, fontSize=11 for edge labels. Edge label color should be `#888` or `#999`.

### Status

Use `node.status` events after creation to set the real status. The default is `planned` — explicitly set `done`, `in-progress`, etc.

## Reset & Regenerate

When `/canvas reset` is called:
1. Stop any running server: kill the process from `.code-canvas/.server-info`
2. Wipe: `> .code-canvas/events.jsonl`
3. Remove layouts: `rm -f .code-canvas/layouts/*.json`
4. Remove marker: `rm -f .code-canvas/.claude-last-seen`
5. Confirm to user: "Canvas reset. Run `/canvas generate` to rebuild."

When `/canvas regenerate` is called:
1. Do all the reset steps above
2. Then immediately run `/canvas generate` (fresh analysis of current codebase)

## Custom Shapes

The shape registry auto-selects shapes from node properties (database → cylinder, cache → hexagon, etc.). When a project needs shapes that don't exist in the registry:

**Option 1: Inline style** — Set `shape` on the node to a raw draw.io style string:
```json
{"nodeId": "n_lambda", "label": "Lambda", "shape": "shape=mxgraph.aws4.lambda_function;fontColor=#e6edf3;fontSize=12;"}
```

**Option 2: Project-specific shapes** — Save reusable shapes to `.code-canvas/shapes.json` via the API:
```bash
curl -X PUT http://localhost:<port>/api/shapes -H 'Content-Type: application/json' -d '{
  "lambda": {"style": "shape=mxgraph.aws4.lambda_function;whiteSpace=wrap;fontSize=12;fontColor=#e6edf3;", "width": 60, "height": 60, "tags": ["aws", "serverless"], "description": "AWS Lambda function"},
  "s3-bucket": {"style": "shape=mxgraph.aws4.bucket;whiteSpace=wrap;fontSize=12;fontColor=#e6edf3;", "width": 60, "height": 60, "tags": ["aws", "storage"], "description": "S3 bucket"}
}'
```
These are loaded on client startup and available for all diagrams in that project. Use the shape name on nodes: `"shape": "lambda"`.

**Built-in shapes:** actor, server, database, queue, cache, cloud, domain, module, interface, usecase, package, class, decision, start, end, process, state, document, file, swimlane, group.

## Guidelines

- Use `actor: "claude"` when posting events
- Generate meaningful IDs: `n_<slug>`, `e_<from>_<to>`, `v_<slug>`
- Populate `files` patterns on nodes when the file mapping is clear
- Prefer updating existing nodes over creating duplicates
- After completing significant work, proactively update the canvas: change node statuses, record decisions with `decision.recorded`, update file patterns, add comments noting deviations
- When making or recommending a design/architecture decision, record it on the canvas with alternatives and reasoning
