# Code Canvas — Design Specification

A Claude Code plugin that provides a visual design knowledge graph for software architecture, prompt flows, data pipelines, and any system the user needs to think through visually.

## Core Identity

Code Canvas is a **design and architecture companion** — not a code viewer. Code is Claude's job. The canvas is where humans think visually about *what* to build and *how* it fits together, at whatever zoom level they need.

It maps **anything**: architecture diagrams, prompt flows, data pipelines, state machines, user journeys, deployment topologies. The node/edge model is generic and domain-agnostic.

---

## 1. Data Model

### 1.1 Event Store

All state is derived from an append-only event log stored at `.code-canvas/events.jsonl`. Each line is a self-contained JSON event.

**Event schema:**
```json
{
  "id": "ev_<ulid>",
  "ts": "2026-03-29T20:00:00Z",
  "type": "node.created",
  "actor": "claude|user|system",
  "data": { ... }
}
```

**Event types:**
- `node.created` — `{ nodeId, label, subtitle, parent, depth, category, confidence }`
- `node.updated` — `{ nodeId, changes: { label?, subtitle?, status?, confidence?, ... } }`
- `node.deleted` — `{ nodeId }`
- `edge.created` — `{ edgeId, from, to, label, edgeType, color }`
- `edge.updated` — `{ edgeId, changes: { label?, edgeType?, from?, to?, ... } }`
- `edge.deleted` — `{ edgeId }`
- `decision.recorded` — `{ nodeId, type: "decision"|"workaround", chosen, alternatives[], reason }`
- `comment.added` — `{ commentId, target, targetLabel, text, actor }`
- `comment.resolved` — `{ commentId, actor }`
- `comment.reopened` — `{ commentId, actor }`
- `comment.deleted` — `{ commentId }`
- `view.created` — `{ viewId, name, filter, description }`
- `view.updated` — `{ viewId, changes }`
- `layout.saved` — `{ viewId, positions: { nodeId: {x, y} } }`
- `node.status` — `{ nodeId, status, prev }`

**Derived state:** Current graph state is computed by replaying all events. Cached in `.code-canvas/state.json` for fast startup.

**Layouts:** Saved per-view in `.code-canvas/layouts/` as JSON files. User's drag positions persist across sessions.

### 1.2 Node Model

```
Node {
  id: string
  label: string
  subtitle: string
  parent: string | null       // parent node ID (for nesting)
  status: "done" | "in-progress" | "planned" | "placeholder"
  depth: "system" | "domain" | "module" | "interface" | string  // extensible
  category: string            // user-defined: "arch", "flow", "decision", etc.
  confidence: 0-3             // 0=unknown, 1=sketch, 2=partial, 3=fully specified
  expanded: boolean           // runtime state, not persisted in events
  hasWorkaround: boolean      // derived from decisions
  completeness: number        // 0-1, derived from children's statuses
}
```

**Visual representation by confidence:**
- **3 (solid):** Normal filled background, solid border
- **2 (partial):** Normal filled background, subtle dashed border
- **1 (sketch):** Normal filled background, pronounced dashed border
- **0 (placeholder):** Hatched fill pattern, dashed border, "click to flesh out" prompt

### 1.3 Edge Model

```
Edge {
  id: string
  from: string               // source node ID
  to: string                 // target node ID
  label: string
  edgeType: string           // "data-flow", "dependency", "triggers", "guards", etc.
  color: string              // hex color
}
```

### 1.4 View Model (Lenses)

Views are filtered/arranged projections of the same underlying graph. Each view:
- Has a name and optional description
- Defines a filter (which nodes/edges are visible)
- Has its own saved layout (node positions)
- Can be created by user or by Claude
- Supports custom grouping logic

```
View {
  id: string
  name: string
  description: string
  filter: {
    categories?: string[]    // show only these categories
    depths?: string[]        // show only these depth levels
    statuses?: string[]      // show only these statuses
    nodeIds?: string[]       // explicit inclusion list
    query?: string           // search query
  }
}
```

Default views: "All", plus any Claude/user generates (e.g., "Auth Flow", "Data Pipeline", "Deployment").

