# Rendering Hints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a composable rendering hints system to views so the same node/edge data can render as different diagram types (architecture cards, UML use cases, state machines, etc.)

**Architecture:** Views gain a `rendering` object with hint properties (`nodeShape`, `edgeStyle`, `layout`, etc.). The Canvas dispatches to shape-specific Svelte components based on the active view's hints. Layout algorithms are selected by the `layout` hint. All hints have sensible defaults so existing canvases render unchanged.

**Tech Stack:** Svelte 5, SVG, existing event-sourced data model

---

### Task 1: Add rendering field to view model

**Files:**
- Modify: `client/src/lib/events.js:149-161` (view.created handler)
- Modify: `server/index.js:82` (view.created replay)
- Test: `client/src/lib/events.test.js`

- [ ] **Step 1: Write the failing test**

In `client/src/lib/events.test.js`, add:

```javascript
test('view.created stores rendering hints', () => {
  const store = new EventStore();
  store.apply({
    type: 'view.created',
    data: {
      viewId: 'v1', name: 'Test',
      tabNodes: [], tabConnections: [],
      rendering: { nodeShape: 'ellipse', layout: 'grid' },
    },
  });
  const state = store.getState();
  expect(state.views[0].rendering).toEqual({ nodeShape: 'ellipse', layout: 'grid' });
});

test('view.created defaults rendering to empty object', () => {
  const store = new EventStore();
  store.apply({
    type: 'view.created',
    data: { viewId: 'v1', name: 'Test', tabNodes: [], tabConnections: [] },
  });
  const state = store.getState();
  expect(state.views[0].rendering).toEqual({});
});

test('view.updated can change rendering hints', () => {
  const store = new EventStore();
  store.apply({
    type: 'view.created',
    data: { viewId: 'v1', name: 'Test', tabNodes: [], tabConnections: [] },
  });
  store.apply({
    type: 'view.updated',
    data: { viewId: 'v1', changes: { rendering: { nodeShape: 'rounded' } } },
  });
  const state = store.getState();
  expect(state.views[0].rendering).toEqual({ nodeShape: 'rounded' });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run client/src/lib/events.test.js --reporter=verbose`
Expected: FAIL — `rendering` is `undefined`

- [ ] **Step 3: Add rendering field to view.created handler in events.js**

In `client/src/lib/events.js`, in the `view.created` case (around line 149), add `rendering`:

```javascript
      case 'view.created':
        this._views.push({
          id: d.viewId,
          name: d.name,
          story: d.story || '',
          description: d.description || '',
          rendering: d.rendering || {},
          tabNodes: d.tabNodes || [],
          tabConnections: d.tabConnections || [],
          filter: d.filter || null,
        });
        break;
```

- [ ] **Step 4: Add rendering field to server replay**

In `server/index.js`, update the `view.created` case (line 82):

```javascript
      case 'view.created': views.push({ id: d.viewId, name: d.name, description: d.description || '', rendering: d.rendering || {}, tabNodes: d.tabNodes || [], tabConnections: d.tabConnections || [] }); break;
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `npx vitest run client/src/lib/events.test.js --reporter=verbose`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add client/src/lib/events.js client/src/lib/events.test.js server/index.js
git commit -m "feat: add rendering hints field to view model"
```

---

### Task 2: Create rendering defaults helper

**Files:**
- Create: `client/src/lib/rendering.js`
- Test: `client/src/lib/rendering.test.js`

- [ ] **Step 1: Write the failing test**

Create `client/src/lib/rendering.test.js`:

```javascript
import { describe, test, expect } from 'vitest';
import { resolveHints, DEFAULTS } from './rendering.js';

describe('resolveHints', () => {
  test('returns all defaults when no hints provided', () => {
    const hints = resolveHints({});
    expect(hints.nodeShape).toBe('card');
    expect(hints.edgeStyle).toBe('curve');
    expect(hints.layout).toBe('grid');
    expect(hints.nodeSize).toBe('standard');
    expect(hints.edgeLabels).toBe('pill');
    expect(hints.nodeContent).toEqual(['label', 'subtitle']);
  });

  test('overrides specific hints', () => {
    const hints = resolveHints({ nodeShape: 'ellipse', layout: 'horizontal-lanes' });
    expect(hints.nodeShape).toBe('ellipse');
    expect(hints.layout).toBe('horizontal-lanes');
    expect(hints.edgeStyle).toBe('curve'); // default preserved
  });

  test('returns undefined hints as undefined (passthrough)', () => {
    const hints = resolveHints({ nodeShape: 'ellipse' });
    expect(hints.groupBy).toBeUndefined();
    expect(hints.ordering).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run client/src/lib/rendering.test.js --reporter=verbose`
