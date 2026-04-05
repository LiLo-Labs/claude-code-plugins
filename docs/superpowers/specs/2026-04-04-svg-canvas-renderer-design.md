# SVG Canvas Renderer

**Goal:** Replace maxGraph with a custom SVG renderer that faithfully renders draw.io XML shapes (hexagons, cylinders, clouds, etc.) with full interactivity (click, drag, draw, zoom/pan).

**Why:** maxGraph (the OSS base library) only supports basic shapes — rectangles and ellipses. All draw.io extended shapes (`shape=hexagon`, `shape=cylinder3`, `shape=document`, `shape=actor`) fall back to default rounded rectangles. This makes all diagrams look the same regardless of the XML styles. Additionally, maxGraph adds 669KB (176KB gzipped) to the bundle.

## Architecture

Two new files replace two existing ones:

| Remove | Replace with | Purpose |
|--------|-------------|---------|
| `client/src/lib/maxgraph.js` | `client/src/lib/svg-renderer.js` | Parse draw.io XML → cell/edge data, serialize back |
| `client/src/components/MaxGraphCanvas.svelte` | `client/src/components/SvgCanvas.svelte` | Render SVG, handle all interaction |

Everything else stays the same — `store.svelte.js`, `auto-layout.js`, `diagram-sync.js`, `App.svelte` all continue working with draw.io XML strings.

## `svg-renderer.js` — XML Parser

Pure functions, no DOM dependency beyond DOMParser for XML parsing.

### `parseDrawioXml(xmlString) → { cells: Map, edges: Map }`

Each cell: `{ id, value, x, y, width, height, style }` where `style` is parsed from the draw.io style string into an object: `{ shape, fillColor, strokeColor, fontColor, fontSize, rounded, dashed, arcSize, fontStyle, ... }`.

Each edge: `{ id, value, source, target, style, points }` where `points` are waypoints from `<Array as="points">` elements.

### `parseStyle(styleString) → object`

Parse draw.io semicolon-delimited style strings: `"rounded=1;fillColor=#1a3320;strokeColor=#3fb950"` → `{ rounded: "1", fillColor: "#1a3320", strokeColor: "#3fb950" }`.

### `serializeToXml(cells, edges) → xmlString`

Round-trip: convert cell/edge data back to draw.io XML. Used when user drags a node (position updates) or draws new shapes.

### `styleToString(styleObj) → string`

Reverse of parseStyle.

## `SvgCanvas.svelte` — Interactive SVG Component

### Props (same interface as MaxGraphCanvas)

```
xml, dark, onchange, onselect, oncontextmenu, oncelladded, oncellremoved
```

### Shape Rendering

Switch on `style.shape` to render different SVG elements:

| shape value | SVG element | Notes |
|-------------|-------------|-------|
| (default) / `rounded` | `<rect rx="8">` | Standard component |
| `hexagon` | `<polygon>` | 6-point polygon computed from width/height |
| `cylinder3` | `<path>` | Elliptical top + rect body + elliptical bottom |
| `document` | `<path>` | Rectangle with wavy bottom edge |
| `ellipse` | `<ellipse>` | UML use case |
| `actor` | `<g>` (circle + lines) | UML stick figure |
| `cloud` | `<path>` | Cloud bezier curves |
| `rhombus` | `<polygon>` | Diamond decision shape |
| `process` | `<rect>` with side bars | Process/queue shape |

Each shape is a Svelte snippet or function: `renderShape(cell) → SVG elements`.

### Text Rendering

- Split `value` on `&#xa;` (or `\n`) into lines
- Render as `<text>` with `<tspan>` per line
- Center horizontally and vertically within shape bounds
- First line: fontSize from style (default 13), bold if `fontStyle` includes bold flag
- Subsequent lines: smaller fontSize (10-11), reduced opacity

### Edge Rendering

- Quadratic bezier `<path>` between source and target cells
- Clip at shape borders (use shape-aware clipping — ellipse clips to ellipse edge, rect clips to rect edge)
- Arrowhead via SVG `<marker>` definition
- Label: `<text>` positioned at bezier midpoint, with background `<rect>` for readability
- Style: strokeColor, dashed, curved from edge style

### Interactions

**Selection:**
- Click node → `onselect([nodeId])`
- Click empty space → `onselect([])`

**Context menu:**
- Right-click node → `oncontextmenu({ x, y, cellId })`

**Drag nodes:**
- mousedown on node → track offset
- mousemove → update cell position in local state, re-render
- mouseup → debounced `onchange(serializeToXml(cells, edges))`

**Draw new shapes:**
- mousedown on empty space + drag → rubber-band rectangle preview
- mouseup → create cell with generated ID → `oncelladded({ id, label, isEdge: false })`
- Minimum size threshold (20x20) to distinguish from click/pan

**Draw edges:**
- Small connection circles appear on node borders on hover
- mousedown on connection circle → drag line preview
- mouseup on another node → `oncelladded({ id, label, isEdge: true, from, to })`

**Delete:**
- Delete/Backspace on selected cell → `oncellremoved({ id, isEdge })`

**Pan:**
- mousedown on empty space + small drag (below draw threshold) → pan viewBox
- Or: middle-click drag always pans

**Zoom:**
- wheel event → scale viewBox (zoom in/out around cursor position)
- `zoomToFit()` → calculate viewBox from content bounds + padding

### State Management

Internal reactive state:
- `cells` and `edges` Maps (parsed from xml prop)
- `viewBox` — current pan/zoom state
- `selectedIds` — currently selected cell IDs
- `dragState` — active drag operation (node drag, edge draw, rubber-band, pan)

Re-parse XML only when `xml` prop changes AND differs from last serialized output (avoid feedback loops, same pattern as current MaxGraphCanvas).

## What Stays The Same

- `App.svelte` passes same props, receives same callbacks
- `store.svelte.js` generates/updates draw.io XML, same incremental splice logic
- `diagram-sync.js` does string-based style updates (fillColor/strokeColor)
- `auto-layout.js` generates draw.io XML with layout algorithms
- Shape registry still defines draw.io style strings (used by auto-layout)
- All tests that don't directly test maxGraph remain valid

## What Gets Removed

- `@maxgraph/core` dependency from package.json
- `client/src/lib/maxgraph.js`
- `client/src/components/MaxGraphCanvas.svelte`
- `import '@maxgraph/core/css/common.css'`

## Bundle Impact

Remove: `@maxgraph/core` — 669KB (176KB gzipped)
Add: ~5-8KB of our own SVG rendering code
Net: ~660KB reduction

## Testing

- Unit tests for `svg-renderer.js`: parse → serialize round-trip preserves data
- Unit tests for shape geometry functions (hexagon points, cylinder path, etc.)
- E2E tests: existing Playwright tests updated to work with SVG elements instead of maxGraph's internal DOM
- Visual verification: regenerate canvas, compare each tab
