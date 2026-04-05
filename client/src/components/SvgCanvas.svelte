<script>
  import { parseDrawioXml, serializeToXml } from '../lib/svg-renderer.js';

  let { xml = '', dark = true, onchange, onselect, oncontextmenu: onctx, oncelladded, oncellremoved } = $props();

  let containerEl = $state(null);
  let cells = $state(new Map());
  let edges = $state(new Map());
  let viewBox = $state({ x: 0, y: 0, w: 1200, h: 800 });
  let selectedIds = $state(new Set());
  let lastSerializedXml = '';
  let dragState = $state(null);
  let drawPreview = $state(null);
  let edgePreview = $state(null);
  let hoveredNodeId = $state(null);

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

  // Shape SVG paths
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
    return `M${x + w * 0.25},${y + h * 0.7} C${x - w * 0.05},${y + h * 0.7} ${x - w * 0.05},${y + h * 0.25} ${x + w * 0.2},${y + h * 0.25} C${x + w * 0.15},${y - h * 0.05} ${x + w * 0.45},${y - h * 0.05} ${x + w * 0.5},${y + h * 0.15} C${x + w * 0.55},${y - h * 0.05} ${x + w * 0.85},${y - h * 0.05} ${x + w * 0.8},${y + h * 0.25} C${x + w * 1.05},${y + h * 0.25} ${x + w * 1.05},${y + h * 0.7} ${x + w * 0.75},${y + h * 0.7} C${x + w * 0.75},${y + h * 0.95} ${x + w * 0.25},${y + h * 0.95} ${x + w * 0.25},${y + h * 0.7} Z`;
  }

  function rhombusPoints(x, y, w, h) {
    return `${x + w / 2},${y} ${x + w},${y + h / 2} ${x + w / 2},${y + h} ${x},${y + h / 2}`;
  }

  // Edge geometry
  function cellCenter(cell) {
    return { x: cell.x + cell.width / 2, y: cell.y + cell.height / 2 };
  }

  function clipToRect(cx, cy, tx, ty, hw, hh) {
    const dx = tx - cx, dy = ty - cy;
    if (dx === 0 && dy === 0) return { x: cx, y: cy };
    const absDx = Math.abs(dx), absDy = Math.abs(dy);
    const scale = absDx * hh > absDy * hw ? hw / absDx : hh / absDy;
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
    if (cell.style.shape === 'ellipse') {
      return clipToEllipse(c.x, c.y, target.x, target.y, cell.width / 2, cell.height / 2);
    }
    return clipToRect(c.x, c.y, target.x, target.y, cell.width / 2, cell.height / 2);
  }

  function edgePath(edge) {
    const fromCell = cells.get(edge.source);
    const toCell = cells.get(edge.target);
    if (!fromCell || !toCell) return { path: '', labelX: 0, labelY: 0 };
    const fc = cellCenter(fromCell), tc = cellCenter(toCell);
    const start = clipPoint(fromCell, tc);
    const end = clipPoint(toCell, fc);
    const mx = (start.x + end.x) / 2, my = (start.y + end.y) / 2;
    const bf = Math.abs(end.y - start.y) > Math.abs(end.x - start.x) ? 0.2 : 0.15;
    const px = -(end.y - start.y) * bf, py = (end.x - start.x) * bf;
    return {
      path: `M${start.x},${start.y} Q${mx + px},${my + py} ${end.x},${end.y}`,
      labelX: mx + px * 0.5, labelY: my + py * 0.5,
    };
  }

  function textLines(value) {
    if (!value) return [];
    return value.split('\n');
  }

  // Interaction handlers
  function svgPoint(e) {
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
    if (e.button === 2) return;
    const pt = svgPoint(e);
    const nodeId = cellAt(pt);
    if (nodeId) {
      const cell = cells.get(nodeId);
      selectedIds = new Set([nodeId]);
      onselect?.([nodeId]);
      dragState = { type: 'node', nodeId, offsetX: pt.x - cell.x, offsetY: pt.y - cell.y };
    } else {
      selectedIds = new Set();
      onselect?.([]);
      dragState = { type: 'pending', startX: pt.x, startY: pt.y, screenX: e.clientX, screenY: e.clientY };
    }
    e.preventDefault();
  }

  function handleMouseMove(e) {
    if (!dragState) {
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
        cells = new Map(cells);
      }
    } else if (dragState.type === 'pending') {
      const dx = Math.abs(e.clientX - dragState.screenX);
      const dy = Math.abs(e.clientY - dragState.screenY);
      if (dx > 5 || dy > 5) {
        if (e.shiftKey || e.metaKey) {
          dragState = { type: 'pan', lastX: e.clientX, lastY: e.clientY };
        } else {
          dragState = { type: 'draw', startX: dragState.startX, startY: dragState.startY };
          drawPreview = { x: dragState.startX, y: dragState.startY, w: 0, h: 0 };
        }
      }
    } else if (dragState.type === 'draw') {
      drawPreview = {
        x: Math.min(dragState.startX, pt.x), y: Math.min(dragState.startY, pt.y),
        w: Math.abs(pt.x - dragState.startX), h: Math.abs(pt.y - dragState.startY),
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
      const id = 'cell_' + Date.now();
      cells.set(id, {
        id, value: '', x: drawPreview.x, y: drawPreview.y,
        width: drawPreview.w, height: drawPreview.h,
        style: { rounded: '1', fillColor: '#1e293b', strokeColor: '#58a6ff', fontColor: '#c9d1d9', fontSize: '13' },
      });
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
    const mx = (e.clientX - rect.left) / rect.width;
    const my = (e.clientY - rect.top) / rect.height;
    const newW = viewBox.w * scale, newH = viewBox.h * scale;
    viewBox = { x: viewBox.x + (viewBox.w - newW) * mx, y: viewBox.y + (viewBox.h - newH) * my, w: newW, h: newH };
  }

  function handleKeyDown(e) {
    if ((e.key === 'Delete' || e.key === 'Backspace') && selectedIds.size > 0) {
      e.preventDefault();
      for (const id of selectedIds) {
        if (cells.has(id)) { cells.delete(id); oncellremoved?.({ id, isEdge: false }); }
        else if (edges.has(id)) { edges.delete(id); oncellremoved?.({ id, isEdge: true }); }
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

<div
  class="graph-container"
  tabindex="0"
  bind:this={containerEl}
  onmousedown={handleMouseDown}
  onmousemove={handleMouseMove}
  onmouseup={handleMouseUp}
  oncontextmenu={handleContextMenu}
  onwheel={handleWheel}
  onkeydown={handleKeyDown}
  role="application"
  aria-label="SVG Canvas"
>
  <svg
    viewBox="{viewBox.x} {viewBox.y} {viewBox.w} {viewBox.h}"
    width="100%"
    height="100%"
    xmlns="http://www.w3.org/2000/svg"
  >
    <defs>
      <marker
        id="arrowhead"
        markerWidth="10"
        markerHeight="7"
        refX="10"
        refY="3.5"
        orient="auto"
        markerUnits="strokeWidth"
      >
        <polygon points="0 0, 10 3.5, 0 7" fill="#8b949e" />
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
          marker-end="url(#arrowhead)"
          class:selected={selectedIds.has(edge.id)}
        />
        {#if edge.value}
          <rect
            x={ep.labelX - edge.value.length * 3.5}
            y={ep.labelY - 8}
            width={edge.value.length * 7}
            height="16"
            rx="3"
            fill={dark ? '#0d1117' : '#ffffff'}
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

    <!-- Edge preview -->
    {#if edgePreview}
      <line
        x1={edgePreview.x1}
        y1={edgePreview.y1}
        x2={edgePreview.x2}
        y2={edgePreview.y2}
        stroke="#58a6ff"
        stroke-width="2"
        stroke-dasharray="6 3"
        marker-end="url(#arrowhead)"
      />
    {/if}

    <!-- Cells -->
    {#each [...cells.values()] as cell (cell.id)}
      {@const shape = cell.style.shape || (cell.style.rounded === '1' ? 'rounded' : 'default')}
      {@const fill = cell.style.fillColor || '#1e293b'}
      {@const stroke = cell.style.strokeColor || '#58a6ff'}
      {@const fontColor = cell.style.fontColor || '#c9d1d9'}
      {@const fontSize = cell.style.fontSize || '13'}
      {@const isSelected = selectedIds.has(cell.id)}
      {@const isHovered = hoveredNodeId === cell.id}
      {@const lines = textLines(cell.value)}
      {@const cx = cell.x + cell.width / 2}
      {@const cy = cell.y + cell.height / 2}
      {@const fontStyle = cell.style.fontStyle || '0'}

      <g class="cell-group">
        <!-- Selection outline -->
        {#if isSelected}
          {#if shape === 'ellipse'}
            <ellipse
              cx={cx} cy={cy}
              rx={cell.width / 2 + 3} ry={cell.height / 2 + 3}
              fill="none" stroke="#58a6ff" stroke-width="2" stroke-dasharray="4 2"
            />
          {:else if shape === 'hexagon'}
            <polygon
              points={hexagonPoints(cell.x - 3, cell.y - 3, cell.width + 6, cell.height + 6)}
              fill="none" stroke="#58a6ff" stroke-width="2" stroke-dasharray="4 2"
            />
          {:else if shape === 'rhombus'}
            <polygon
              points={rhombusPoints(cell.x - 3, cell.y - 3, cell.width + 6, cell.height + 6)}
              fill="none" stroke="#58a6ff" stroke-width="2" stroke-dasharray="4 2"
            />
          {:else}
            <rect
              x={cell.x - 3} y={cell.y - 3}
              width={cell.width + 6} height={cell.height + 6}
              rx="10" fill="none" stroke="#58a6ff" stroke-width="2" stroke-dasharray="4 2"
            />
          {/if}
        {/if}

        <!-- Shape -->
        {#if shape === 'ellipse'}
          <ellipse
            cx={cx} cy={cy}
            rx={cell.width / 2} ry={cell.height / 2}
            fill={fill} stroke={stroke} stroke-width="1.5"
          />
        {:else if shape === 'hexagon'}
          <polygon
            points={hexagonPoints(cell.x, cell.y, cell.width, cell.height)}
            fill={fill} stroke={stroke} stroke-width="1.5"
          />
        {:else if shape === 'cylinder3'}
          <path
            d={cylinderPath(cell.x, cell.y, cell.width, cell.height)}
            fill={fill} stroke={stroke} stroke-width="1.5"
          />
        {:else if shape === 'document'}
          <path
            d={documentPath(cell.x, cell.y, cell.width, cell.height)}
            fill={fill} stroke={stroke} stroke-width="1.5"
          />
        {:else if shape === 'cloud'}
          <path
            d={cloudPath(cell.x, cell.y, cell.width, cell.height)}
            fill={fill} stroke={stroke} stroke-width="1.5"
          />
        {:else if shape === 'rhombus'}
          <polygon
            points={rhombusPoints(cell.x, cell.y, cell.width, cell.height)}
            fill={fill} stroke={stroke} stroke-width="1.5"
          />
        {:else if shape === 'actor'}
          <!-- Stick figure -->
          <g stroke={stroke} stroke-width="1.5" fill="none">
            <circle cx={cx} cy={cell.y + cell.height * 0.15} r={cell.height * 0.12} />
            <line x1={cx} y1={cell.y + cell.height * 0.27} x2={cx} y2={cell.y + cell.height * 0.6} />
            <line x1={cell.x + cell.width * 0.2} y1={cell.y + cell.height * 0.4} x2={cell.x + cell.width * 0.8} y2={cell.y + cell.height * 0.4} />
            <line x1={cx} y1={cell.y + cell.height * 0.6} x2={cell.x + cell.width * 0.25} y2={cell.y + cell.height * 0.85} />
            <line x1={cx} y1={cell.y + cell.height * 0.6} x2={cell.x + cell.width * 0.75} y2={cell.y + cell.height * 0.85} />
          </g>
        {:else}
          <!-- Default / rounded rect -->
          <rect
            x={cell.x} y={cell.y}
            width={cell.width} height={cell.height}
            rx={shape === 'rounded' || cell.style.rounded === '1' ? 8 : 0}
            fill={fill} stroke={stroke} stroke-width="1.5"
          />
        {/if}

        <!-- Text -->
        {#if lines.length > 0}
          <text
            x={cx} y={cy}
            text-anchor="middle"
            dominant-baseline="central"
            fill={fontColor}
            font-size={fontSize}
            pointer-events="none"
          >
            {#each lines as line, i}
              <tspan
                x={cx}
                dy={i === 0 ? `${-(lines.length - 1) * 0.6}em` : '1.2em'}
                font-weight={i === 0 && (parseInt(fontStyle) & 1) ? 'bold' : 'normal'}
              >{line}</tspan>
            {/each}
          </text>
        {/if}

        <!-- Connection points on hover -->
        {#if isHovered && !dragState}
          <circle cx={cx} cy={cell.y} r="5" fill="#58a6ff" opacity="0.8" cursor="crosshair"
            onmousedown={(e) => startEdgeDraw(cell.id, e)} />
          <circle cx={cx} cy={cell.y + cell.height} r="5" fill="#58a6ff" opacity="0.8" cursor="crosshair"
            onmousedown={(e) => startEdgeDraw(cell.id, e)} />
          <circle cx={cell.x} cy={cy} r="5" fill="#58a6ff" opacity="0.8" cursor="crosshair"
            onmousedown={(e) => startEdgeDraw(cell.id, e)} />
          <circle cx={cell.x + cell.width} cy={cy} r="5" fill="#58a6ff" opacity="0.8" cursor="crosshair"
            onmousedown={(e) => startEdgeDraw(cell.id, e)} />
        {/if}
      </g>
    {/each}

    <!-- Draw preview rubber-band -->
    {#if drawPreview}
      <rect
        x={drawPreview.x} y={drawPreview.y}
        width={drawPreview.w} height={drawPreview.h}
        fill="rgba(88, 166, 255, 0.1)"
        stroke="#58a6ff"
        stroke-width="1.5"
        stroke-dasharray="6 3"
        rx="4"
      />
    {/if}
  </svg>
</div>

<style>
  .graph-container {
    width: 100%;
    height: 100%;
    min-height: 400px;
    overflow: hidden;
    position: relative;
    cursor: default;
    background: var(--graph-bg, #0d1117);
  }
  .graph-container:focus {
    outline: none;
  }
  svg {
    display: block;
  }
</style>