**View architecture is extensible** — the sidebar tabs are a view switcher, not hardcoded categories. Users can create arbitrary views for any concern: architecture, prompt flows, deployment topology, state machines, user journeys, or anything else. The system should support dozens of views without UX degradation (scrollable tab bar, search within views). Each view is a lens on the same underlying graph — adding a view never duplicates data.

---

## 2. Look & Feel

### 2.1 Theme

Dark and light mode with system-preference detection. Toggle in top bar.

**Dark theme:**
- Background: `#0f1117` with subtle dot grid
- Surfaces: `#161822` (panels), `#1e2235` (elevated)
- Borders: `#2d3148`
- Glass-morphism on sidebars (backdrop-blur + transparency)

**Light theme:**
- Background: `#f8fafc` with subtle dot grid
- Surfaces: `#ffffff`, `#f1f5f9`
- Borders: `#e2e8f0`

### 2.2 Layout

```
+------------------------------------------------------+
| TOP BAR: project name | views | filters | zoom/theme |
+------+------------------------------+---------------+
| LEFT | CANVAS (SVG)                 | RIGHT PANEL   |
| SIDE | - dot grid background        | - Details     |
| BAR  | - nodes (draggable)          | - Decisions   |
|      | - edges (editable)           | - History     |
| tree | - pan/zoom                   |               |
| view |                              |               |
+------+------------------------------+---------------+
| COMMENT BAR: unresolved comments, resolve/delete      |
+------------------------------------------------------+
| STATUS LINE: sync status | alerts | stats | port      |
+------------------------------------------------------+
```

Both sidebars are collapsible. Comment bar is collapsible.

### 2.3 Node Visuals

Each node is a rounded rectangle (210x74) with:
- **Depth glow ring:** Colored outer glow (blue=system, purple=domain, teal=module, orange=interface)
- **Title + subtitle:** Primary label and description
- **Status badge:** Top-right pill with status text and color
- **Confidence dots:** Bottom-right, 3 dots (filled=specified, empty=not)
- **Comment count badge:** Bottom-left circle with count (only if unresolved comments)
- **Completeness bar:** Bottom edge thin bar showing % of children specified (parent nodes only)
- **Expand chevron:** Left side, click to expand/collapse children
- **Workaround badge:** Orange border + warning icon when a workaround is active
- **Flesh-out prompt:** Italic text on placeholder (confidence=0) nodes inviting interaction

**Selection:** Dashed blue outline around selected nodes.

### 2.4 Parent-Child Visual Relationships

Parent-child hierarchy must be visually obvious on the canvas regardless of how nodes are positioned. Layout is free-form (users drag nodes anywhere), so hierarchy cannot rely on indentation or grid position.

**Four complementary mechanisms:**

**1. Containment (expanded parents):**
When a parent node is expanded, it renders as a **container** — a larger rounded rectangle that visually wraps its children. The parent's label becomes a header bar at the top of the container.

- Container background is a subtle tint of the parent's depth color (very low opacity: ~0.03-0.05)
- Container border matches the parent's depth glow color at reduced opacity
- Nesting depth creates progressively visible layering
- Containers are draggable as a group — moving the parent moves all children
- Children can be dragged within the container or pulled outside (reparenting gesture)

