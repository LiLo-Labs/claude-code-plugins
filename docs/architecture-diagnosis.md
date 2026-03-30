# Architecture Diagnosis: Why It Feels Off (2026-03-30)

## The Core Problem

**Views were designed as filters on a global flat state rather than as first-class data containers.**

The study-tutor canvas works because **a tab is a diagram**. A diagram has its own nodes and connections. You author diagrams. You do not query them from a global pool with filter predicates.

## Four Mismatches

### 1. Tab Model Is Hollow
Study-tutor tabs: each tab has its own `nodes[]` and `connections[]`. Switching tabs = complete view replacement.
Our tabs: filters on a flat node pool. Views have no identity — just WHERE clauses.

### 2. Layout Fused To Node Identity
`row`/`col`/`cols` are on the node entity. A node is always at the same grid position regardless of which tab. Can't show the same node at different positions in different views.

### 3. App.svelte Is The Rendering Brain
App.svelte owns drag, selection, structural edge rendering, filter derivations, layout computation. It should be a thin orchestrator. Rendering belongs in components.

### 4. ViewModes vs Views — Unresolved Tension
Canvas/Timeline/Diff/Story buttons do nothing. View tabs filter weakly. Two navigation axes that don't compose.

## The Fix: Per-Tab Nodes/Connections

**Layer 1 — Node Registry (global, event-sourced):**
All nodes as canonical definitions. Label, status, depth, color, decisions, comments.

**Layer 2 — Tab Diagram (per-tab, authored):**
Each tab stores its own `tabNodes: [{ nodeId, row, col, cols }]` and `tabConnections: [{ from, to, label, color }]`. These REFERENCE registry nodes with layout overrides.

### Implementation

1. Update `view.created` event to carry `tabNodes`/`tabConnections` instead of `filter`
2. `computeLayout` accepts `tabNodes` array + `nodeRegistry` Map (decouple layout from entity)
3. Remove `row`/`col`/`cols` from node entity model
4. App.svelte: replace filter derivations with direct `activeTab` reference
5. Extract structural edges to `StructuralEdges.svelte`
6. Seed data uses per-tab node/connection arrays (matching study-tutor format)

### Why This Works

An author says exactly which nodes go on a tab and where. That produces UX that feels natural. The event store stays for audit/undo. But views are **data, not queries**.
