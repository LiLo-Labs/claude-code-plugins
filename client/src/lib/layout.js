/**
 * Layout engine — grid-based positioning from per-tab node placement.
 *
 * Each tab defines its own nodes with { nodeId, row, col, cols }.
 * The layout computes pixel positions from the grid.
 * Node metadata (label, subtitle, color, etc.) comes from the registry.
 *
 * This matches the study-tutor canvas model: tabs are diagrams, not filters.
 */

export const GRID = {
  nodeW: 280,
  nodeH: 70,
  colGap: 100,
  rowGap: 90,
  pad: 80,
};

/**
 * Compute pixel positions for tab nodes on a grid.
 *
 * @param {Array} tabNodes — [{nodeId, row, col, cols, ...}] from the active tab
 * @param {Object} savedPositions — user drag overrides { nodeId: {x, y} }
 * @returns {Map<nodeId, {x, y, w, h}>}
 */
export function computeLayout(tabNodes, savedPositions = {}) {
  const positions = new Map();

  // Determine max cols for centering
  let maxCols = 1;
  for (const tn of tabNodes) {
    if ((tn.col || 0) + 1 > maxCols) maxCols = (tn.col || 0) + 1;
    if (tn.cols && tn.cols > maxCols) maxCols = tn.cols;
  }
  const totalW = maxCols * (GRID.nodeW + GRID.colGap) - GRID.colGap;

  for (const tn of tabNodes) {
    const row = tn.row ?? 0;
    const col = tn.col ?? 0;
    const cols = tn.cols ?? maxCols;

    const autoY = GRID.pad + row * (GRID.nodeH + GRID.rowGap);
    const rowW = cols * (GRID.nodeW + GRID.colGap) - GRID.colGap;
    const rowOffset = (totalW - rowW) / 2;
    const autoX = GRID.pad + rowOffset + col * (GRID.nodeW + GRID.colGap);

    // Node size — span for width, height override, or depth-based default
    const span = tn.span || 1;
    const nodeW = span > 1 ? span * GRID.nodeW + (span - 1) * GRID.colGap : GRID.nodeW;
    const nodeH = tn.height || GRID.nodeH;  // tabs can override per-node

    const saved = savedPositions[tn.nodeId || tn.id];
    const x = saved ? saved.x : autoX;
    const y = saved ? saved.y : autoY;

    positions.set(tn.nodeId || tn.id, { x, y, w: nodeW, h: nodeH });
  }

  return positions;
}

/**
 * Clip a line from center toward target at rectangle border.
 */
export function clipAtBorder(cx, cy, tx, ty, hw, hh) {
  const dx = tx - cx;
  const dy = ty - cy;
  if (dx === 0 && dy === 0) return { x: cx, y: cy };
  const scale = Math.abs(dy * hw) > Math.abs(dx * hh)
    ? hh / Math.abs(dy)
    : hw / Math.abs(dx);
  return { x: cx + dx * scale, y: cy + dy * scale };
}

/**
 * Clip a line from center toward target at ellipse border.
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

/**
 * Get ancestors of a node from the registry.
 */
export function getAncestors(nodeId, nodes) {
  const result = [];
  let current = nodes.get(nodeId);
  while (current && current.parent) {
    const parent = nodes.get(current.parent);
    if (parent) result.unshift(parent);
    current = parent;
  }
  return result;
}
