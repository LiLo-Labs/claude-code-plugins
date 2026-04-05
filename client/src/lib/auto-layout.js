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
 *
 * Supports layout hints via opts.layout:
 *   - 'layered-top-down' (default) — topological sort, vertical hierarchy
 *   - 'horizontal-flow' — topological sort, left-to-right flow
 *   - 'grid' — simple grid, no hierarchy
 *   - 'horizontal-lanes' — group by node depth property into swim lanes
 */
export function generateLayoutXml(nodes, edges, opts = {}) {
  const nodeMap = nodes instanceof Map ? nodes : new Map(Object.entries(nodes));
  const edgeMap = edges instanceof Map ? edges : new Map(Object.entries(edges));

  if (nodeMap.size === 0) return '';

  const interRankSpacing = opts.interRankSpacing || 80;
  const interNodeSpacing = opts.interNodeSpacing || 40;
  const pad = 40;
  const layout = opts.layout || 'layered-top-down';

  // Get shape dimensions for each node (shapes vary in size)
  const shapeDefs = new Map();
  for (const [id, node] of nodeMap) {
    shapeDefs.set(id, getStyledShape(node));
  }

  // Calculate positions based on layout algorithm
  const positions = new Map();

  if (layout === 'grid') {
    // Simple grid — no edge-based ordering
    const cols = Math.ceil(Math.sqrt(nodeMap.size));
    let maxWidth = 0, maxHeight = 0;
    for (const shape of shapeDefs.values()) {
      if (shape.width > maxWidth) maxWidth = shape.width;
      if (shape.height > maxHeight) maxHeight = shape.height;
    }
    let col = 0, row = 0;
    for (const [id] of nodeMap) {
      positions.set(id, {
        x: col * (maxWidth + interNodeSpacing) + pad + maxWidth / 2,
        y: row * (maxHeight + interRankSpacing) + pad,
      });
      col++;
      if (col >= cols) { col = 0; row++; }
    }
  } else if (layout === 'horizontal-lanes') {
    // Group nodes by depth property into horizontal swim lanes
    const lanes = new Map();
    for (const [id, node] of nodeMap) {
      const depth = node.depth || 'default';
      if (!lanes.has(depth)) lanes.set(depth, []);
      lanes.get(depth).push(id);
    }
    let laneY = pad;
    for (const [, ids] of lanes) {
      let maxH = 0;
      let x = pad;
      for (const id of ids) {
        const shape = shapeDefs.get(id);
        positions.set(id, { x: x + shape.width / 2, y: laneY });
        x += shape.width + interNodeSpacing;
        if (shape.height > maxH) maxH = shape.height;
      }
      laneY += maxH + interRankSpacing;
    }
  } else {
    // Topological sort layouts: layered-top-down (default) and horizontal-flow
    const horizontal = layout === 'horizontal-flow';

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

    for (let r = 0; r < rankGroups.length; r++) {
      const group = rankGroups[r];

      // Calculate total span of this rank using actual shape dimensions
      let totalSpan = 0;
      for (const id of group) {
        totalSpan += horizontal ? shapeDefs.get(id).height : shapeDefs.get(id).width;
      }
      totalSpan += (group.length - 1) * interNodeSpacing;
      const startCross = -totalSpan / 2;

      // Calculate cumulative main-axis position based on previous ranks
      let mainPos = 0;
      for (let pr = 0; pr < r; pr++) {
        let prMax = 0;
        for (const pid of rankGroups[pr]) {
          const dim = horizontal ? shapeDefs.get(pid).width : shapeDefs.get(pid).height;
          if (dim > prMax) prMax = dim;
        }
        mainPos += prMax + interRankSpacing;
      }

      let crossCursor = startCross;
      for (const id of group) {
        const shape = shapeDefs.get(id);
        if (horizontal) {
          // Ranks flow left-to-right (X = main axis), nodes stack vertically
          positions.set(id, { x: mainPos + shape.width / 2, y: crossCursor + shape.height / 2 });
          crossCursor += shape.height + interNodeSpacing;
        } else {
          // Ranks flow top-to-bottom (Y = main axis), nodes spread horizontally
          positions.set(id, { x: crossCursor + shape.width / 2, y: mainPos });
          crossCursor += shape.width + interNodeSpacing;
        }
      }
    }
  }

  // Normalize positions so minimum is at padding origin
  let minX = Infinity, minY = Infinity;
  for (const [id, pos] of positions) {
    const shape = shapeDefs.get(id);
    if (pos.x - shape.width / 2 < minX) minX = pos.x - shape.width / 2;
    if (pos.y < minY) minY = pos.y;
  }
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

  return generateLayoutXml(viewNodes, viewEdges, { ...opts, layout: view.rendering?.layout });
}

function escapeXml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
