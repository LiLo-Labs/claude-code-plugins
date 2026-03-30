# Code Canvas — Review Findings (2026-03-30)

Consolidated from: code-reviewer agent, Codex council member, UX reviewer, visual inspection via Playwright.

## Critical (Fix First)

### F1. `$derived` wraps arrow function — ancestor highlighting broken
**File:** `client/src/App.svelte:36-39`
`$derived(() => { ... })` evaluates to a stable function reference, not a reactive Set.
**Fix:** `$derived(selectedNode ? new Set(...) : new Set())` — remove the arrow wrapper.

### F2. EventStore not reactive — client-side events don't update UI
**File:** `client/src/lib/state.svelte.js:30`
`appState.store.apply(event)` mutates internal Maps but Svelte 5 never re-renders because `appState.store` reference doesn't change.
**Fix:** Either replace `appState.store` with a new instance after each event, or track a reactive version counter.

### F3. Edges invisible — connect to collapsed/hidden nodes with no positions
**File:** `client/src/App.svelte` edge rendering section
Edges reference child nodes (e.g., `events` → `graph-e`) but when their parent is collapsed, they have no layout positions.
**Fix:** Re-route edges to the nearest visible ancestor when an endpoint is collapsed.

### F4. CORS wildcard allows any website to mutate events
**File:** `server/index.js:108`
`Access-Control-Allow-Origin: *` with POST means any web page can write to the event store.
**Fix:** Restrict to `localhost` origin or add a session token.

## High

### F5. Layout path traversal guard fails with relative project-dir
**File:** `server/index.js:127-138`
`path.join` vs `path.resolve` mismatch causes `startsWith` to always fail when `--project-dir` is relative.
**Fix:** Use `path.resolve` consistently.

### F6. Malformed JSONL line breaks all reads
**File:** `server/index.js:47-50`
No per-line error handling in `readEvents()`.
**Fix:** Wrap each `JSON.parse` in try/catch, skip bad lines.

### F7. node.deleted leaves orphaned children, edges, comments
**File:** `client/src/lib/events.js:57`
Only removes the node itself, not descendants or connected entities.
**Fix:** Cascade delete children, remove connected edges and comments.

### F8. Nodes all stacked vertically — layout needs horizontal spreading
**Visual:** Screenshot shows all 4 children in one narrow column inside the parent container.
**Fix:** Layout engine should support horizontal arrangement for siblings, or a grid layout.

## Medium

### F9. No drag implementation — nodes can't be moved
**File:** `client/src/components/NodeLeaf.svelte:21`
`onmousedown` immediately fires `onselect`, no drag tracking. Design spec requires draggable nodes.
**Fix:** Implement drag system with mousedown → mousemove → mouseup, distinguish click from drag.

### F10. Unbounded request body size
**File:** `server/index.js:62`
**Fix:** Add 1MB body limit.

### F11. Server accepts events with no data validation
**File:** `server/index.js:118`
Only checks `body.type` exists. Missing/invalid `data` accepted.
**Fix:** Validate required fields per event type.

### F12. "Synced" shown even when POST fails
**File:** `client/src/lib/state.svelte.js:37`, `client/src/App.svelte:189`
Optimistic apply with no rollback or error surfacing.
**Fix:** Track sync state, show warning on failure.

### F13. _recomputeCompleteness is O(n²), called on every event
**File:** `client/src/lib/events.js:163-173`
Scans all nodes for each node to find children.
**Fix:** Maintain a childrenMap, update incrementally.

### F14. `getSvgEl` export invalid in Svelte 5
**File:** `client/src/components/Canvas.svelte:46`
`export function` doesn't work in Svelte 5 runes mode.
**Fix:** Use `bind:this` pattern instead.

### F15. readEvents() is synchronous, called on every /health request
**File:** `server/index.js:144-152`
Parses entire JSONL just for a count.
**Fix:** Track event count in memory.

### F16. Light theme washed out — containers barely visible
**Visual:** Container tints too faint against white.
**Fix:** Increase container tint opacity for light theme.

### F17. View modes and search non-functional
Buttons change state but render path is Canvas-only. Search bound but not used.

### F18. TreeView crash on empty depth string
**File:** `client/src/components/TreeView.svelte:48`
`node.depth[0].toUpperCase()` throws if depth is empty.
**Fix:** Guard with `(node.depth?.[0] || '?').toUpperCase()`.

## Low

### F19. Port scan capped at 200, no stale server-info cleanup
### F20. A11y warnings globally suppressed
