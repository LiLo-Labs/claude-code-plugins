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

### F19. Comment badge font 9px — below 10px minimum
**File:** `NodeLeaf.svelte:89`, `TreeView.svelte:65`
Tree chevron also 9px. Spec says nothing below 10px.

### F20. Edge label pill 24px/rx12 — spec says 20px/rx10
**File:** `EdgeLine.svelte:53,72`

### F21. Container header label y-offset 4px too low
**File:** `NodeContainer.svelte:34` — placed at y+24, should be y+20 for 40px header center.

### F22. Workaround icon overlaps status badge
**File:** `NodeLeaf.svelte:52,72` — both positioned at right edge, overlap for short status words.

### F23. Bottom-row element crowding
**File:** `NodeLeaf.svelte:82-98` — confidence dots, child preview dots, and comment badge all compete for the same y-band.

### F24. Spec section 2.3 says 210x74 but section 6.1 says 280x90
Internal spec conflict. Code follows 6.1 (correct). Strike section 2.3 node dimensions.

### F25. Completeness bar not rendered on canvas nodes
Spec 2.3 describes it, data exists in model and panel, but no SVG bar on nodes.

### F26. Parent-child structural dotted edges not implemented
Spec 2.4 mechanism 2 — light dotted lines from parent to children. Only data-flow edges render.

### F27. Color banding (sibling tint inheritance) not implemented
Spec 2.4 mechanism 3 — children should inherit parent's depth color tint. All use uniform `var(--bg-n)`.

## Low

### F28. Port scan capped at 200, no stale server-info cleanup
### F29. A11y warnings globally suppressed
### F30. savedPositions parameter in layout.js never passed by caller
