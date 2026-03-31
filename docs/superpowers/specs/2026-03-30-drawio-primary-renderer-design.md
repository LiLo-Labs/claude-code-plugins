# Draw.io as Primary Renderer — Design Specification

Replace custom SVG and Excalidraw with draw.io as the single rendering backend. All diagram tabs use an embedded draw.io iframe. Our semantic layer (nodes, comments, decisions, status) maps to draw.io shapes via matching IDs.

## Architecture

Every tab renders via draw.io iframe. The app layout:

```
┌─────────────────────────────────────────┐
│ Tab bar                                 │
├─────────────────────────────┬───────────┤
│                             │ Detail    │
│   Draw.io iframe            │ Panel     │
│   (full width)              │ (slide)   │
│                             │           │
├─────────────────────────────┴───────────┤
│ Comment bar                             │
└─────────────────────────────────────────┘
```

No sidebar, no custom SVG, no Excalidraw. Draw.io's own shape palette and tools handle all drawing.

## Node-to-Shape Mapping

- Claude uses `nodeId` values as `mxCell` `id` attributes in draw.io XML
- Comments, decisions, and status target nodeIds — unchanged from current model
- When a node's status changes, Claude updates the corresponding shape's style in the XML (e.g., `fillColor` changes)
- On autosave from draw.io, updated XML is stored in the view's `drawioXml` field

## How Claude Creates/Updates Diagrams

- **New diagrams / complex layouts:** Draw.io MCP (`open_drawio_xml` for XML, `open_drawio_mermaid` for sequence/class/flowchart diagrams)
- **Simple updates:** Claude reads current XML from the view, modifies it directly (change labels, colors, add/remove cells), posts back via our API
- **Hooks:** `post-tool-use` can trigger XML updates when node statuses change from file edits

## Files to Remove

- `client/src/components/Canvas.svelte`
- `client/src/components/NodeLeaf.svelte`
- `client/src/components/NodeEllipse.svelte`
- `client/src/components/NodeActor.svelte`
- `client/src/components/NodeRounded.svelte`
- `client/src/components/NodePill.svelte`
- `client/src/components/NodeContainer.svelte`
- `client/src/components/EdgeLine.svelte`
- `client/src/components/TreeView.svelte`
- `client/src/components/ExcalidrawEmbed.svelte`
- `client/src/lib/layout.js` + `layout.test.js`
- `client/src/lib/rendering.js` + `rendering.test.js`
- `client/src/lib/drag.js`

## Files to Keep

- `client/src/lib/events.js` — event store, node/edge/comment/decision model
- `client/src/lib/events.test.js` — tests
- `client/src/lib/state.svelte.js` — reactive state
- `client/src/lib/config.js` — colors/status mappings (used to generate draw.io styles)
- `client/src/lib/theme.js` — dark/light theme
- `client/src/components/DrawioEmbed.svelte` — the iframe component
- `client/src/components/ViewTabs.svelte` — tab bar with rename/delete
- `client/src/components/DetailPanel.svelte` — comments/decisions panel
- `client/src/components/CommentBar.svelte` — bottom comment strip
- `client/src/components/CommentModal.svelte` — add comment modal
- `client/src/components/ContextMenu.svelte` — right-click menu (may adapt)
- `client/src/App.svelte` — main app (heavily simplified)
- `client/src/app.css` — theme variables
- All server code, hooks, SKILL.md

## App.svelte Changes

- Remove all SVG-related imports (Canvas, NodeLeaf, EdgeLine, etc.)
- Remove Excalidraw import
- Remove `backend` switching — everything is draw.io
- Remove sidebar/tree view logic
- Remove drag state, grid layout, shape dispatch
- Keep: tab bar, draw.io embed, detail panel, comment bar/modal, context menu
- Draw.io embed takes full canvas area
- Detail panel slides in from right when a node is selected (always available, not gated by backend)

## Draw.io Embed Configuration

Minimal UI: `ui=min`, no toolbar, no grid, no page view, no libraries panel, no format panel. Just the canvas with floating toolbar for essential shape/connection tools.

## Data Flow

```
Claude → MCP/direct XML → POST /api/events (view.updated with drawioXml) → server stores
Server → GET /api/state → view.drawioXml → DrawioEmbed loads via postMessage
User edits → draw.io autosave → postMessage → onchange → POST /api/events (view.updated)
Hooks → inject view XML into Claude context → Claude can read/modify
```
