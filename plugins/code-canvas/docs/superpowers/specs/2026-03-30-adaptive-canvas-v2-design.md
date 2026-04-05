# Adaptive Canvas v2 — Design Specification

A redesign of Code Canvas from a static architecture mapper into a living, adaptive visual reasoning surface that Claude actively reads, writes, and evolves alongside the codebase.

## Goals

1. **Visual polish** — Canvas looks like a polished design tool (Excalidraw/Whimsical quality), not a debug dump
2. **Active Claude integration** — Claude reads the canvas for context, writes to it as it works, sketches architecture before building, records decisions, and respects user-authored content
3. **Adaptive diagrams** — Multiple diagram styles (architecture, sequence, state, data model, layers) rendered from the same underlying node/edge model via composable rendering hints
4. **Shared mental model** — Both Claude and user read/write the same graph; event log tracks who changed what

---

## 1. Rendering Hints System

### Problem
Today every view renders identically — boxes and arrows. The canvas can only show one kind of diagram.

### Solution
Views carry a `rendering` object with composable hints. Claude picks hints based on what it's trying to communicate. No fixed "diagram types" — hints are mixed and matched freely.

### Hint Properties

**Layout hints:**
- `layout` — `"grid"`, `"horizontal-lanes"`, `"vertical-lanes"`, `"radial"`, `"layered-top-down"`, `"force-directed"`
- `groupBy` — property to group nodes by: `"depth"`, `"category"`, `"parent"`, `null`
- `ordering` — edge/node ordering: `"temporal"`, `"dependency"`, `"alphabetical"`, `null`

**Node hints:**
- `nodeShape` — `"card"`, `"rounded"`, `"pill"`, `"circle"`, `"minimal"`
- `nodeContent` — array of what to show: `["label"]`, `["label", "subtitle"]`, `["label", "fields"]`, `["label", "status-badge"]`
- `nodeSize` — `"compact"`, `"standard"`, `"expanded"`

**Edge hints:**
- `edgeStyle` — `"curve"`, `"straight"`, `"step"`, `"ordered-arrows"`
- `edgeLabels` — `"pill"`, `"inline"`, `"hidden"`
- `edgeWeight` — whether to vary thickness by some metric

**Chrome hints:**
- `showLegend` — whether to show a color/shape legend
- `annotations` — freeform text/arrows Claude can place on the canvas

### Examples

Architecture overview:
```json
{ "layout": "layered-top-down", "nodeShape": "card", "nodeContent": ["label", "subtitle"], "nodeSize": "standard" }
```

Sequence diagram:
```json
{ "layout": "horizontal-lanes", "ordering": "temporal", "edgeStyle": "ordered-arrows", "nodeShape": "pill" }
```

Data model:
```json
{ "layout": "grid", "nodeShape": "card", "nodeContent": ["label", "fields"], "edgeLabels": "inline" }
```

State machine:
```json
{ "layout": "force-directed", "nodeShape": "rounded", "edgeLabels": "pill" }
```

### Renderer Architecture
- Each hint value maps to a Svelte component or layout function
- `Canvas.svelte` reads the active view's hints and dispatches to the appropriate node/edge/layout renderers
- Layout algorithms live in `layout.js` as composable functions: `gridLayout()`, `laneLayout()`, `layeredLayout()`, `forceLayout()`
- Node shapes are separate Svelte components: `NodeCard.svelte`, `NodeRounded.svelte`, `NodePill.svelte`, etc.
- Sensible defaults for every hint — Claude only specifies what matters

---

## 2. Active Claude Integration

### 2a. Canvas-Aware Reasoning (Architecture Advisor)

When Claude receives a task, hooks inject relevant canvas context — not just a summary, but the nodes mapped to files being discussed, their decisions, edges, and comments.

Claude is taught to:
- Check the canvas before modifying code: "What nodes does this touch? Are there recorded decisions I should respect?"
- Warn when a change contradicts a recorded decision
- Surface which nodes are affected by a proposed change

**Hook change:** `pre-tool-use` expands to cover `Write` and `Edit` (not just `EnterPlanMode`). It injects the relevant node subgraph for the files being touched, as structured JSON.

### 2b. Proactive Canvas Maintenance (Living Documentation)

Claude updates the canvas as a side effect of working:
- **New files → new nodes:** When Claude creates a file that doesn't match any existing node's `files` patterns, it creates a node and connects it to related nodes
- **Decisions → decision events:** When Claude chooses between approaches, it records `decision.recorded` events automatically
- **Deviations → comments:** When implementation diverges from what a node describes, Claude adds a comment noting why
- **Status tracking:** Gets smarter — tracks `done` when tests pass, not just `in-progress` when files are edited