Expected: FAIL — module not found

- [ ] **Step 3: Create rendering.js**

Create `client/src/lib/rendering.js`:

```javascript
/**
 * Rendering hints — composable visual properties for views.
 * Claude picks hints when creating views; the renderer reads them.
 * All hints have sensible defaults so existing views render unchanged.
 */

export const DEFAULTS = {
  layout: 'grid',
  nodeShape: 'card',
  nodeSize: 'standard',
  nodeContent: ['label', 'subtitle'],
  edgeStyle: 'curve',
  edgeLabels: 'pill',
};

/**
 * Merge view-level hints with defaults.
 * Only properties in DEFAULTS get defaulted — unknown hints pass through.
 */
export function resolveHints(rendering = {}) {
  return {
    ...DEFAULTS,
    ...rendering,
  };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run client/src/lib/rendering.test.js --reporter=verbose`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add client/src/lib/rendering.js client/src/lib/rendering.test.js
git commit -m "feat: rendering hints defaults and resolver"
```

---

### Task 3: Create NodeEllipse shape component

**Files:**
- Create: `client/src/components/NodeEllipse.svelte`

This is the UML use case oval. Same props as NodeLeaf but renders as a horizontal ellipse with centered text.

- [ ] **Step 1: Create NodeEllipse.svelte**

Create `client/src/components/NodeEllipse.svelte`:

```svelte
<script>
  /**
   * Ellipse node — UML use case style.
   * Horizontal oval with centered label. Subtitle shown below label in smaller text.
   * Same props interface as NodeLeaf for drop-in switching.
   */
  import { depthColor, statusColor, DEPTH_BG_COLORS, DEPTH_TEXT_COLORS } from '../lib/config.js';

  let {
    node,
    tabNode,
    pos,
    isSelected = false,
    comments = [],
    onselect,
    onstartdrag,
    oncontextmenu,
  } = $props();

  const dc = $derived(depthColor(node.depth));
  const sc = $derived(statusColor(node.status));
  const bgColor = $derived(tabNode?.color || node.color || DEPTH_BG_COLORS[node.depth] || '#1e293b');
  const txtColor = $derived(tabNode?.textColor || node.textColor || DEPTH_TEXT_COLORS[node.depth] || '#94a3b8');

  // Ellipse geometry
  const cx = $derived(pos.x + pos.w / 2);
  const cy = $derived(pos.y + pos.h / 2);
  const rx = $derived(pos.w / 2);
  const ry = $derived(pos.h / 2);
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<g
  data-node={node.id}
  style="cursor: grab"
  onmousedown={(e) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    onselect?.(node.id, e);
    onstartdrag?.(node.id, e);
  }}
  oncontextmenu={(e) => {
    e.preventDefault();
    e.stopPropagation();
    oncontextmenu?.(node.id, e);
  }}
