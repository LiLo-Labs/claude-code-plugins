# SVG Canvas Renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace maxGraph with a custom SVG renderer that faithfully renders draw.io XML shapes (hexagons, cylinders, documents, actors, etc.) with click, drag, draw, zoom/pan interactivity.

**Architecture:** Two new files (`svg-renderer.js` + `SvgCanvas.svelte`) replace two existing ones (`maxgraph.js` + `MaxGraphCanvas.svelte`). Everything else stays the same — `store.svelte.js`, `auto-layout.js`, `diagram-sync.js`, `App.svelte` all continue working with draw.io XML strings. The `@maxgraph/core` dependency gets removed.

**Tech Stack:** Svelte 5, native SVG, DOMParser for XML parsing

---

### Task 1: Create `svg-renderer.js` — XML parser and serializer

**Files:**
- Create: `client/src/lib/svg-renderer.js`
- Test: `client/src/lib/svg-renderer.test.js`

- [ ] **Step 1: Write the failing tests**

Create `client/src/lib/svg-renderer.test.js`:

```javascript
import { describe, test, expect } from 'vitest';
import { parseStyle, styleToString, parseDrawioXml, serializeToXml } from './svg-renderer.js';

describe('parseStyle', () => {
  test('parses semicolon-delimited style string', () => {
    const result = parseStyle('rounded=1;fillColor=#1a3320;strokeColor=#3fb950;fontSize=13;');
    expect(result.rounded).toBe('1');
    expect(result.fillColor).toBe('#1a3320');
    expect(result.strokeColor).toBe('#3fb950');
    expect(result.fontSize).toBe('13');
  });

  test('handles shape prefix (first token without =)', () => {
    const result = parseStyle('shape=hexagon;whiteSpace=wrap;fillColor=#1a3320;');
    expect(result.shape).toBe('hexagon');
    expect(result.fillColor).toBe('#1a3320');
  });

  test('returns empty object for empty string', () => {
    expect(parseStyle('')).toEqual({});
    expect(parseStyle(undefined)).toEqual({});
  });
});

describe('styleToString', () => {
  test('converts object back to semicolon-delimited string', () => {
    const str = styleToString({ rounded: '1', fillColor: '#1a3320' });
    expect(str).toContain('rounded=1');
    expect(str).toContain('fillColor=#1a3320');
    expect(str.endsWith(';')).toBe(true);
  });
});

describe('parseDrawioXml', () => {
  const xml = `<mxGraphModel><root>
    <mxCell id="0"/>
    <mxCell id="1" parent="0"/>
    <mxCell id="n_server" value="Server&#xa;HTTP API" style="rounded=1;fillColor=#1a3320;strokeColor=#3fb950;" vertex="1" parent="1">
      <mxGeometry x="100" y="200" width="160" height="60" as="geometry"/>
    </mxCell>
    <mxCell id="e_1" value="calls" style="curved=1;strokeColor=#8b949e;" edge="1" source="n_server" target="n_db" parent="1">
      <mxGeometry relative="1" as="geometry"/>
    </mxCell>
  </root></mxGraphModel>`;

  test('parses vertex cells into cells Map', () => {
    const { cells } = parseDrawioXml(xml);
    expect(cells.size).toBe(1);
    const server = cells.get('n_server');
    expect(server.value).toBe('Server\nHTTP API');
    expect(server.x).toBe(100);
    expect(server.y).toBe(200);
    expect(server.width).toBe(160);
    expect(server.height).toBe(60);
    expect(server.style.fillColor).toBe('#1a3320');
  });

  test('parses edge cells into edges Map', () => {
    const { edges } = parseDrawioXml(xml);
    expect(edges.size).toBe(1);
    const edge = edges.get('e_1');
    expect(edge.value).toBe('calls');
    expect(edge.source).toBe('n_server');
    expect(edge.target).toBe('n_db');
  });

  test('returns empty maps for empty/invalid XML', () => {
    const { cells, edges } = parseDrawioXml('');
    expect(cells.size).toBe(0);
    expect(edges.size).toBe(0);
  });
});

describe('serializeToXml', () => {
  test('round-trip: parse then serialize preserves data', () => {
    const xml = `<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="n_a" value="NodeA" style="rounded=1;fillColor=#1a3320;" vertex="1" parent="1"><mxGeometry x="40" y="80" width="120" height="50" as="geometry"/></mxCell></root></mxGraphModel>`;
    const { cells, edges } = parseDrawioXml(xml);
    const result = serializeToXml(cells, edges);
    const reparsed = parseDrawioXml(result);
    expect(reparsed.cells.size).toBe(1);
    const node = reparsed.cells.get('n_a');
    expect(node.value).toBe('NodeA');
    expect(node.x).toBe(40);
    expect(node.y).toBe(80);
    expect(node.style.fillColor).toBe('#1a3320');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npx vitest run client/src/lib/svg-renderer.test.js --reporter=verbose`