**Hook change:** `post-tool-use` gets richer pattern matching. Skill prompt teaches Claude to record decisions and deviations naturally.

### 2c. Design-First Sketching

For non-trivial work, Claude:
1. Creates/updates nodes representing what it plans to build
2. Picks appropriate rendering hints for the view
3. Tells the user: "I've sketched the architecture on the canvas — take a look before I start coding"
4. Waits for confirmation or adjustments

Not enforced — taught as best practice in the skill prompt. Skipped for small changes.

**Skill change:** SKILL.md gets a "When to sketch" section with heuristics.

### 2d. Canvas as Read-Write Medium

Claude doesn't just create — it continuously edits:
- **Renames nodes** when concepts evolve
- **Restructures edges** when dependencies change
- **Merges/splits nodes** during refactoring
- **Updates rendering hints** when diagrams no longer communicate well
- **Retires stale views** and creates new ones
- **Resolves its own comments** when fixing noted deviations

**Actor-aware merge logic:** Nodes/edges track who created them (`actor` field). Claude treats user-authored content with deference — raises comments rather than silently overwriting. User edits in the browser are respected and incorporated.

---

## 3. Node Model Extensions

### New Node Fields
- `fields[]` — Optional array of `{ name, type, description }` for data-model views. Renders as property list when `nodeContent` includes `"fields"`.
- `actor` — Who created this node (`"claude"` or `"user"`). Drives merge deference.

### New Edge Fields
- `order` — Numeric ordering for `edgeStyle: "ordered-arrows"`. Used in sequence-style views.
- `guard` — Optional condition label for state-machine transitions (e.g., "payment received"). Renders below the main label.

### New View Fields
- `rendering` — The hints object (Section 1). Replaces implicit "everything is a graph."
- `generatedFrom` — Free-text context about why this view was created. Helps Claude decide update vs. replace.
- `pinned` — Boolean. User can pin views. Claude won't retire pinned views.

### Event Schema
- `view.created` and `view.updated` data gains `rendering`, `generatedFrom`, `pinned` fields
- No new event types — everything fits existing `node.created/updated`, `edge.created/updated`, `view.created/updated`
- Fully backward compatible — old canvases still work, all new fields are optional

---

## 4. Visual Polish

### Design System
- **Depth-based color palette** — Each depth level gets a distinct desaturated hue. Nodes, borders, and text tint to depth color.
- **Node cards** — 280x90, centered text, label + subtitle, status badge, confidence dots, left depth bar. Rounded corners, subtle shadow on hover.
- **Edge rendering** — Smooth bezier curves, 20px label pills with border, properly sized arrow markers. Neutral default color, overridable per edge.
- **Spacing** — 40-60px between nodes. Canvas never feels cramped.
- **Dark and light themes** — Both fully designed with proper contrast.

### Interaction
- Smooth pan/zoom with momentum
- Node drag with snap-to-grid
- Selection highlights ancestry chain
- Animated transitions on view switch and status change
- Context menu for quick actions (change status, add comment, create edge)

### Known Bug Fixes
Addresses the 30 findings in `review-findings.md` and 12 UX gaps in `ux-gaps-v2.md`, including:
- F1: `$derived` arrow function fix
- F2: EventStore reactivity
- F3: Edges to collapsed nodes
- F4: CORS restriction to localhost
- G1-G10: Node colors, sizing, edge styling, tab consolidation, status badges

---

## 5. Implementation Sequencing (Vertical Slices)

### Slice 1: Visual Foundation + Canvas Read/Write
- Fix critical rendering bugs (F1-F4, G1-G2)
- Build design system (depth palette, node components, spacing)
- Upgrade hook context injection to structured JSON
- Claude reads canvas state before acting, respects decisions
- **Result:** Canvas looks good, Claude is canvas-aware

### Slice 2: Rendering Hints + Adaptive Views
- Add `rendering` hints to view model
- Build layout algorithms: grid (exists), lanes, layered
- Build node shape variants: card (exists), rounded, pill, minimal
- Claude picks rendering hints when generating/updating views
- **Result:** Different views look different based on what they're showing

### Slice 3: Proactive Maintenance + Design-First Sketching
- Claude auto-creates nodes for new files, records decisions, adds deviation comments
- Claude sketches architecture before non-trivial implementations
- Actor-aware merge logic (deference to user-authored content)
- View lifecycle (Claude creates, updates, retires views as codebase evolves)
- **Result:** Canvas stays alive without manual `/canvas update`

### Slice 4: Advanced Diagram Capabilities
- `fields` on nodes for data model views
- `order` and `guard` on edges for sequence/state diagrams
- Force-directed and radial layouts
- Annotations (freeform text/arrows)
- **Result:** Canvas handles the full range of diagram types
