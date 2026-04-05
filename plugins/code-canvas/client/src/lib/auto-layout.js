/**
 * Auto-layout engine: generates drawio XML from node/edge data
 * using maxGraph's HierarchicalLayout for proper positioning.
 *
 * This replaces static hand-crafted XML with data-driven diagrams
 * that re-layout automatically when nodes/edges change.
 */

const STATUS_FILLS = {
  done:          { fill: '#1a3320', stroke: '#3fb950' },
  'in-progress': { fill: '#2a2a10', stroke: '#d29922' },
  planned:       { fill: '#1e2a3a', stroke: '#58a6ff' },
  blocked:       { fill: '#2a1010', stroke: '#f85149' },
  cut:           { fill: '#1a1a1a', stroke: '#8b949e' },
  placeholder:   { fill: '#1a1a1a', stroke: '#484f58' },
};

const DEPTH_ACCENTS = {
  system:    { fill: '#1e3a5f', stroke: '#4a90d9' },
  domain:    { fill: '#1a3320', stroke: '#3fb950' },
  module:    { fill: '#1e2a3a', stroke: '#58a6ff' },
  'interface': { fill: '#2a2020', stroke: '#8b949e' },
};

/**
 * Generate drawio XML for a set of nodes and edges using auto-layout.
 *
 * @param {Map|Object} nodes - nodeId → {id, label, subtitle, status, depth, ...}
 * @param {Map|Object} edges - edgeId → {id, from, to, label, ...}
 * @param {Object} opts - { direction: 'north'|'west', spacing: number }
 * @returns {string} drawio XML string
 */
export function generateLayoutXml(nodes, edges, opts = {}) {
  const nodeMap = nodes instanceof Map ? nodes : new Map(Object.entries(nodes));
  const edgeMap = edges instanceof Map ? edges : new Map(Object.entries(edges));

  if (nodeMap.size === 0) return '';

  const direction = opts.direction || 'north';  // top-to-bottom
  const interRankSpacing = opts.interRankSpacing || 80;
  const interNodeSpacing = opts.interNodeSpacing || 40;
  const nodeWidth = opts.nodeWidth || 200;
  const nodeHeight = opts.nodeHeight || 60;

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
  const rankGroups = []; // rank → [nodeIds]
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

  // Handle cycles: unranked nodes get placed at the bottom
  for (const [id] of nodeMap) {
    if (!ranks.has(id)) {
      if (!rankGroups[rank]) rankGroups[rank] = [];
      rankGroups[rank].push(id);
      ranks.set(id, rank);
    }
  }

  // Calculate positions
  const positions = new Map();
  const isVertical = direction === 'north' || direction === 'south';

  for (let r = 0; r < rankGroups.length; r++) {
    const group = rankGroups[r];
    const groupWidth = group.length * nodeWidth + (group.length - 1) * interNodeSpacing;
    const startOffset = -groupWidth / 2 + nodeWidth / 2;

    for (let i = 0; i < group.length; i++) {
      const id = group[i];
      const crossPos = startOffset + i * (nodeWidth + interNodeSpacing);
      const mainPos = r * (nodeHeight + interRankSpacing);

      if (isVertical) {
        positions.set(id, { x: crossPos, y: mainPos });
      } else {
        positions.set(id, { x: mainPos, y: crossPos });
      }
    }
  }

  // Normalize positions so minimum is at padding origin
  let minX = Infinity, minY = Infinity;
  for (const pos of positions.values()) {
    if (pos.x < minX) minX = pos.x;
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
    const colors = STATUS_FILLS[node.status] || DEPTH_ACCENTS[node.depth] || STATUS_FILLS.planned;
    const label = node.subtitle
      ? `${escapeXml(node.label)}&#xa;${escapeXml(node.subtitle)}`
      : escapeXml(node.label);

    const isSystem = node.depth === 'system' || node.depth === 'domain';
    const fontSize = isSystem ? 13 : 12;
    const fontStyle = isSystem ? 'fontStyle=1;' : '';
    const w = isSystem ? 220 : nodeWidth;
    const h = node.subtitle ? 60 : 45;

    cells.push(
      `<mxCell id="${escapeXml(id)}" value="${label}" ` +
      `style="rounded=1;whiteSpace=wrap;fillColor=${colors.fill};strokeColor=${colors.stroke};` +
      `fontColor=#e6edf3;fontSize=${fontSize};${fontStyle}spacingTop=4;spacingBottom=4;" ` +
      `vertex="1" parent="1">` +
      `<mxGeometry x="${Math.round(pos.x)}" y="${Math.round(pos.y)}" width="${w}" height="${h}" as="geometry"/>` +
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
 * Generate XML for a specific view, filtering to only nodes/edges that belong to it.
 * If view has tabNodes specified, use those. Otherwise, include all nodes.
 */
export function generateViewXml(view, allNodes, allEdges, opts = {}) {
  const nodeMap = allNodes instanceof Map ? allNodes : new Map(Object.entries(allNodes));
  const edgeMap = allEdges instanceof Map ? allEdges : new Map(Object.entries(allEdges));

  // Filter to view-specific nodes if tabNodes is specified
  let viewNodes = nodeMap;
  if (view.tabNodes && view.tabNodes.length > 0) {
    viewNodes = new Map();
    for (const tn of view.tabNodes) {
      const id = typeof tn === 'string' ? tn : tn.nodeId;
      if (nodeMap.has(id)) viewNodes.set(id, nodeMap.get(id));
    }
  }

  // Filter edges to only those connecting view nodes
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
