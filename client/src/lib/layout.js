/**
 * Layout engine — grid-based positioning from row/col data.
 *
 * Nodes define their position via { row, col, cols } fields.
 * The layout computes pixel positions from a grid with configurable sizing.
 * User drag overrides are stored in savedPositions.
 *
 * This matches the proven study-tutor canvas approach.
 */

export const GRID = {
  nodeW: 300,
  nodeH: 70,
  colGap: 80,
  rowGap: 80,
  pad: 80,
};

/**
 * Compute pixel positions for nodes based on row/col grid.
 * Returns Map<nodeId, { x, y, w, h }>
 */
export function computeLayout(nodes, savedPositions = {}) {
  const positions = new Map();

  // Determine max cols for centering
  let maxCols = 1;
  for (const node of nodes.values()) {
    if ((node.col || 0) + 1 > maxCols) maxCols = (node.col || 0) + 1;
    if (node.cols && node.cols > maxCols) maxCols = node.cols;
  }
  const totalW = maxCols * (GRID.nodeW + GRID.colGap) - GRID.colGap;

  for (const [id, node] of nodes) {
    const row = node.row ?? 0;
    const col = node.col ?? 0;
    const cols = node.cols ?? maxCols;

    // Auto-layout position from grid
    const autoY = GRID.pad + row * (GRID.nodeH + GRID.rowGap);
    const rowW = cols * (GRID.nodeW + GRID.colGap) - GRID.colGap;
    const rowOffset = (totalW - rowW) / 2;
    const autoX = GRID.pad + rowOffset + col * (GRID.nodeW + GRID.colGap);

    // Apply saved position override
    const saved = savedPositions[id];
    const x = saved ? saved.x : autoX;
    const y = saved ? saved.y : autoY;

    positions.set(id, { x, y, w: GRID.nodeW, h: GRID.nodeH });
  }

  return positions;
}

/**
 * Clip a line from center (cx,cy) toward target (tx,ty) at rectangle border.
 * Returns the point where the line exits the rectangle.
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
 * Compute bezier edge path between two nodes.
 * Uses quadratic bezier with perpendicular offset (avoids straight lines).
 * Returns { path, labelX, labelY } for SVG rendering.
 */
export function computeEdgePath(fromPos, toPos) {
  const fcx = fromPos.x + fromPos.w / 2;
  const fcy = fromPos.y + fromPos.h / 2;
  const tcx = toPos.x + toPos.w / 2;
  const tcy = toPos.y + toPos.h / 2;

  // Clip at node borders
  const start = clipAtBorder(fcx, fcy, tcx, tcy, fromPos.w / 2, fromPos.h / 2);
  const end = clipAtBorder(tcx, tcy, fcx, fcy, toPos.w / 2 + 6, toPos.h / 2 + 6);

  const mx = (start.x + end.x) / 2;
  const my = (start.y + end.y) / 2;

  // Perpendicular offset for curve (avoids straight line overlap)
  const bf = Math.abs(end.y - start.y) > Math.abs(end.x - start.x) ? 0.2 : 0.15;
  const px = -(end.y - start.y) * bf;
  const py = (end.x - start.x) * bf;

  // Quadratic bezier
  const path = `M${start.x},${start.y} Q${mx + px},${my + py} ${end.x},${end.y}`;

  // Label position (offset from midpoint along perpendicular)
  const labelX = mx + px * 0.5;
  const labelY = my + py * 0.5;

  return { path, labelX, labelY };
}

/**
 * Get ancestors of a node (ordered root → parent).
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
