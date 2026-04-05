/**
 * Auto-layout engine: generates drawio XML from node/edge data.
 *
 * Uses the shape registry for node shapes — databases get cylinders,
 * queues get process shapes, actors get stick figures, etc.
 *
 * Layout is hierarchical: topological sort into ranks, center-aligned.
 */
import { getStyledShape } from './shapes/registry.js';

/**
 * Generate drawio XML for a set of nodes and edges using auto-layout.
 */
export function generateLayoutXml(nodes, edges, opts = {}) {
  const nodeMap = nodes instanceof Map ? nodes : new Map(Object.entries(nodes));
  const edgeMap = edges instanceof Map ? edges : new Map(Object.entries(edges));

  if (nodeMap.size === 0) return '';

  const interRankSpacing = opts.interRankSpacing || 80;
  const interNodeSpacing = opts.interNodeSpacing || 40;
  const direction = opts.direction || 'north';

  // Build adjacency for topological sorting
  const inDegree = new Map();
  const adjList = new Map();
  for (const [id] of nodeMap) {
    inDegree.set(id, 0);
    adjList.set(id, []);
  }
  for (const [, edge] of edgeMap) {
    if (nodeMap.has(edge.from) && nodeMap.has(edge.to)) {
      adjList.get(edge.from).push(edge.to);
      inDegree.set(edge.to, (inDegree.get(edge.to) || 0) + 1);
    }
  }

  // Assign ranks using topological sort (Kahn's algorithm)
  const ranks = new Map();
  const queue = [];
  for (const [id, deg] of inDegree) {
    if (deg === 0) queue.push(id);
  }

  let rank = 0;
  const rankGroups = [];
  while (queue.length > 0) {
    const currentRank = [...queue];
    rankGroups.push(currentRank);
    const nextQueue = [];
    for (const id of currentRank) {
      ranks.set(id, rank);
      for (const child of (adjList.get(id) || [])) {
        inDegree.set(child, inDegree.get(child) - 1);
        if (inDegree.get(child) === 0) nextQueue.push(child);
      }
    }
    queue.length = 0;
    queue.push(...nextQueue);
    rank++;
  }

  // Handle cycles: unranked nodes at the bottom
  for (const [id] of nodeMap) {
    if (!ranks.has(id)) {
      if (!rankGroups[rank]) rankGroups[rank] = [];
      rankGroups[rank].push(id);
      ranks.set(id, rank);
    }
  }

  // Get shape dimensions for each node (shapes vary in size)
  const shapeDefs = new Map();
  for (const [id, node] of nodeMap) {
    shapeDefs.set(id, getStyledShape(node));
  }

  // Calculate positions using actual shape widths
  const positions = new Map();
  const isVertical = direction === 'north' || direction === 'south';

  for (let r = 0; r < rankGroups.length; r++) {
    const group = rankGroups[r];

    // Calculate total width of this rank using actual shape widths
    let totalWidth = 0;
    for (const id of group) {
      totalWidth += shapeDefs.get(id).width;
    }
    totalWidth += (group.length - 1) * interNodeSpacing;
    const startX = -totalWidth / 2;

    // Find max height in this rank for consistent row spacing
    let maxHeight = 0;
    for (const id of group) {
      const h = shapeDefs.get(id).height;
      if (h > maxHeight) maxHeight = h;
    }

    // Calculate cumulative Y position based on previous ranks
    let yPos = 0;
    for (let pr = 0; pr < r; pr++) {
      let prMaxH = 0;
      for (const pid of rankGroups[pr]) {
        const h = shapeDefs.get(pid).height;
        if (h > prMaxH) prMaxH = h;
      }
      yPos += prMaxH + interRankSpacing;
    }

    let xCursor = startX;
    for (const id of group) {
      const shape = shapeDefs.get(id);
      if (isVertical) {
        positions.set(id, { x: xCursor + shape.width / 2, y: yPos });
      } else {
        positions.set(id, { x: yPos, y: xCursor + shape.width / 2 });
      }
      xCursor += shape.width + interNodeSpacing;
    }
  }

  // Normalize positions so minimum is at padding origin
  let minX = Infinity, minY = Infinity;
  for (const [id, pos] of positions) {
    const shape = shapeDefs.get(id);
    if (pos.x - shape.width / 2 < minX) minX = pos.x - shape.width / 2;
    if (pos.y < minY) minY = pos.y;
  }
  const pad = 40;
  for (const pos of positions.values()) {
    pos.x = pos.x - minX + pad;
    pos.y = pos.y - minY + pad;
  }

  // Generate XML
  const cells = ['<mxGraphModel><root>', '<mxCell id="0"/>', '<mxCell id="1" parent="0"/>'];

  for (const [id, node] of nodeMap) {
    const pos = positions.get(id) || { x: pad, y: pad };
    const shape = shapeDefs.get(id);

    const label = node.subtitle
      ? `${escapeXml(node.label)}&#xa;${escapeXml(node.subtitle)}`
      : escapeXml(node.label);

    // Position is center-x, but mxGeometry wants top-left
    const x = Math.round(pos.x - shape.width / 2);
    const y = Math.round(pos.y);

    cells.push(
      `<mxCell id="${escapeXml(id)}" value="${label}" ` +
      `style="${shape.style}" ` +
      `vertex="1" parent="1">` +
      `<mxGeometry x="${x}" y="${y}" width="${shape.width}" height="${shape.height}" as="geometry"/>` +
      `</mxCell>`
    );
  }

  for (const [id, edge] of edgeMap) {
    if (!nodeMap.has(edge.from) || !nodeMap.has(edge.to)) continue;
    const label = edge.label ? ` value="${escapeXml(edge.label)}"` : '';
    const color = edge.color || '#8b949e';
    cells.push(
      `<mxCell id="${escapeXml(id)}"${label} ` +
      `style="rounded=1;curved=1;strokeColor=${color};fontColor=#8b949e;fontSize=11;" ` +
      `edge="1" source="${escapeXml(edge.from)}" target="${escapeXml(edge.to)}" parent="1">` +
      `<mxGeometry relative="1" as="geometry"/>` +
      `</mxCell>`
    );
  }

  cells.push('</root></mxGraphModel>');
  return cells.join('');
}

/**
 * Generate XML for a specific view, filtering to only nodes/edges that belong.
 */
export function generateViewXml(view, allNodes, allEdges, opts = {}) {
  const nodeMap = allNodes instanceof Map ? allNodes : new Map(Object.entries(allNodes));
  const edgeMap = allEdges instanceof Map ? allEdges : new Map(Object.entries(allEdges));

  let viewNodes = nodeMap;
  if (view.tabNodes && view.tabNodes.length > 0) {
    viewNodes = new Map();
    for (const tn of view.tabNodes) {
      const id = typeof tn === 'string' ? tn : tn.nodeId;
      if (nodeMap.has(id)) viewNodes.set(id, nodeMap.get(id));
    }
  }

  const viewEdges = new Map();
  for (const [id, edge] of edgeMap) {
    if (viewNodes.has(edge.from) && viewNodes.has(edge.to)) {
      viewEdges.set(id, edge);
    }
  }

  return generateLayoutXml(viewNodes, viewEdges, opts);
}

function escapeXml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
