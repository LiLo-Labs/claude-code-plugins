# Code Canvas v2 — Clean Rebuild Design

## Summary

Clean rewrite of code-canvas client and server using the same proven stack (Svelte 5, maxGraph, Node, JSONL events). Hooks and plugin config are kept as-is. All v1 technical learnings are baked in as architectural requirements.

## Architecture

Three layers with clean separation:

```
Client (Svelte 5 + Vite)
  App.svelte              — shell/layout
  MaxGraphCanvas.svelte   — maxGraph renderer
  DetailPanel.svelte      — node info on click
  ContextMenu.svelte      — right-click actions
  ViewTabs.svelte         — tab bar
  CommentBar.svelte       — bottom comment strip
  CommentModal.svelte     — add comment dialog
  lib/
    store.js              — pure EventStore class (no framework deps)
    store.svelte.js       — Svelte reactive wrapper
    api.js                — fetch + SSE client
    maxgraph.js           — graph creation, XML I/O, zoom-to-fit
    theme.js              — CSS custom properties, dark/light toggle
    config.js             — status colors, constants

Server (Node, zero deps)
  index.js                — HTTP server, REST API, SSE, static serving

Hooks (unchanged from v1)
  session-start.js, pre-tool-use.js, post-tool-use.js, stop.js
  hooks.json, lib/canvas-client.js, lib/glob-match.js
```

## Data Model

Event-sourced JSONL (unchanged). Event types:

- `node.created`, `node.updated`, `node.deleted` — shape lifecycle
- `edge.created`, `edge.updated`, `edge.deleted` — connections
- `view.created`, `view.updated`, `view.deleted` — diagram tabs with drawioXml
- `comment.added`, `comment.resolved`, `comment.deleted` — comments on nodes
- `decision.recorded` — architectural decisions with alternatives
- `status.changed` — node status transitions

State is derived by replaying events. EventStore is a pure JS class with `apply(event)` and `getState()`.

## Server API

All endpoints under `/api/`:

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/events` | All events as JSON array |
| POST | `/api/events` | Append single event |
| POST | `/api/events/batch` | Append multiple events |
| GET | `/api/state` | Computed state (optional `?level=L0\|L1`) |
| GET | `/api/events/stream` | SSE stream for real-time sync |
| GET | `/api/layouts/:viewId` | Get layout XML for a view |
| PUT | `/api/layouts/:viewId` | Save layout XML for a view |

Static files served from `client/dist/` at root.

Server resilience (v1 lesson):
- `process.stdin.resume()` keeps event loop alive
- Ignore SIGHUP, SIGTERM (only SIGINT kills)
- `uncaughtException` handler logs and continues
- Launch: `nohup node server/index.js --project-dir . </dev/null &`
- Write `.server-info` JSON with `{port, pid, startedAt}`

## Client Components

### MaxGraphCanvas.svelte
The core renderer. Wraps all maxGraph interaction.

- `createGraph(container)` — init with settings, default styles, undo manager
- `loadXml(xml)` — `model.clear()` first (v1 lesson: codec merges, doesn't replace)
- `serializeXml()` — encode model to XML string
- Zoom-to-fit via manual `scaleAndTranslate()` (v1 lesson: `graph.fit()` doesn't exist)
- Native `keydown` for Ctrl+Z/Y undo/redo (v1 lesson: `KeyHandler` unreliable)
- Container: `tabindex="0"`, auto-focus on mousedown
- Default edge style: `rounded: true, curved: true`
- Debounced auto-save (1s) on model changes → `onchange` callback
- Selection events → `onselect` callback with cell IDs
- `contextmenu` event on cells → `oncontextmenu` callback with position + cell

### DetailPanel.svelte
Left side panel, appears only on shape click.

Shows: node name, status badge, description, file patterns, comments (resolve/delete), related decisions. Close button and click-away-to-close.

### ContextMenu.svelte
Positioned absolutely at cursor. Appears on right-click of a maxGraph cell.

Actions:
- **Change Status** — submenu: planned, in-progress, done, blocked, cut
- **Add Comment** — opens CommentModal
- **View Details** — opens DetailPanel

Dismisses on click-away or Escape.

### ViewTabs.svelte
Horizontal tab bar above canvas. Each tab = one view with its own drawioXml.

- Click to switch (triggers `model.clear()` + reload)
- Double-click to rename
- X button to delete (with confirm)
- "+" button to create new tab

### CommentBar.svelte
Bottom strip showing unresolved comments. Click navigates to node + opens detail panel.

### CommentModal.svelte
Dialog for adding a comment to a node. Text input + submit.

## Theme

Two CSS variable sets (dark and light) applied to `:root`. Toggle persisted in localStorage.

Dark defaults:
- `--bg: #0d1117`, `--bg-s: #161b22`, `--bg-e: #1c2128`
- `--tx: #e6edf3`, `--tx-m: #8b949e`, `--tx-d: #484f58`
- `--ac: #58a6ff`, `--gr: #3fb950`, `--or: #d29922`, `--rd: #f85149`
- maxGraph container: `#1a1a2e`

## What Gets Deleted vs Kept

**Keep as-is:**
- `hooks/*` (all hook scripts and lib/)
- `.claude-plugin/plugin.json`
- `package.json` (workspace structure, deps)
- `client/package.json`, `client/vite.config.js`, `client/svelte.config.js`, `client/index.html`
- `skills/canvas/SKILL.md`
- `.code-canvas/` (data directory)
- `vitest.workspace.js`
- `scripts/seed-demo.sh`

**Delete and rewrite:**
- `client/src/*` (all components and lib/)
- `server/index.js`

**Delete (not needed):**
- `server/index.test.js` (will write new tests)
- `docs/architecture-diagnosis.md`, `docs/ux-gaps-v2.md`, `docs/review-findings.md` (v1 analysis docs)

## Build Sequence

1. **EventStore** (`lib/store.js`) — pure logic, test with vitest
2. **Server** (`server/index.js`) — API + SSE + static serving, test with vitest
3. **API client** (`lib/api.js`) — fetch wrapper + SSE subscription
4. **Theme** (`lib/theme.js` + `app.css`) — CSS variables
5. **maxGraph wrapper** (`lib/maxgraph.js`) — graph utils
6. **MaxGraphCanvas.svelte** — renderer component
7. **App shell** (`App.svelte`) — layout, tab switching, state wiring
8. **ViewTabs** — tab bar component
9. **DetailPanel** — node detail on click
10. **ContextMenu** — right-click actions
11. **CommentBar + CommentModal** — comment UI
12. **Integration test** — boot server, load client, verify end-to-end