Expected: FAIL — module not found

- [ ] **Step 3: Implement svg-renderer.js**

Create `client/src/lib/svg-renderer.js`:

```javascript
/**
 * SVG Renderer — parse draw.io XML into cell/edge data and serialize back.
 * Pure functions, no framework dependency beyond DOMParser.
 */

/** Parse draw.io semicolon-delimited style string into object. */
export function parseStyle(str) {
  if (!str) return {};
  const result = {};
  for (const part of str.split(';')) {
    if (!part) continue;
    const eq = part.indexOf('=');
    if (eq === -1) {
      // Bare token like "rounded" — treat as flag
      result[part] = '1';
    } else {
      result[part.slice(0, eq)] = part.slice(eq + 1);
    }
  }
  return result;
}

/** Convert style object back to semicolon-delimited string. */
export function styleToString(obj) {
  if (!obj) return '';
  return Object.entries(obj).map(([k, v]) => `${k}=${v}`).join(';') + ';';
}

/** Escape XML attribute value. */
function esc(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/**
 * Parse draw.io XML into cells and edges Maps.
 * @param {string} xmlStr - draw.io XML string
 * @returns {{ cells: Map, edges: Map }}
 */
export function parseDrawioXml(xmlStr) {
  const cells = new Map();
  const edges = new Map();
  if (!xmlStr) return { cells, edges };

  let doc;
  try {
    doc = new DOMParser().parseFromString(xmlStr, 'text/xml');
  } catch {
    return { cells, edges };
  }

  const mxCells = doc.querySelectorAll('mxCell');
  for (const cell of mxCells) {
    const id = cell.getAttribute('id');
    if (!id || id === '0' || id === '1') continue;

    const style = parseStyle(cell.getAttribute('style') || '');
    const value = (cell.getAttribute('value') || '').replace(/&#xa;/g, '\n');

    if (cell.getAttribute('edge') === '1') {
      const points = [];
      const arrayEl = cell.querySelector('Array');
      if (arrayEl) {
        for (const pt of arrayEl.querySelectorAll('mxPoint')) {
          points.push({ x: parseFloat(pt.getAttribute('x')) || 0, y: parseFloat(pt.getAttribute('y')) || 0 });
        }
      }
      edges.set(id, {
        id, value,
        source: cell.getAttribute('source') || '',
        target: cell.getAttribute('target') || '',
        style, points,
      });
    } else if (cell.getAttribute('vertex') === '1') {
      const geo = cell.querySelector('mxGeometry');
      cells.set(id, {
        id, value,
        x: parseFloat(geo?.getAttribute('x')) || 0,
        y: parseFloat(geo?.getAttribute('y')) || 0,
        width: parseFloat(geo?.getAttribute('width')) || 120,
        height: parseFloat(geo?.getAttribute('height')) || 60,
        style,
      });
    }
  }

  return { cells, edges };
}

/**
 * Serialize cells and edges back to draw.io XML.
 * @param {Map} cells
 * @param {Map} edges
 * @returns {string}
 */
export function serializeToXml(cells, edges) {
  const parts = ['<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'];

  for (const [id, cell] of cells) {
    const val = cell.value ? cell.value.replace(/\n/g, '&#xa;') : '';
    parts.push(
      `<mxCell id="${esc(id)}" value="${esc(val)}" style="${styleToString(cell.style)}" vertex="1" parent="1">` +
      `<mxGeometry x="${Math.round(cell.x)}" y="${Math.round(cell.y)}" width="${Math.round(cell.width)}" height="${Math.round(cell.height)}" as="geometry"/>` +
      `</mxCell>`
    );
  }

  for (const [id, edge] of edges) {
    const val = edge.value ? ` value="${esc(edge.value)}"` : '';
    parts.push(
      `<mxCell id="${esc(id)}"${val} style="${styleToString(edge.style)}" edge="1" source="${esc(edge.source)}" target="${esc(edge.target)}" parent="1">` +
      `<mxGeometry relative="1" as="geometry"/>` +
      `</mxCell>`
    );
  }

  parts.push('</root></mxGraphModel>');
  return parts.join('');
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npx vitest run client/src/lib/svg-renderer.test.js --reporter=verbose`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add client/src/lib/svg-renderer.js client/src/lib/svg-renderer.test.js
git commit -m "feat: svg-renderer — draw.io XML parser and serializer"
```

---

### Task 2: Create `SvgCanvas.svelte` — shape rendering (no interactivity yet)

**Files:**
- Create: `client/src/components/SvgCanvas.svelte`

- [ ] **Step 1: Create SvgCanvas.svelte with shape rendering**

Create `client/src/components/SvgCanvas.svelte`:

```svelte
<script>
  import { parseDrawioXml, serializeToXml } from '../lib/svg-renderer.js';

  let { xml = '', dark = true, onchange, onselect, oncontextmenu: onctx, oncelladded, oncellremoved } = $props();

  let containerEl = $state(null);
  let cells = $state(new Map());
  let edges = $state(new Map());
  let viewBox = $state({ x: 0, y: 0, w: 1200, h: 800 });
  let selectedIds = $state(new Set());
  let lastSerializedXml = '';

  // Drag state
  let dragState = $state(null); // { type: 'node'|'pan'|'draw'|'edge', ... }
  let drawPreview = $state(null); // { x, y, w, h } for rubber-band
  let edgePreview = $state(null); // { x1, y1, x2, y2 } for edge drawing
  let hoveredNodeId = $state(null);

  // Parse XML when prop changes (avoid feedback loops)
  $effect(() => {
    if (xml && xml !== lastSerializedXml) {
      const parsed = parseDrawioXml(xml);
      cells = parsed.cells;
      edges = parsed.edges;
      zoomToFit();
    }
  });

  function zoomToFit() {
    if (cells.size === 0) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const c of cells.values()) {
      if (c.x < minX) minX = c.x;
      if (c.y < minY) minY = c.y;
      if (c.x + c.width > maxX) maxX = c.x + c.width;
      if (c.y + c.height > maxY) maxY = c.y + c.height;
    }
    const pad = 60;
    viewBox = { x: minX - pad, y: minY - pad, w: maxX - minX + pad * 2, h: maxY - minY + pad * 2 };
  }

  function emitChange() {
    const xmlStr = serializeToXml(cells, edges);
    lastSerializedXml = xmlStr;
    onchange?.(xmlStr);
  }

  // --- Shape SVG paths ---

  function hexagonPoints(x, y, w, h) {
    const inset = w * 0.2;
    return `${x + inset},${y} ${x + w - inset},${y} ${x + w},${y + h / 2} ${x + w - inset},${y + h} ${x + inset},${y + h} ${x},${y + h / 2}`;
  }

  function cylinderPath(x, y, w, h) {
    const ry = Math.min(h * 0.15, 12);
    return `M${x},${y + ry} A${w / 2},${ry} 0 0,1 ${x + w},${y + ry} L${x + w},${y + h - ry} A${w / 2},${ry} 0 0,1 ${x},${y + h - ry} Z M${x},${y + ry} A${w / 2},${ry} 0 0,0 ${x + w},${y + ry}`;
  }

  function documentPath(x, y, w, h) {
    const wave = h * 0.1;
    return `M${x},${y} L${x + w},${y} L${x + w},${y + h - wave} Q${x + w * 0.75},${y + h + wave} ${x + w / 2},${y + h - wave} Q${x + w * 0.25},${y + h - wave * 3} ${x},${y + h} Z`;
  }

  function cloudPath(x, y, w, h) {
    const cx = x + w / 2, cy = y + h / 2;
    return `M${x + w * 0.25},${y + h * 0.7} C${x - w * 0.05},${y + h * 0.7} ${x - w * 0.05},${y + h * 0.25} ${x + w * 0.2},${y + h * 0.25} C${x + w * 0.15},${y - h * 0.05} ${x + w * 0.45},${y - h * 0.05} ${x + w * 0.5},${y + h * 0.15} C${x + w * 0.55},${y - h * 0.05} ${x + w * 0.85},${y - h * 0.05} ${x + w * 0.8},${y + h * 0.25} C${x + w * 1.05},${y + h * 0.25} ${x + w * 1.05},${y + h * 0.7} ${x + w * 0.75},${y + h * 0.7} C${x + w * 0.75},${y + h * 0.95} ${x + w * 0.25},${y + h * 0.95} ${x + w * 0.25},${y + h * 0.7} Z`;
  }

  function rhombusPoints(x, y, w, h) {
    return `${x + w / 2},${y} ${x + w},${y + h / 2} ${x + w / 2},${y + h} ${x},${y + h / 2}`;
  }

  // --- Edge geometry ---

  function cellCenter(cell) {
    return { x: cell.x + cell.width / 2, y: cell.y + cell.height / 2 };
  }

  function clipToRect(cx, cy, tx, ty, hw, hh) {
    const dx = tx - cx, dy = ty - cy;
    if (dx === 0 && dy === 0) return { x: cx, y: cy };
    const absDx = Math.abs(dx), absDy = Math.abs(dy);
    let scale;
    if (absDx * hh > absDy * hw) {
      scale = hw / absDx;
    } else {
      scale = hh / absDy;
    }
    return { x: cx + dx * scale, y: cy + dy * scale };
  }

  function clipToEllipse(cx, cy, tx, ty, rx, ry) {
    const dx = tx - cx, dy = ty - cy;
    if (dx === 0 && dy === 0) return { x: cx, y: cy };
    const angle = Math.atan2(dy, dx);
    return { x: cx + rx * Math.cos(angle), y: cy + ry * Math.sin(angle) };
  }

  function clipPoint(cell, target) {
    const c = cellCenter(cell);
    const shape = cell.style.shape;
    if (shape === 'ellipse') {
      return clipToEllipse(c.x, c.y, target.x, target.y, cell.width / 2, cell.height / 2);
    }
    return clipToRect(c.x, c.y, target.x, target.y, cell.width / 2, cell.height / 2);
  }

  function edgePath(edge) {
    const fromCell = cells.get(edge.source);
    const toCell = cells.get(edge.target);
    if (!fromCell || !toCell) return { path: '', labelX: 0, labelY: 0 };

    const fc = cellCenter(fromCell);
    const tc = cellCenter(toCell);
    const start = clipPoint(fromCell, tc);
    const end = clipPoint(toCell, fc);

    const mx = (start.x + end.x) / 2;
    const my = (start.y + end.y) / 2;
    const bf = Math.abs(end.y - start.y) > Math.abs(end.x - start.x) ? 0.2 : 0.15;
    const px = -(end.y - start.y) * bf;
    const py = (end.x - start.x) * bf;

    return {
      path: `M${start.x},${start.y} Q${mx + px},${my + py} ${end.x},${end.y}`,
      labelX: mx + px * 0.5,
      labelY: my + py * 0.5,
    };
  }

  // --- Text lines ---

  function textLines(value) {
    if (!value) return [];
    return value.split('\n');
  }

  // --- Interaction handlers ---

  function svgPoint(e) {
    // Convert mouse event to SVG coordinates
    if (!containerEl) return { x: 0, y: 0 };
    const svg = containerEl.querySelector('svg');
    if (!svg) return { x: 0, y: 0 };
    const rect = svg.getBoundingClientRect();
    return {
      x: viewBox.x + (e.clientX - rect.left) / rect.width * viewBox.w,
      y: viewBox.y + (e.clientY - rect.top) / rect.height * viewBox.h,
    };
  }

  function cellAt(pt) {
    for (const [id, cell] of cells) {
      if (pt.x >= cell.x && pt.x <= cell.x + cell.width && pt.y >= cell.y && pt.y <= cell.y + cell.height) {
        return id;
      }
    }
    return null;
  }

  function handleMouseDown(e) {
    if (e.button === 2) return; // right-click handled separately
    const pt = svgPoint(e);
    const nodeId = cellAt(pt);

    if (nodeId) {
      // Start node drag
      const cell = cells.get(nodeId);
      selectedIds = new Set([nodeId]);
      onselect?.([nodeId]);
      dragState = { type: 'node', nodeId, offsetX: pt.x - cell.x, offsetY: pt.y - cell.y };
    } else {
      // Start draw or pan
      selectedIds = new Set();
      onselect?.([]);
      dragState = { type: 'pending', startX: pt.x, startY: pt.y, screenX: e.clientX, screenY: e.clientY };
    }
    e.preventDefault();
  }

  function handleMouseMove(e) {
    if (!dragState) {
      // Hover detection for connection points
      const pt = svgPoint(e);
      hoveredNodeId = cellAt(pt);
      return;
    }

    const pt = svgPoint(e);

    if (dragState.type === 'node') {
      const cell = cells.get(dragState.nodeId);
      if (cell) {
        cell.x = pt.x - dragState.offsetX;
        cell.y = pt.y - dragState.offsetY;
        cells = new Map(cells); // trigger reactivity
      }
    } else if (dragState.type === 'pending') {
      const dx = Math.abs(e.clientX - dragState.screenX);
      const dy = Math.abs(e.clientY - dragState.screenY);
      if (dx > 5 || dy > 5) {
        // Decide: draw shape or pan
        if (e.shiftKey || e.metaKey) {
          dragState = { type: 'pan', lastX: e.clientX, lastY: e.clientY };
        } else {
          dragState = { type: 'draw', startX: dragState.startX, startY: dragState.startY };
          drawPreview = { x: dragState.startX, y: dragState.startY, w: 0, h: 0 };
        }
      }
    } else if (dragState.type === 'draw') {
      drawPreview = {
        x: Math.min(dragState.startX, pt.x),
        y: Math.min(dragState.startY, pt.y),
        w: Math.abs(pt.x - dragState.startX),
        h: Math.abs(pt.y - dragState.startY),
      };
    } else if (dragState.type === 'pan') {
      const svg = containerEl?.querySelector('svg');
      if (svg) {
        const rect = svg.getBoundingClientRect();
        const dx = (e.clientX - dragState.lastX) / rect.width * viewBox.w;
        const dy = (e.clientY - dragState.lastY) / rect.height * viewBox.h;
        viewBox = { ...viewBox, x: viewBox.x - dx, y: viewBox.y - dy };
        dragState.lastX = e.clientX;
        dragState.lastY = e.clientY;
      }
    } else if (dragState.type === 'edge') {
      edgePreview = { ...edgePreview, x2: pt.x, y2: pt.y };
    }
  }

  function handleMouseUp(e) {
    if (!dragState) return;

    if (dragState.type === 'node') {
      emitChange();
    } else if (dragState.type === 'draw' && drawPreview && drawPreview.w > 20 && drawPreview.h > 20) {
      // Create new shape
      const id = 'cell_' + Date.now();
      const newCell = {
        id, value: '', x: drawPreview.x, y: drawPreview.y,
        width: drawPreview.w, height: drawPreview.h,
        style: { rounded: '1', fillColor: '#1e293b', strokeColor: '#58a6ff', fontColor: '#c9d1d9', fontSize: '13' },
      };
      cells.set(id, newCell);
      cells = new Map(cells);
      emitChange();
      oncelladded?.({ id, label: '', isEdge: false });
    } else if (dragState.type === 'edge' && edgePreview) {
      const pt = svgPoint(e);
      const targetId = cellAt(pt);
      if (targetId && targetId !== dragState.fromId) {
        const id = 'edge_' + Date.now();
        edges.set(id, {
          id, value: '', source: dragState.fromId, target: targetId,
          style: { curved: '1', strokeColor: '#8b949e', fontColor: '#8b949e', fontSize: '11' },
          points: [],
        });
        edges = new Map(edges);
        emitChange();
        oncelladded?.({ id, label: '', isEdge: true, from: dragState.fromId, to: targetId });
      }
    }

    dragState = null;
    drawPreview = null;
    edgePreview = null;
  }

  function handleContextMenu(e) {
    e.preventDefault();
    const pt = svgPoint(e);
    const nodeId = cellAt(pt);
    if (nodeId) {
      selectedIds = new Set([nodeId]);
      onselect?.([nodeId]);
      onctx?.({ x: e.clientX, y: e.clientY, cellId: nodeId });
    }
  }

  function handleWheel(e) {
    e.preventDefault();
    const scale = e.deltaY > 0 ? 1.1 : 0.9;
    const svg = containerEl?.querySelector('svg');
    if (!svg) return;
    const rect = svg.getBoundingClientRect();
    // Zoom around cursor position
    const mx = (e.clientX - rect.left) / rect.width;
    const my = (e.clientY - rect.top) / rect.height;
    const newW = viewBox.w * scale;
    const newH = viewBox.h * scale;
    viewBox = {
      x: viewBox.x + (viewBox.w - newW) * mx,
      y: viewBox.y + (viewBox.h - newH) * my,
      w: newW, h: newH,
    };
  }

  function handleKeyDown(e) {
    if ((e.key === 'Delete' || e.key === 'Backspace') && selectedIds.size > 0) {
      e.preventDefault();
      for (const id of selectedIds) {
        if (cells.has(id)) {
          cells.delete(id);
          oncellremoved?.({ id, isEdge: false });
        } else if (edges.has(id)) {
          edges.delete(id);
          oncellremoved?.({ id, isEdge: true });
        }
      }
      cells = new Map(cells);
      edges = new Map(edges);
      selectedIds = new Set();
      emitChange();
    }
  }

  function startEdgeDraw(nodeId, e) {
    e.stopPropagation();
    const cell = cells.get(nodeId);
    if (!cell) return;
    const c = cellCenter(cell);
    dragState = { type: 'edge', fromId: nodeId };
    edgePreview = { x1: c.x, y1: c.y, x2: c.x, y2: c.y };
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="graph-container"
  bind:this={containerEl}
  tabindex="0"
  onmousedown={handleMouseDown}
  onmousemove={handleMouseMove}
  onmouseup={handleMouseUp}
  oncontextmenu={handleContextMenu}
  onwheel={handleWheel}
  onkeydown={handleKeyDown}
>
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="{viewBox.x} {viewBox.y} {viewBox.w} {viewBox.h}"
    width="100%"
    height="100%"
  >
    <defs>
      <marker id="arrowhead" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z" fill="#8b949e"/>
      </marker>
    </defs>

    <!-- Edges -->
    {#each [...edges.values()] as edge (edge.id)}
      {@const ep = edgePath(edge)}
      {#if ep.path}
        <path
          d={ep.path}
          fill="none"
          stroke={edge.style.strokeColor || '#8b949e'}
          stroke-width="1.5"
          stroke-dasharray={edge.style.dashed === '1' ? '6,3' : 'none'}
          marker-end="url(#arrowhead)"
          style="cursor: pointer"
          onclick={() => { selectedIds = new Set([edge.id]); onselect?.([edge.id]); }}
        />
        {#if edge.value}
          <rect
            x={ep.labelX - edge.value.length * 3.5 - 6}
            y={ep.labelY - 9}
            width={edge.value.length * 7 + 12}
            height={18}
            rx="4"
            fill="var(--graph-bg, #0d1117)"
            opacity="0.85"
          />
          <text
            x={ep.labelX}
            y={ep.labelY + 4}
            text-anchor="middle"
            fill={edge.style.fontColor || '#8b949e'}
            font-size={edge.style.fontSize || '11'}
          >{edge.value}</text>
        {/if}
      {/if}
    {/each}

    <!-- Edge preview while drawing -->
    {#if edgePreview}
      <line x1={edgePreview.x1} y1={edgePreview.y1} x2={edgePreview.x2} y2={edgePreview.y2}
        stroke="#58a6ff" stroke-width="2" stroke-dasharray="6,3"/>
    {/if}

    <!-- Cells -->
    {#each [...cells.values()] as cell (cell.id)}
      {@const isSelected = selectedIds.has(cell.id)}
      {@const fill = cell.style.fillColor || '#1e293b'}
      {@const stroke = cell.style.strokeColor || '#58a6ff'}
      {@const fontColor = cell.style.fontColor || '#c9d1d9'}
      {@const fontSize = parseInt(cell.style.fontSize) || 13}
      {@const shape = cell.style.shape}
      {@const lines = textLines(cell.value)}
      {@const cx = cell.x + cell.width / 2}
      {@const cy = cell.y + cell.height / 2}

      <g style="cursor: grab" data-node={cell.id}>
        <!-- Selection outline -->
        {#if isSelected}
          {#if shape === 'hexagon'}
            <polygon points={hexagonPoints(cell.x - 3, cell.y - 3, cell.width + 6, cell.height + 6)} fill="none" stroke="#58a6ff" stroke-width="2.5" opacity="0.6"/>
          {:else if shape === 'ellipse'}
            <ellipse cx={cx} cy={cy} rx={cell.width / 2 + 4} ry={cell.height / 2 + 4} fill="none" stroke="#58a6ff" stroke-width="2.5" opacity="0.6"/>
          {:else if shape === 'rhombus'}
            <polygon points={rhombusPoints(cell.x - 4, cell.y - 4, cell.width + 8, cell.height + 8)} fill="none" stroke="#58a6ff" stroke-width="2.5" opacity="0.6"/>
          {:else}
            <rect x={cell.x - 3} y={cell.y - 3} width={cell.width + 6} height={cell.height + 6} rx="10" fill="none" stroke="#58a6ff" stroke-width="2.5" opacity="0.6"/>
          {/if}
        {/if}

        <!-- Shape -->
        {#if shape === 'hexagon' || shape === 'hexagonPerimeter2'}
          <polygon points={hexagonPoints(cell.x, cell.y, cell.width, cell.height)} fill={fill} stroke={stroke} stroke-width="1.5"/>
        {:else if shape === 'cylinder3'}
          <path d={cylinderPath(cell.x, cell.y, cell.width, cell.height)} fill={fill} stroke={stroke} stroke-width="1.5"/>
        {:else if shape === 'document'}
          <path d={documentPath(cell.x, cell.y, cell.width, cell.height)} fill={fill} stroke={stroke} stroke-width="1.5"/>
        {:else if shape === 'ellipse'}
          <ellipse cx={cx} cy={cy} rx={cell.width / 2} ry={cell.height / 2} fill={fill} stroke={stroke} stroke-width="1.5"/>
        {:else if shape === 'cloud'}
          <path d={cloudPath(cell.x, cell.y, cell.width, cell.height)} fill={fill} stroke={stroke} stroke-width="1.5"/>
        {:else if shape === 'rhombus'}
          <polygon points={rhombusPoints(cell.x, cell.y, cell.width, cell.height)} fill={fill} stroke={stroke} stroke-width="1.5"/>
        {:else if shape === 'actor'}
          {@const headR = Math.min(cell.width, cell.height) * 0.15}
          {@const headY = cell.y + headR + 4}
          {@const bodyTop = headY + headR}
          {@const bodyBot = cell.y + cell.height * 0.65}
          {@const armY = bodyTop + (bodyBot - bodyTop) * 0.3}
          <circle cx={cx} cy={headY} r={headR} fill="none" stroke={stroke} stroke-width="2"/>
          <line x1={cx} y1={bodyTop} x2={cx} y2={bodyBot} stroke={stroke} stroke-width="2"/>
          <line x1={cx - cell.width * 0.25} y1={armY} x2={cx + cell.width * 0.25} y2={armY} stroke={stroke} stroke-width="2"/>
          <line x1={cx} y1={bodyBot} x2={cx - cell.width * 0.2} y2={cell.y + cell.height * 0.85} stroke={stroke} stroke-width="2"/>
          <line x1={cx} y1={bodyBot} x2={cx + cell.width * 0.2} y2={cell.y + cell.height * 0.85} stroke={stroke} stroke-width="2"/>
        {:else}
          <!-- Default: rounded rectangle -->
          {@const rx = cell.style.rounded === '1' ? Math.min(parseInt(cell.style.arcSize) || 8, cell.width / 4) : 0}
          <rect x={cell.x} y={cell.y} width={cell.width} height={cell.height} rx={rx}
            fill={fill} stroke={stroke} stroke-width="1.5"
            stroke-dasharray={cell.style.dashed === '1' ? '6,3' : 'none'}/>
        {/if}

        <!-- Text -->
        {#if shape !== 'actor'}
          {#each lines as line, i}
            <text
              x={cx}
              y={cy + (i - (lines.length - 1) / 2) * (fontSize + 3) + fontSize * 0.35}
              text-anchor="middle"
              fill={fontColor}
              font-size={i === 0 ? fontSize : Math.max(fontSize - 2, 10)}
              font-weight={i === 0 && (parseInt(cell.style.fontStyle) & 1) ? '700' : '400'}
              opacity={i === 0 ? 1 : 0.7}
            >{line}</text>
          {/each}
        {:else}
          <!-- Actor: label below figure -->
          <text
            x={cx}
            y={cell.y + cell.height - 2}
            text-anchor="middle"
            fill={fontColor}
            font-size={Math.max(fontSize - 1, 10)}
            font-weight="600"
          >{lines[0] || ''}</text>
        {/if}

        <!-- Connection point (visible on hover) -->
        {#if hoveredNodeId === cell.id}
          <circle cx={cx + cell.width / 2} cy={cy} r="5" fill="#58a6ff" opacity="0.8" style="cursor: crosshair"
            onmousedown={(e) => startEdgeDraw(cell.id, e)}/>
          <circle cx={cx - cell.width / 2} cy={cy} r="5" fill="#58a6ff" opacity="0.8" style="cursor: crosshair"
            onmousedown={(e) => startEdgeDraw(cell.id, e)}/>
          <circle cx={cx} cy={cell.y} r="5" fill="#58a6ff" opacity="0.8" style="cursor: crosshair"
            onmousedown={(e) => startEdgeDraw(cell.id, e)}/>
          <circle cx={cx} cy={cell.y + cell.height} r="5" fill="#58a6ff" opacity="0.8" style="cursor: crosshair"
            onmousedown={(e) => startEdgeDraw(cell.id, e)}/>
        {/if}
      </g>
    {/each}

    <!-- Draw preview (rubber-band rectangle) -->
    {#if drawPreview}
      <rect x={drawPreview.x} y={drawPreview.y} width={drawPreview.w} height={drawPreview.h}
        fill="rgba(88,166,255,0.1)" stroke="#58a6ff" stroke-width="1" stroke-dasharray="4,2"/>
    {/if}
  </svg>
</div>

<style>
  .graph-container {
    width: 100%; height: 100%; min-height: 400px;
    overflow: hidden; position: relative; cursor: default;
    background: var(--graph-bg, #0d1117);
  }
  .graph-container:focus { outline: none; }
  svg { display: block; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add client/src/components/SvgCanvas.svelte
git commit -m "feat: SvgCanvas — custom SVG renderer with all shapes and interactions"
```

---

### Task 3: Wire SvgCanvas into App.svelte, remove maxGraph

**Files:**
- Modify: `client/src/App.svelte:7` (change import)
- Modify: `client/src/App.svelte:142` (change component name)
- Delete: `client/src/components/MaxGraphCanvas.svelte`
- Delete: `client/src/lib/maxgraph.js`
- Modify: `client/package.json` (remove `@maxgraph/core`)

- [ ] **Step 1: Update App.svelte import**

In `client/src/App.svelte`, change line 7:

```javascript
// OLD:
import MaxGraphCanvas from './components/MaxGraphCanvas.svelte';
// NEW:
import SvgCanvas from './components/SvgCanvas.svelte';
```

- [ ] **Step 2: Update App.svelte component usage**

In `client/src/App.svelte`, change line 142:

```javascript
// OLD:
<MaxGraphCanvas
// NEW:
<SvgCanvas
```

And the closing tag is self-managed (no closing tag needed since props end with `/>` at line 178).

- [ ] **Step 3: Remove old files**

```bash
rm client/src/components/MaxGraphCanvas.svelte client/src/lib/maxgraph.js
```

- [ ] **Step 4: Remove @maxgraph/core dependency**

```bash
cd client && npm uninstall @maxgraph/core && cd ..
```

- [ ] **Step 5: Build to verify**

```bash
cd client && npx vite build
```

Expected: Build succeeds with no maxGraph imports. Bundle should be ~660KB smaller.

- [ ] **Step 6: Run tests**

```bash
npx vitest run --reporter=verbose
```

Expected: All non-server tests pass. E2E tests should pass because `.graph-container` class and SVG elements are preserved.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: replace maxGraph with custom SVG renderer

Drop @maxgraph/core (669KB) in favor of SvgCanvas.svelte which renders
draw.io XML shapes natively — hexagons, cylinders, documents, actors,
clouds, ellipses, diamonds. Full interactivity: click, drag, draw,
zoom/pan, edge creation, delete."
```

---

### Task 4: Visual verification and edge cases

**Files:** None (verification only)

- [ ] **Step 1: Start server and open canvas**

```bash
node server/index.js --project-dir . &
open http://localhost:<port>
```

- [ ] **Step 2: Verify Architecture tab**

Check that:
- Shape Registry renders as a hexagon (not a rounded rectangle)
- SKILL.md renders with document shape
- Server, EventStore render as rounded rectangles with bold text
- Config renders with dashed border
- Edges connect properly with labels visible
- Click any node → detail panel opens

- [ ] **Step 3: Verify UI Components tab**

Check that:
- Tree layout from App Shell to child components
- Click-to-detail works
- Right-click context menu works

- [ ] **Step 4: Verify Hook Lifecycle tab**

Check that:
- Horizontal flow layout (left-to-right)
- Orange flow edges visible
- Dashed utility edges to Canvas Client

- [ ] **Step 5: Verify interactions**

- Drag a node → it moves, position persists on tab switch
- Zoom with scroll wheel
- Pan with Shift+drag
- Draw a new rectangle on empty space
- Draw an edge between two nodes via connection circles
- Delete a selected node with Delete key
- Right-click → context menu appears

- [ ] **Step 6: Commit version bump and push**

```bash
# Update version in marketplace config
# Build client
cd client && npx vite build && cd ..
git add -A
git commit -m "chore: bump to v0.5.0 — custom SVG renderer replaces maxGraph"
git push
```