>
  <!-- Selection outline -->
  {#if isSelected}
    <ellipse
      cx={cx} cy={cy} rx={rx + 4} ry={ry + 4}
      fill="none" stroke="#c8d8f0" stroke-width="3"
    />
  {/if}

  <!-- Ellipse background -->
  <ellipse
    cx={cx} cy={cy} rx={rx} ry={ry}
    fill={bgColor} stroke={dc} stroke-width="1.5"
  />

  <!-- Label (centered) -->
  <text
    x={cx} y={node.subtitle ? cy - 4 : cy + 5}
    text-anchor="middle" fill={txtColor}
    font-size="13" font-weight="600"
  >{node.label}</text>

  <!-- Subtitle (centered, below label) -->
  {#if node.subtitle}
    {@const maxChars = Math.floor((pos.w - 40) / 6.5)}
    <text
      x={cx} y={cy + 14}
      text-anchor="middle" fill={txtColor}
      font-size="10" opacity=".7"
    >{node.subtitle.length > maxChars ? node.subtitle.slice(0, maxChars - 2) + '...' : node.subtitle}</text>
  {/if}

  <!-- Status dot (top right of ellipse) -->
  <circle cx={cx + rx - 12} cy={cy - ry + 12} r="5" fill={sc} />

  <!-- Comment badge -->
  {#if comments.length > 0}
    <circle cx={cx - rx + 12} cy={cy + ry - 12} r="7" fill="#3b82f6" opacity=".9" />
    <text
      x={cx - rx + 12} y={cy + ry - 8}
      text-anchor="middle" fill="white" font-size="10" font-weight="600"
    >{comments.length}</text>
  {/if}
</g>
```

- [ ] **Step 2: Visually verify in browser (manual)**

This will be wired up in Task 5. Skip for now.

- [ ] **Step 3: Commit**

```bash
git add client/src/components/NodeEllipse.svelte
git commit -m "feat: NodeEllipse component for UML use case diagrams"
```

---

### Task 4: Create NodeActor shape component

**Files:**
- Create: `client/src/components/NodeActor.svelte`

UML stick figure actor. Same props as NodeLeaf.

- [ ] **Step 1: Create NodeActor.svelte**

Create `client/src/components/NodeActor.svelte`:

```svelte
<script>
  /**
   * Actor node — UML stick figure style.
   * Stick figure icon with label below. Used for actors in use case diagrams.
   * Same props interface as NodeLeaf for drop-in switching.
   */
  import { depthColor, DEPTH_TEXT_COLORS } from '../lib/config.js';

  let {
    node,
    tabNode,
    pos,
    isSelected = false,
    comments = [],
    onselect,
    onstartdrag,
    oncontextmenu,
  } = $props();

  const dc = $derived(depthColor(node.depth));
  const txtColor = $derived(tabNode?.textColor || node.textColor || DEPTH_TEXT_COLORS[node.depth] || '#94a3b8');

  // Center of the node area
  const cx = $derived(pos.x + pos.w / 2);
  // Stick figure sits in upper portion, label below
  const figureY = $derived(pos.y + 12);
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<g
  data-node={node.id}
  style="cursor: grab"
  onmousedown={(e) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    onselect?.(node.id, e);
    onstartdrag?.(node.id, e);
  }}
  oncontextmenu={(e) => {
    e.preventDefault();
    e.stopPropagation();
    oncontextmenu?.(node.id, e);
  }}
>
  <!-- Selection highlight -->
  {#if isSelected}
    <rect
      x={pos.x - 3} y={pos.y - 3}
      width={pos.w + 6} height={pos.h + 6}
      rx="8" fill="none" stroke="#c8d8f0" stroke-width="3"
    />
  {/if}

  <!-- Stick figure -->
  <!-- Head -->
  <circle cx={cx} cy={figureY + 10} r="8" fill="none" stroke={dc} stroke-width="2" />
  <!-- Body -->
  <line x1={cx} y1={figureY + 18} x2={cx} y2={figureY + 38} stroke={dc} stroke-width="2" />
  <!-- Arms -->
  <line x1={cx - 14} y1={figureY + 26} x2={cx + 14} y2={figureY + 26} stroke={dc} stroke-width="2" />
  <!-- Left leg -->
  <line x1={cx} y1={figureY + 38} x2={cx - 10} y2={figureY + 52} stroke={dc} stroke-width="2" />
  <!-- Right leg -->
  <line x1={cx} y1={figureY + 38} x2={cx + 10} y2={figureY + 52} stroke={dc} stroke-width="2" />

  <!-- Label (centered below figure) -->
  <text
    x={cx} y={pos.y + pos.h - 4}
    text-anchor="middle" fill={txtColor}
    font-size="12" font-weight="600"
  >{node.label}</text>

  <!-- Comment badge -->
  {#if comments.length > 0}
    <circle cx={pos.x + pos.w - 10} cy={pos.y + 10} r="7" fill="#3b82f6" opacity=".9" />
    <text
      x={pos.x + pos.w - 10} y={pos.y + 14}
      text-anchor="middle" fill="white" font-size="10" font-weight="600"
    >{comments.length}</text>
  {/if}
</g>
```

- [ ] **Step 2: Commit**

```bash
git add client/src/components/NodeActor.svelte
git commit -m "feat: NodeActor component for UML stick figures"
```

---

### Task 5: Wire rendering hints into App.svelte node dispatch

**Files:**
- Modify: `client/src/App.svelte`

This is the key integration point. App.svelte reads the active view's rendering hints and passes the `nodeShape` to determine which component renders each node.

- [ ] **Step 1: Add imports and hint resolution to App.svelte**

At the top of `<script>` in `App.svelte`, add these imports (after the existing imports around line 17):

```javascript
  import NodeEllipse from './components/NodeEllipse.svelte';
  import NodeActor from './components/NodeActor.svelte';
  import { resolveHints } from './lib/rendering.js';
```

After the `activeTab` derived (around line 50), add:

```javascript
  // Resolve rendering hints for active view
  const hints = $derived(resolveHints(activeTab?.rendering));
```

- [ ] **Step 2: Add node shape dispatch logic**

After the `hints` derived, add a shape-to-component map:

```javascript
  // Map nodeShape hint → component
  const SHAPE_COMPONENTS = {
    card: NodeLeaf,
    ellipse: NodeEllipse,
    actor: NodeActor,
  };
```

- [ ] **Step 3: Update node rendering to use shape dispatch**

In `App.svelte`, replace the node rendering block (around lines 395-411):

```svelte
        <!-- Nodes -->
        {#each tabNodes as tabNode}
          {@const nodeId = tabNode.nodeId || tabNode.id}
          {@const node = getNodeWithOverrides(tabNode)}
          {@const pos = activePositions.get(nodeId)}
          {#if node && pos}
            {@const shape = tabNode.shape || (node.category === 'actor' ? 'actor' : hints.nodeShape)}
            {@const NodeComponent = SHAPE_COMPONENTS[shape] || NodeLeaf}
            <svelte:component this={NodeComponent}
              {node}
              {tabNode}
              {pos}
              isSelected={appState.selectedIds.has(nodeId)}
              comments={graphState.comments.filter(c => c.target === nodeId && !c.resolved)}
              onselect={selectNode}
              onstartdrag={startDrag}
              oncontextmenu={handleContextMenu}
            />
          {/if}
        {/each}
```

Note the shape resolution order:
1. `tabNode.shape` — per-node override (a node can be an actor on a use-case tab)
2. `node.category === 'actor'` — auto-detect actor nodes
3. `hints.nodeShape` — view-level default from rendering hints

- [ ] **Step 4: Rebuild and test visually**

```bash
cd client && npx vite build
```

Restart server, open canvas, verify:
- Existing tabs render unchanged (nodeShape defaults to `card`)
- Use Case Diagrams tab shows cards (no rendering hints set yet)

- [ ] **Step 5: Commit**

```bash
git add client/src/App.svelte
git commit -m "feat: wire rendering hints into node shape dispatch"
```

---

### Task 6: Set rendering hints on Use Case Diagrams tab and auto-detect actors

**Files:**
- No code changes — this is an API call to update the existing view

- [ ] **Step 1: Update the Use Case Diagrams view with rendering hints**

```bash
curl -s -X POST http://localhost:9105/api/events \
  -H 'Content-Type: application/json' \
  -d '{
    "type": "view.updated",
    "actor": "claude",
    "data": {
      "viewId": "tab-1774918688486",
      "changes": {
        "rendering": {
          "nodeShape": "ellipse",
          "edgeLabels": "pill",
          "layout": "grid"
        }
      }
    }
  }'
```

- [ ] **Step 2: Verify in browser**

Refresh the canvas and switch to Use Case Diagrams tab.

Expected:
- `n_uc_developer` and `n_uc_claude` render as stick figures (auto-detected via `category: "actor"`)
- All other nodes render as ellipses (view-level `nodeShape: "ellipse"`)
- Edges render as curves with label pills (unchanged)

- [ ] **Step 3: Manual visual QA**

Check:
- Stick figures are proportional and readable
- Ellipses fit their text
- Selection outline works on both shapes
- Context menu works on both shapes
- Edge connections clip properly to ellipse borders

---

### Task 7: Update edge clipping for ellipse nodes

**Files:**
- Modify: `client/src/lib/layout.js:65-73`
- Test: `client/src/lib/layout.test.js`

The existing `clipAtBorder` function clips to a rectangle. Ellipse nodes need ellipse clipping for edges to look right.

- [ ] **Step 1: Write the failing test**

In `client/src/lib/layout.test.js`, add:

```javascript
import { clipAtEllipse } from './layout.js';

describe('clipAtEllipse', () => {
  test('clips horizontal ray to ellipse edge', () => {
    const p = clipAtEllipse(100, 100, 200, 100, 50, 30);
    expect(p.x).toBeCloseTo(150);
    expect(p.y).toBeCloseTo(100);
  });

  test('clips vertical ray to ellipse edge', () => {
    const p = clipAtEllipse(100, 100, 100, 200, 50, 30);
    expect(p.x).toBeCloseTo(100);
    expect(p.y).toBeCloseTo(130);
  });

  test('clips diagonal ray to ellipse edge', () => {
    const p = clipAtEllipse(100, 100, 200, 200, 50, 30);
    // Should be on the ellipse boundary
    const dx = (p.x - 100) / 50;
    const dy = (p.y - 100) / 30;
    expect(dx * dx + dy * dy).toBeCloseTo(1, 1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run client/src/lib/layout.test.js --reporter=verbose`
Expected: FAIL — `clipAtEllipse` not found

- [ ] **Step 3: Implement clipAtEllipse**

In `client/src/lib/layout.js`, add after `clipAtBorder`:

```javascript
/**
 * Clip a line from center toward target at ellipse border.
 * cx, cy = ellipse center, tx, ty = target point, rx, ry = radii.
 */
export function clipAtEllipse(cx, cy, tx, ty, rx, ry) {
  const dx = tx - cx;
  const dy = ty - cy;
  if (dx === 0 && dy === 0) return { x: cx, y: cy };
  const angle = Math.atan2(dy, dx);
  return {
    x: cx + rx * Math.cos(angle),
    y: cy + ry * Math.sin(angle),
  };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run client/src/lib/layout.test.js --reporter=verbose`
Expected: All PASS

- [ ] **Step 5: Use clipAtEllipse in computeEdgePath when nodes are ellipses**

In `client/src/lib/layout.js`, update `computeEdgePath` to accept an optional `shapes` parameter:

```javascript
/**
 * Compute bezier edge path between two nodes.
 * @param {Object} fromPos - {x, y, w, h}
 * @param {Object} toPos - {x, y, w, h}
 * @param {Object} [options] - { fromShape: 'card'|'ellipse', toShape: 'card'|'ellipse' }
 */
export function computeEdgePath(fromPos, toPos, options = {}) {
  const fcx = fromPos.x + fromPos.w / 2;
  const fcy = fromPos.y + fromPos.h / 2;
  const tcx = toPos.x + toPos.w / 2;
  const tcy = toPos.y + toPos.h / 2;

  const clipFrom = options.fromShape === 'ellipse' ? clipAtEllipse : clipAtBorder;
  const clipTo = options.toShape === 'ellipse' ? clipAtEllipse : clipAtBorder;

  const start = clipFrom(fcx, fcy, tcx, tcy, fromPos.w / 2, fromPos.h / 2);
  const end = clipTo(tcx, tcy, fcx, fcy, toPos.w / 2 + 6, toPos.h / 2 + 6);

  const mx = (start.x + end.x) / 2;
  const my = (start.y + end.y) / 2;

  const bf = Math.abs(end.y - start.y) > Math.abs(end.x - start.x) ? 0.25 : 0.2;
  const px = -(end.y - start.y) * bf;
  const py = (end.x - start.x) * bf;

  const path = `M${start.x},${start.y} Q${mx + px},${my + py} ${end.x},${end.y}`;
  const labelX = mx + px * 0.6;
  const labelY = my + py * 0.6;

  return { path, labelX, labelY };
}
```

- [ ] **Step 6: Pass shape info to EdgeLine from App.svelte**

In `App.svelte`, update the edge rendering block (around line 382) to pass shape options:

```svelte
        {#each tabConnections as conn}
          {@const fromId = conn.from}
          {@const toId = conn.to}
          {#if activePositions.has(fromId) && activePositions.has(toId)}
            {@const fromNode = graphState.nodes.get(fromId)}
            {@const toNode = graphState.nodes.get(toId)}
            {@const fromShape = fromNode?.category === 'actor' ? 'actor' : hints.nodeShape}
            {@const toShape = toNode?.category === 'actor' ? 'actor' : hints.nodeShape}
            <EdgeLine
              edge={{ id: fromId + '-' + toId, ...conn }}
              fromPos={activePositions.get(fromId)}
              toPos={activePositions.get(toId)}
              shapes={{ fromShape: fromShape === 'actor' ? 'card' : fromShape, toShape: toShape === 'actor' ? 'card' : toShape }}
            />
          {/if}
        {/each}
```

Update `EdgeLine.svelte` to accept and pass the shapes:

```svelte
<script>
  import { computeEdgePath } from '../lib/layout.js';

  let { edge, fromPos, toPos, shapes = {} } = $props();

  const color = $derived(edge.color || '#64748b');
  const edgePath = $derived(computeEdgePath(fromPos, toPos, shapes));
  const labelW = $derived(edge.label ? edge.label.length * 7.5 + 24 : 0);
</script>
```

- [ ] **Step 7: Rebuild and verify edges clip to ellipses**

```bash
cd client && npx vite build
```

Restart server, check Use Case Diagrams tab — edges should connect smoothly to ellipse borders, not to invisible rectangle corners.

- [ ] **Step 8: Commit**

```bash
git add client/src/lib/layout.js client/src/lib/layout.test.js client/src/App.svelte client/src/components/EdgeLine.svelte
git commit -m "feat: ellipse edge clipping for non-rectangular node shapes"
```

---

### Task 8: Create NodeRounded shape component

**Files:**
- Create: `client/src/components/NodeRounded.svelte`
- Modify: `client/src/App.svelte` (add to SHAPE_COMPONENTS)

Rounded rectangle for state machine diagrams. More rounded than card (rx=20), no depth bar, status shown as fill tint.

- [ ] **Step 1: Create NodeRounded.svelte**

Create `client/src/components/NodeRounded.svelte`:

```svelte
<script>
  /**
   * Rounded node — state machine style.
   * Heavily rounded rectangle, centered label, status as fill tint.
   * Same props interface as NodeLeaf.
   */
  import { depthColor, statusColor, DEPTH_BG_COLORS, DEPTH_TEXT_COLORS } from '../lib/config.js';

  let {
    node,
    tabNode,
    pos,
    isSelected = false,
    comments = [],
    onselect,
    onstartdrag,
    oncontextmenu,
  } = $props();

  const dc = $derived(depthColor(node.depth));
  const sc = $derived(statusColor(node.status));
  const bgColor = $derived(tabNode?.color || node.color || DEPTH_BG_COLORS[node.depth] || '#1e293b');
  const txtColor = $derived(tabNode?.textColor || node.textColor || DEPTH_TEXT_COLORS[node.depth] || '#94a3b8');

  const cx = $derived(pos.x + pos.w / 2);
  const cy = $derived(pos.y + pos.h / 2);
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<g
  data-node={node.id}
  style="cursor: grab"
  onmousedown={(e) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    onselect?.(node.id, e);
    onstartdrag?.(node.id, e);
  }}
  oncontextmenu={(e) => {
    e.preventDefault();
    e.stopPropagation();
    oncontextmenu?.(node.id, e);
  }}
>
  {#if isSelected}
    <rect
      x={pos.x - 3} y={pos.y - 3}
      width={pos.w + 6} height={pos.h + 6}
      rx="23" fill="none" stroke="#c8d8f0" stroke-width="3"
    />
  {/if}

  <rect
    x={pos.x} y={pos.y}
    width={pos.w} height={pos.h}
    rx="20" fill={bgColor}
    stroke={dc} stroke-width="1.5"
  />

  <!-- Label -->
  <text
    x={cx} y={node.subtitle ? cy - 2 : cy + 5}
    text-anchor="middle" fill={txtColor}
    font-size="13" font-weight="600"
  >{node.label}</text>

  {#if node.subtitle}
    <text
      x={cx} y={cy + 14}
      text-anchor="middle" fill={txtColor}
      font-size="10" opacity=".7"
    >{node.subtitle}</text>
  {/if}

  <!-- Status dot -->
  <circle cx={pos.x + pos.w - 14} cy={pos.y + 14} r="5" fill={sc} />

  {#if comments.length > 0}
    <circle cx={pos.x + 14} cy={pos.y + pos.h - 14} r="7" fill="#3b82f6" opacity=".9" />
    <text
      x={pos.x + 14} y={pos.y + pos.h - 10}
      text-anchor="middle" fill="white" font-size="10" font-weight="600"
    >{comments.length}</text>
  {/if}
</g>
```

- [ ] **Step 2: Register in App.svelte**

Add import:

```javascript
  import NodeRounded from './components/NodeRounded.svelte';
```

Add to `SHAPE_COMPONENTS`:

```javascript
  const SHAPE_COMPONENTS = {
    card: NodeLeaf,
    ellipse: NodeEllipse,
    actor: NodeActor,
    rounded: NodeRounded,
  };
```

- [ ] **Step 3: Rebuild, commit**

```bash
cd client && npx vite build
git add client/src/components/NodeRounded.svelte client/src/App.svelte
git commit -m "feat: NodeRounded component for state machine diagrams"
```

---

### Task 9: Add NodePill shape component

**Files:**
- Create: `client/src/components/NodePill.svelte`
- Modify: `client/src/App.svelte` (add to SHAPE_COMPONENTS)

Pill shape — fully rounded ends, compact. For sequence diagram participants and minimal labels.

- [ ] **Step 1: Create NodePill.svelte**

Create `client/src/components/NodePill.svelte`:

```svelte
<script>
  /**
   * Pill node — fully rounded ends, compact label.
   * For sequence diagram participants, tags, minimal labels.
   * Same props interface as NodeLeaf.
   */
  import { depthColor, DEPTH_BG_COLORS, DEPTH_TEXT_COLORS } from '../lib/config.js';

  let {
    node,
    tabNode,
    pos,
    isSelected = false,
    comments = [],
    onselect,
    onstartdrag,
    oncontextmenu,
  } = $props();

  const dc = $derived(depthColor(node.depth));
  const bgColor = $derived(tabNode?.color || node.color || DEPTH_BG_COLORS[node.depth] || '#1e293b');
  const txtColor = $derived(tabNode?.textColor || node.textColor || DEPTH_TEXT_COLORS[node.depth] || '#94a3b8');
  const ry = $derived(pos.h / 2);
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<g
  data-node={node.id}
  style="cursor: grab"
  onmousedown={(e) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    onselect?.(node.id, e);
    onstartdrag?.(node.id, e);
  }}
  oncontextmenu={(e) => {
    e.preventDefault();
    e.stopPropagation();
    oncontextmenu?.(node.id, e);
  }}
>
  {#if isSelected}
    <rect
      x={pos.x - 3} y={pos.y - 3}
      width={pos.w + 6} height={pos.h + 6}
      rx={ry + 3} fill="none" stroke="#c8d8f0" stroke-width="3"
    />
  {/if}

  <rect
    x={pos.x} y={pos.y}
    width={pos.w} height={pos.h}
    rx={ry} fill={bgColor}
    stroke={dc} stroke-width="1.5"
  />

  <text
    x={pos.x + pos.w / 2} y={pos.y + pos.h / 2 + 5}
    text-anchor="middle" fill={txtColor}
    font-size="13" font-weight="600"
  >{node.label}</text>

  {#if comments.length > 0}
    <circle cx={pos.x + pos.w - 8} cy={pos.y + 8} r="6" fill="#3b82f6" opacity=".9" />
    <text
      x={pos.x + pos.w - 8} y={pos.y + 12}
      text-anchor="middle" fill="white" font-size="9" font-weight="600"
    >{comments.length}</text>
  {/if}
</g>
```

- [ ] **Step 2: Register in App.svelte**

Add import:

```javascript
  import NodePill from './components/NodePill.svelte';
```

Add to `SHAPE_COMPONENTS`:

```javascript
  const SHAPE_COMPONENTS = {
    card: NodeLeaf,
    ellipse: NodeEllipse,
    actor: NodeActor,
    rounded: NodeRounded,
    pill: NodePill,
  };
```

- [ ] **Step 3: Rebuild, commit**

```bash
cd client && npx vite build
git add client/src/components/NodePill.svelte client/src/App.svelte
git commit -m "feat: NodePill component for sequence diagrams and minimal labels"
```

---

### Task 10: Update SKILL.md with rendering hints documentation

**Files:**
- Modify: `skills/canvas/SKILL.md`

- [ ] **Step 1: Add rendering hints section to SKILL.md**

Add after the "Node Model" section in `skills/canvas/SKILL.md`:

```markdown
## Rendering Hints

Views can carry a `rendering` object with composable hints that control how nodes and edges are drawn. Claude picks hints based on what the diagram is trying to communicate.

### Available Hints

| Hint | Values | Default | Purpose |
|------|--------|---------|---------|
| `nodeShape` | `card`, `ellipse`, `rounded`, `pill`, `actor` | `card` | How nodes are drawn |
| `nodeSize` | `compact`, `standard`, `expanded` | `standard` | Node dimensions |
| `nodeContent` | Array: `label`, `subtitle`, `fields`, `status-badge` | `["label", "subtitle"]` | What to show on nodes |
| `edgeStyle` | `curve`, `straight`, `step`, `ordered-arrows` | `curve` | How edges are drawn |
| `edgeLabels` | `pill`, `inline`, `hidden` | `pill` | Edge label style |
| `layout` | `grid`, `horizontal-lanes`, `vertical-lanes`, `layered-top-down` | `grid` | Layout algorithm |

### Per-Node Shape Override

Individual nodes can override the view's `nodeShape` via `tabNode.shape` or by setting `category: "actor"` (auto-detected as stick figures).

### Examples

UML use case diagram:
```json
{ "rendering": { "nodeShape": "ellipse" } }
```

State machine:
```json
{ "rendering": { "nodeShape": "rounded" } }
```

Sequence diagram:
```json
{ "rendering": { "nodeShape": "pill", "edgeStyle": "ordered-arrows" } }
```
```

- [ ] **Step 2: Commit**

```bash
git add skills/canvas/SKILL.md
git commit -m "docs: add rendering hints to SKILL.md"
```

---

### Task 11: Final integration test — rebuild, restart, verify all tabs

**Files:** None (verification only)

- [ ] **Step 1: Full rebuild**

```bash
cd client && npx vite build
```

- [ ] **Step 2: Restart server**

Kill existing server, start fresh:
```bash
node server/index.js --project-dir . &
```

- [ ] **Step 3: Verify existing tabs unchanged**

Open canvas, check:
- Data Flow tab: all card nodes, edges connect properly
- Plugin Integration tab: all card nodes, edges connect properly
- Client Architecture tab: all card nodes, edges connect properly

- [ ] **Step 4: Verify Use Case Diagrams tab**

Switch to Use Case Diagrams:
- Developer and Claude nodes render as stick figures (auto-detected from `category: "actor"`)
- All use case nodes render as ellipses (from `rendering: { nodeShape: "ellipse" }`)
- Edges connect smoothly to ellipse borders
- Selection, context menu, drag all work on both shapes

- [ ] **Step 5: Update canvas nodes to reflect completion**

```bash
curl -s -X POST http://localhost:PORT/api/events/batch \
  -H 'Content-Type: application/json' \
  -d '[
    {"type": "node.status", "actor": "claude", "data": {"nodeId": "n_rendering_hints", "status": "in-progress", "prev": "planned"}},
    {"type": "node.status", "actor": "claude", "data": {"nodeId": "n_node_shapes", "status": "in-progress", "prev": "planned"}},
    {"type": "node.status", "actor": "claude", "data": {"nodeId": "n_edge_styles", "status": "in-progress", "prev": "planned"}}
  ]'
```