**2. Parent-child edges (always visible):**
Distinct from data-flow edges. Light dotted lines connecting parent to each child, using a muted color (e.g., `var(--border)` or parent's depth color at 30% opacity). These persist whether nodes are inside a container, scattered freely, or the parent is collapsed. Visually distinct from user-created data/flow edges (which are solid with arrows).

**3. Color banding (sibling affinity):**
Children inherit a subtle background tint from their parent's depth color. All children of "Canvas UI" share a faint teal-tinted node background, regardless of where they're placed on the canvas. This makes siblings visually cohesive even when scattered.

**4. Breadcrumb trail (on selection):**
When you select a node, the right panel shows its full ancestry path (e.g., `root → UI → Node Renderer`). On the canvas, all ancestors get a subtle highlight (brighter depth glow). Clicking any breadcrumb segment navigates to that ancestor. This answers "where am I in the hierarchy?" at any time.

**Collapsed preview:** When a parent is collapsed to a single node:
- Small badge showing child count (e.g., "4 children")
- Mini status dots inside the node — a row of tiny colored circles representing each child's status
- Parent-child edges still connect to the collapsed node (converging into it)

**Tree view connectors:** The sidebar tree uses vertical/horizontal connector lines (like VS Code's indentation guides). Lines are subtle and connect parent chevrons to child items. The tree is the only place where indentation-based hierarchy is appropriate (it's a tree, not a free-form canvas).

### 2.4 Edge Visuals

- Curved bezier paths between nodes
- Arrow markers at target end
- Labels on pill-shaped badges with theme background + subtle border (not colored blocks)
- **Edge ports:** Small circles on node edges where connections attach. Visible on hover.
- **Editable:** Click to select, drag midpoint to reroute, right-click for options

### 2.5 Interactions

**Node interactions:**
| Action | Gesture | Result |
|--------|---------|--------|
| Select | Click | Highlight + show hover card with summary |
| Open details | Double-click | Open right panel with full details |
| Multi-select | Shift+click | Add/remove from selection |
| Move | Drag | Move all selected nodes, save layout |
| Add comment | Right-click → Add Comment | Modal opens, comment saved |
| Change status | Right-click → status option | Event emitted |
| Expand/collapse | Click chevron | Toggle one level of children |
| Deep expand/collapse | Double-click chevron | Recursively expand/collapse all descendants |
| Flesh out | Click on placeholder node | Sends request to Claude |
| Context menu | Right-click | Full context menu |

**Edge interactions:**
| Action | Gesture | Result |
|--------|---------|--------|
| Create edge | Drag from node port to another node | New edge created |
| Select edge | Click on edge | Highlights, shows in panel |
| Edit route | Drag edge midpoint | Reroutes the bezier curve |
| Edit label | Double-click edge label | Inline edit |
| Delete/modify | Right-click edge | Context menu: delete, relabel, change type/direction |

**Canvas interactions:**
| Action | Gesture | Result |
|--------|---------|--------|
| Pan | Drag background | Move viewport |
| Zoom | Scroll wheel | Zoom in/out |
| Deselect | Click background | Clear selection |
| Search | Cmd+K | Focus search, filter tree + highlight canvas |

---

## 3. Behaviors

### 3.1 Generate

Claude creates a canvas from a plan, spec, or codebase analysis.

- Emits a stream of `node.created`, `edge.created`, and `decision.recorded` events
- Each node gets a **confidence level**: 3 for things Claude is certain about, 1-2 for partial understanding, 0 for acknowledged placeholders
- Claude proactively identifies which nodes need user input: "These 3 nodes need your input before I can design further"
- Generates default views based on the content (e.g., "Overview", "Data Flow")

### 3.2 Update

Canvas reflects implementation progress. **All updates are deterministic via hooks — no user action required.**

| Trigger | Detection | Canvas effect |
|---------|-----------|---------------|
| File write/edit | PostToolUse hook | Track changes, map to nodes |
| Task completed | TaskCompleted hook | Check node status, prompt update |
| Plan change | Spec file change detected | Canvas diff |
| Workaround | Claude says "X doesn't work, doing Y" | `decision.workaround` event, orange warning badge |
| Status change | Hook accumulation threshold | Node status auto-updated |

**Workaround capture is critical:** When implementation diverges from design, the canvas shows the drift with a warning badge. The user can intervene before it cascades.

**No silent changes:** If a node's implementation diverges from its design, the canvas visually flags the inconsistency.

### 3.3 Drill

User expands a node to see deeper detail.

- If children exist → they appear with saved layout
- If no children exist and confidence > 0 → Claude auto-generates children (inline, canvas live-updates)
- If no children and confidence = 0 → "Flesh out" prompt, starts conversation (inline for simple, redirect to terminal for complex)

### 3.4 Annotate

User or Claude adds feedback.

- **Comments:** Right-click → Add Comment. Saved to event store. Auto-injected to Claude context via FileChanged hook.
- **Resolution:** Both user (browser checkmark) and Claude (via skill) can resolve. Resolved comments leave Claude's context but stay in history.
- **Status changes:** Via context menu or panel dropdown. Event emitted.
- **Layout changes:** Drag positions saved per-view on mouseup.

### 3.5 Diff

Show what changed between two points in time.

- User selects "Changes since..." or switches to Diff view
- Event log filtered by time range
- Visual indicators: green glow = added, red = removed, yellow = modified
- Works because event store is time-indexed

### 3.6 Explore

Search, filter, navigate the graph.

- **Search:** Cmd+K, filters tree and highlights matching nodes on canvas (dims non-matching)
- **Filters:** Top bar toggles for depth, status, confidence, changes
- **Views:** Tab bar switches between saved views/lenses
- **Tree navigation:** Click tree item to focus canvas on that node

### 3.7 View Modes

The top bar switches between four view modes. Each renders the same underlying data differently.

**Canvas View (default):**
The main graph view described throughout this spec. Nodes, edges, containment, pan/zoom, drag.

**Timeline View:**
A vertical chronological view of all events, grouped by time period.
- Left column: timestamp + actor badge (user/claude/system with colored dot)
- Right column: event description with affected node name as a clickable link
- Events are collapsible by time group (Today, Yesterday, This Week, Older)
- Filter bar at top: filter by actor, event type, node
- Click any event to highlight the related node on the canvas (switches to Canvas view)
- Visual emphasis on decisions and workarounds (colored left border: green for decisions, orange for workarounds)
- "Jump to canvas" button on each event shows the graph state at that point in time

**Diff View:**
Shows what changed between two points in time.
- Top: date range picker (presets: "since last session", "since yesterday", "last 24h", "custom range")
- Canvas renders with diff overlays:
  - **Added nodes/edges:** Green glow + "NEW" badge
  - **Removed nodes/edges:** Red glow + strikethrough label + reduced opacity
  - **Modified nodes:** Yellow glow + change summary tooltip (e.g., "status: planned → done")
  - **Unchanged:** Normal rendering, slightly dimmed
- Left sidebar shows a structured diff list: "3 added, 2 modified, 1 removed"
- Click any diff entry to focus on that node
- "Accept all" / "Revert" actions (for changes Claude made that the user wants to undo)

**Story View:**
Narrated walkthrough of the project's decision history. Designed for onboarding or reflection.
- Presentation-style: one "slide" per major event/decision
- Navigation: forward/back arrows, timeline scrubber at bottom
- Each slide shows:
  - The graph state at that point in time (mini canvas, focused on relevant nodes)
  - A narrative text block: "On March 29, we decided to use JSONL for the event store because..."
  - The alternatives that were considered, with reasoning
  - Actor attribution
- Auto-play mode: advances every 5 seconds (configurable)
- "Exit to canvas" button returns to the full canvas at current state
- Claude can generate narration from the event log, or the user writes their own

### 3.8 Export

Export current state for sharing.

- Markdown document (for PRs, docs)
- PNG/SVG image (for presentations)
- Prompt (copy-pasteable summary for other contexts)

### 3.8 History Detail

The history panel is not a flat list — it's a rich, collapsible timeline:

- **Grouped by time period:** "Today", "Yesterday", "This week", "Older"
- **Grouped by actor:** Filter by user / claude / system
- **Expandable entries:** Each history item can expand to show full event data (the decision alternatives, the exact file that triggered a status change, the comment text that was resolved)
- **Linked entries:** Click a history item to highlight the related node/edge on canvas
- **Diff links:** "Show changes from this point" opens diff view from that event's timestamp
- **Collapsible sections:** Each group collapses independently. Default: today expanded, rest collapsed.

All history data comes from the event log — no separate storage needed.

### 3.9 Onboard (Story Mode)

When someone opens a canvas mid-project, Story mode narrates the decision history.

- Replays event log chronologically with narration
- "First we decided X, then Y changed because Z, now we're here"
- Useful for onboarding teammates or resuming after a break

---

## 4. Integration

### 3.10 Claude Context Accessibility

Claude needs access to canvas data at **different levels of detail at different times**. The canvas exposes a layered context API:

**Level 0 — Summary** (injected on session start, after compaction):
- Project title, node count, view names
- Status summary: "5 done, 3 in-progress, 4 planned"
- Unresolved comment count
- Active workaround alerts
- ~200 tokens

**Level 1 — Structure** (injected when entering plan mode or brainstorming):
- All nodes with labels, statuses, parent relationships, confidence
- Edge list with labels and types
- Unresolved comments with text
- ~500-1000 tokens depending on graph size

**Level 2 — Focused** (injected when working on a specific node):
- Full detail of the target node + its ancestors + its children
- All decisions and history for that subtree
- Related comments
- Connected edges
- ~300-500 tokens per subtree

**Level 3 — Full** (on explicit `/canvas comments` or `/canvas export prompt`):
- Everything: all nodes, edges, decisions, comments, history
- Only used when user explicitly requests it
- Could be large — warn if > 2000 tokens

Claude chooses the appropriate level based on context:
- Just starting a session? Level 0
- Planning architecture? Level 1
- Implementing "Auth Service"? Level 2 focused on auth subtree
- User asks "what decisions have we made"? Level 3

The hooks inject the appropriate level automatically. Claude can also request a specific level via the canvas skill.

### 3.11 Node Visibility

Nodes can be **hidden** without deleting them:
- Right-click → "Hide from view" removes the node from the current view's filter
- Hidden nodes appear grayed in the tree view with a "hidden" indicator
- "Show hidden" toggle in the sidebar reveals them as ghost nodes on canvas
- Hiding a parent optionally hides all children
- Hidden nodes still exist in the graph — they're just filtered from the current lens
- Different views can have different hidden sets

### 3.12 Context Menus Everywhere

Right-click context menus are available on **every interactive element**, not just canvas nodes:

**Tree view items:** Same options as canvas nodes (status, expand, hide, comment, flesh out, history)
**Right panel fields:** Copy value, edit, navigate to related node
**Comments:** Resolve, reopen, delete, navigate to target node, copy text
**Edges (canvas):** Delete, relabel, change type, change direction, reverse
**Edge labels (canvas):** Edit inline, copy
**View tabs:** Rename, duplicate, delete, set as default
**History items:** Show diff from this point, navigate to related node

This ensures every action is at most one right-click away, regardless of which panel the user is focused on.

### 4.1 Plugin Hooks

| Hook | Event | Behavior |
|------|-------|----------|
| SessionStart | startup, resume | Inject canvas state as context. Report changes since last session. |
| PreToolUse | EnterPlanMode | Open/suggest canvas |
| PostToolUse | Write, Edit | Track file changes, map to nodes |
| TaskCompleted | — | Update node statuses |
| PostCompact | — | Re-inject architecture summary |
| FileChanged | events.jsonl, comments | Sync browser ↔ Claude context |
| UserPromptSubmit | architecture keywords | Suggest canvas if none exists |

### 4.2 Plugin Ecosystem Integration

Canvas exposes an **event API** that other plugins can call:

- **Superpowers brainstorming** → generates canvas as side effect
- **Superpowers writing-plans** → plan steps map to canvas nodes
- **Superpowers executing-plans** → task completion updates nodes
- **Feature-dev** → architecture exploration feeds canvas
- **Commit-commands** → commits reference affected nodes
- **Code-review** → findings create comments on nodes

### 4.3 Autonomous Behavior

The canvas stays current without user commands. The **status line** is the passive notification channel:

| Event | Status line shows |
|-------|-------------------|
| Auto-update | `canvas: Server ✓ done` |
| Workaround | `⚠ Canvas: "Auth Service" — workaround recorded` |
| New comment | `canvas: 1 new comment on Layout Engine` |
| Nodes ready | `canvas: 3 nodes ready for detail` |
| Session start | `canvas: 12 changes since last session` |

### 4.4 CLI Commands

Commands are shortcuts, not requirements:

| Command | Action |
|---------|--------|
| `/canvas` | Open canvas (generate if none exists) |
| `/canvas generate` | Create from plan/spec/codebase |
| `/canvas update` | Sync with implementation |
| `/canvas diff [since]` | Open diff view |
| `/canvas story` | Open story mode |
| `/canvas export [md\|png\|prompt]` | Export current state |

Natural language also works: "show me the architecture", "mark server as done", etc.

---

## 5. Technical Architecture

### 5.1 Project Structure

```
code-canvas-plugin/
├── .claude-plugin/
│   └── plugin.json           # Plugin manifest
├── client/
│   ├── src/
│   │   ├── App.svelte        # Shell: topbar, layout, routing
│   │   ├── lib/
│   │   │   ├── state.js      # Event bus + derived state
│   │   │   ├── events.js     # Event store client (fetch/write API)
│   │   │   └── theme.js      # Theme management
│   │   ├── components/
│   │   │   ├── Canvas.svelte      # SVG canvas with pan/zoom
│   │   │   ├── Node.svelte        # Single node component
│   │   │   ├── Edge.svelte        # Bezier edge with ports
│   │   │   ├── EdgeCreator.svelte # Draw-new-edge interaction
│   │   │   ├── TreeView.svelte    # Left sidebar tree
│   │   │   ├── Panel.svelte       # Right detail panel
│   │   │   ├── Comments.svelte    # Bottom comment bar
│   │   │   ├── ContextMenu.svelte # Right-click menu
│   │   │   ├── StatusLine.svelte  # Bottom status bar
│   │   │   ├── SearchBar.svelte   # Cmd+K search
│   │   │   ├── ViewTabs.svelte    # View/lens switcher
│   │   │   └── HoverCard.svelte   # Quick node summary on click
│   │   └── views/
│   │       ├── CanvasView.svelte
│   │       ├── TimelineView.svelte
│   │       ├── DiffView.svelte
│   │       └── StoryView.svelte
│   ├── vite.config.js        # Builds to dist/
│   └── package.json
├── server/
│   └── index.js              # Static files + event API
├── hooks/
│   ├── hooks.json            # Hook definitions
│   └── *.sh                  # Hook scripts
├── skills/
│   └── canvas/
│       └── SKILL.md          # Skill definition
└── docs/
    └── design-spec.md        # This file
```

### 5.2 Server

Node.js server (localhost only, no TLS needed):
- Serves built Svelte app from `client/dist/`
- REST API for events, comments, layouts, views
- Path traversal protection on static file serving

**Multi-instance support:** Every project gets its own canvas server. No port collisions.

- **Port allocation:** On startup, server scans for a free port starting from 9100. No fixed range ceiling — if 9100-9199 are taken, it keeps scanning upward (9200, 9201, etc.). Falls back to OS auto-assign (port 0) as last resort.
- **Server registry:** Each running server writes its info to `.code-canvas/.server-info` (port, PID, project path, start time). The plugin reads this file to reconnect to an existing server rather than starting a duplicate.
- **Stale detection:** On startup, if `.server-info` exists, check if the PID is still alive and the port is responsive (`/health` endpoint). If stale, remove the file and start fresh.
- **Discovery:** The canvas skill first checks for `.server-info` before starting a server. If a server is already running for this project, it reuses it.
- **Isolation:** Each server only serves its own project's `.code-canvas/` data. No cross-project access.
- **Cleanup:** Servers write PID to `.server-info`. On SIGTERM/SIGINT, they clean up. The `stop-server.sh` script reads the PID and kills it. A `/canvas stop` command also works.

### 5.3 Storage

```
.code-canvas/
├── events.jsonl              # Immutable event log
├── state.json                # Computed current state (cache)
├── layouts/
│   ├── all.json              # Layout for "All" view
│   └── <view-id>.json        # Layout per custom view
└── .server-info              # Running server port/PID
```

### 5.4 Migration Path

JSONL → SQLite when query complexity demands it. Event schema stays the same. Migration is a single script: read lines, insert rows.

---

## 6. Visual Specification (Final UX Pass)

All sizing values for the Svelte build. These override any earlier prototype values.

### 6.1 Canvas Nodes (Leaf)
- **Size: 280w x 90h px** (minimum, can grow with content)
- **Border radius: 10px**
- **Title: 14px, font-weight 600**, color `var(--tx)`
- **Subtitle: hidden on node** — shown on hover (tooltip) and in right panel (progressive disclosure)
- **Status badge: 18h px pill**, 10px font, 9px border-radius, top-right with 10px inset
- **Confidence dots: 4px radius**, 10px center-to-center spacing, bottom-right
- **Color band: 5px wide** left edge bar, depth color at 60% opacity
- **Comment badge: 7px radius** circle, bottom-left
- **Workaround icon: 13px**, top-right (before status badge)
- **Collapsed child preview: 10px** "N children" text + 3.5px radius mini status dots

### 6.2 Containers (Expanded Parents)
- **Header height: 40px**
- **Header font: 14px bold**, depth color at 90% opacity
- **Internal padding: 32px** (all sides below header)
- **Child gap: 20px** between sibling nodes
- **Background: depth tint at 4% opacity** (8% when ancestor of selection)
- **Border: 1px depth color at 20% opacity** (2px at 50% when ancestor highlight)
- **Border radius: 14px**
- **Auto-resize: container bounds recalculate on child drag** (elastic, with 32px padding maintained)

### 6.3 Edges
- **Stroke width: 2px**
- **Opacity: 0.65** (was .55 — more visible)
- **Arrow markers: 10x7px**
- **Label pills: 20px height, 10px border-radius**, `var(--bg-s)` fill, `var(--bdr)` 1px border, 11px font

### 6.4 Topbar
- **Height: 44px**
- **Project name: 14px bold**
- **View tab buttons: 12px, padding 7px 16px**
- **Tool buttons: 32px height, 10px horizontal padding**

### 6.5 Left Sidebar
- **Width: 260px**
- **Search input: padding 9px 12px, 12px font**
- **Tree items: min-height 32px, padding 6px 12px, 12px font**
- **Depth badges: 10px font**
- **View tabs: 11px font, 4px 8px padding**

### 6.6 Right Panel
- **Width: 300px**
- **Panel title: 14px bold**
- **Section titles: 10px uppercase, 0.06em letter-spacing**
- **Field labels/values: 12px**
- **Breadcrumb: 11px, padding 3px 6px per segment**
- **Decision cards: 12px chosen, 11px alternatives/reason, 10px padding, 6px border-radius**

### 6.7 Comment Bar
- **Max height: 130px (expandable)**
- **Comment rows: 12px font, 5px vertical padding**
- **Actor badges: 10px font, 4px padding**
- **Target labels: 12px bold, accent color**

### 6.8 Status Line
- **Height: 22px** (unobtrusive)
- **Font: 10px**

### 6.9 Typography Hierarchy
| Element | Size | Weight | Usage |
|---------|------|--------|-------|
| Node title | 14px | 600 | Primary label on canvas |
| Container header | 14px | 700 | Parent label in container |
| Panel title | 14px | 600 | Selected node name |
| Panel body | 12px | 400 | Properties, connections |
| Status badge | 10px | 600 | Status pills on nodes |
| Section header | 10px | 500 | Panel section labels |
| Tree item | 12px | 400/500 | Sidebar tree (500 when selected) |
| Edge label | 11px | 500 | Connection labels |
| Hint/meta | 10px | 400 | Status line, tooltips |
| Minimum anywhere | 10px | — | Nothing smaller than 10px |

### 6.10 Spacing System
| Context | Value |
|---------|-------|
| Between sibling nodes (in container) | 20px |
| Container internal padding | 32px |
| Container header height | 40px |
| Between top-level nodes | 40px |
| Panel section margin | 14px |
| Panel internal padding | 14px |
| Tree item min-height | 32px |
| Search input padding | 9px 12px |

## 7. Design Prototype

Interactive prototype at `/Users/mark/Developer/code-canvas-v2.html` demonstrates:
- Dark + light theme toggle
- Node confidence indicators (solid/hatched/dashed)
- Workaround warning badges
- Comment resolution with actor badges
- Status line mockup
- Collapsible panels
- Search + filter
- Context menus
- Drag + pan + zoom
