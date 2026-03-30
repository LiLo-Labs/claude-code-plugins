/**
 * Layout engine — uses ELK.js for hierarchical graph layout with edge routing.
 *
 * ELK handles:
 * - Node positioning (layered/hierarchical)
 * - Edge routing (avoids crossing nodes)
 * - Container/compound node support
 *
 * We translate our graph model → ELK graph → position map.
 */

import ELK from 'elkjs/lib/elk.bundled.js';
import { NODE, CONTAINER, SPACING, estimateNodeWidth, estimateNodeHeight } from './config.js';

const elk = new ELK();

// ── Helpers ──

function getChildren(nodeId, nodes) {
  return [...nodes.values()].filter(n => n.parent === nodeId);
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

/**
 * Find the nearest ancestor that has a position (for edge re-routing).
 */
export function findVisibleEndpoint(nodeId, nodes, positions) {
  if (positions.has(nodeId)) return nodeId;
  const node = nodes.get(nodeId);
  if (!node || !node.parent) return null;
  return findVisibleEndpoint(node.parent, nodes, positions);
}

/**
 * Build an ELK graph from our node/edge model.
 */
function buildElkGraph(nodes, edges, expandedSet) {
  const elkNodes = [];
  const elkEdges = [];

  // Build node tree recursively
  function buildNode(node) {
    const children = getChildren(node.id, nodes);
    const isExpanded = expandedSet.has(node.id) && children.length > 0;

    const w = estimateNodeWidth(node.label, node.subtitle);
    const h = estimateNodeHeight(node.subtitle);

    const elkNode = {
      id: node.id,
      width: w,
      height: h,
      labels: [{ text: node.label }],
    };

    if (isExpanded) {
      // Compound node — children laid out inside
      elkNode.children = children.map(buildNode);
      elkNode.layoutOptions = {
        'elk.algorithm': 'layered',
        'elk.direction': 'RIGHT',
        'elk.spacing.nodeNode': String(SPACING.siblingGapH),
        'elk.padding': `[top=${CONTAINER.headerHeight + CONTAINER.padding},left=${CONTAINER.padding},bottom=${CONTAINER.padding},right=${CONTAINER.padding}]`,
        'elk.layered.spacing.nodeNodeBetweenLayers': String(SPACING.siblingGapH),
      };
      // Don't set width/height for compound nodes — ELK computes it
      delete elkNode.width;
      delete elkNode.height;
    }

    return elkNode;
  }

  // Build root nodes
  const roots = [...nodes.values()].filter(n => !n.parent);
  for (const root of roots) {
    elkNodes.push(buildNode(root));
  }

  // Collect all node IDs that exist in the ELK graph
  const elkNodeIds = new Set();
  function collectIds(elkNode) {
    elkNodeIds.add(elkNode.id);
    if (elkNode.children) elkNode.children.forEach(collectIds);
  }
  elkNodes.forEach(collectIds);

  // Find nearest ancestor that's in the ELK graph
  function remapToVisible(nodeId) {
    if (elkNodeIds.has(nodeId)) return nodeId;
    const node = nodes.get(nodeId);
    if (!node || !node.parent) return null;
    return remapToVisible(node.parent);
  }

  // Build edges — remap endpoints to visible ancestors, skip self-loops
  const seenEdges = new Set();
  for (const edge of edges.values()) {
    const from = remapToVisible(edge.from);
    const to = remapToVisible(edge.to);
    if (!from || !to || from === to) continue;
    const key = `${from}->${to}`;
    if (seenEdges.has(key)) continue; // deduplicate remapped edges
    seenEdges.add(key);
    elkEdges.push({
      id: edge.id,
      sources: [from],
      targets: [to],
      labels: edge.label ? [{ text: edge.label, width: edge.label.length * 7 + 28, height: 22 }] : [],
    });
  }

  return {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.spacing.nodeNode': String(SPACING.topLevelGap),
      'elk.layered.spacing.nodeNodeBetweenLayers': String(SPACING.topLevelGap),
      'elk.edgeRouting': 'SPLINES',
      'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
    },
    children: elkNodes,
    edges: elkEdges,
  };
}

/**
 * Extract positions from ELK layout result.
 * Returns Map<nodeId, { x, y, w, h, isContainer }>
 */
function extractPositions(elkResult, offsetX = 0, offsetY = 0) {
  const positions = new Map();

  for (const node of elkResult.children || []) {
    const x = (node.x || 0) + offsetX;
    const y = (node.y || 0) + offsetY;
    const w = node.width || NODE.minWidth;
    const h = node.height || 60;
    const isContainer = !!(node.children && node.children.length > 0);

    positions.set(node.id, { x, y, w, h, isContainer });

    // Recurse into children (positions are relative to parent)
    if (node.children) {
      const childPositions = extractPositions(node, x, y);
      for (const [id, pos] of childPositions) {
        positions.set(id, pos);
      }
    }
  }

  return positions;
}

/**
 * Extract edge routes from ELK layout result.
 * Returns Map<edgeId, { points: [{x,y}], labelPos: {x,y} | null }>
 */
function extractEdgeRoutes(elkResult, offsetX = 0, offsetY = 0) {
  const routes = new Map();

  for (const edge of elkResult.edges || []) {
    const sections = edge.sections || [];
    const points = [];

    for (const section of sections) {
      points.push({
        x: (section.startPoint?.x || 0) + offsetX,
        y: (section.startPoint?.y || 0) + offsetY,
      });
      for (const bp of section.bendPoints || []) {
        points.push({ x: bp.x + offsetX, y: bp.y + offsetY });
      }
      points.push({
        x: (section.endPoint?.x || 0) + offsetX,
        y: (section.endPoint?.y || 0) + offsetY,
      });
    }

    let labelPos = null;
    if (edge.labels && edge.labels.length > 0) {
      const l = edge.labels[0];
      labelPos = {
        x: (l.x || 0) + (l.width || 0) / 2 + offsetX,
        y: (l.y || 0) + (l.height || 0) / 2 + offsetY,
      };
    }

    routes.set(edge.id, { points, labelPos });
  }

  // Recurse into children for edges inside compound nodes
  for (const node of elkResult.children || []) {
    if (node.children) {
      const childRoutes = extractEdgeRoutes(node, (node.x || 0) + offsetX, (node.y || 0) + offsetY);
      for (const [id, route] of childRoutes) {
        routes.set(id, route);
      }
    }
  }

  return routes;
}

/**
 * Compute layout using ELK.
 * Async because ELK runs in a web worker.
 * Returns { positions: Map, edgeRoutes: Map }
 */
export async function computeLayoutAsync(nodes, edges, expandedSet, savedPositions = {}) {
  const elkGraph = buildElkGraph(nodes, edges, expandedSet);

  try {
    const result = await elk.layout(elkGraph);
    const positions = extractPositions(result, SPACING.edgePadding, SPACING.edgePadding);
    const edgeRoutes = extractEdgeRoutes(result, SPACING.edgePadding, SPACING.edgePadding);

    // Apply saved position overrides
    for (const [nodeId, saved] of Object.entries(savedPositions)) {
      if (positions.has(nodeId)) {
        const pos = positions.get(nodeId);
        pos.x = saved.x;
        pos.y = saved.y;
      }
    }

    return { positions, edgeRoutes };
  } catch (err) {
    console.error('ELK layout failed:', err);
    // Fallback: simple horizontal layout
    return { positions: fallbackLayout(nodes, expandedSet), edgeRoutes: new Map() };
  }
}

/**
 * Synchronous fallback layout (no edge routing).
 * Used when ELK fails or for initial render before async completes.
 */
export function computeLayout(nodes, expandedSet, savedPositions = {}) {
  const positions = new Map();
  const roots = [...nodes.values()].filter(n => !n.parent);
  let x = SPACING.edgePadding;

  for (const root of roots) {
    layoutSimple(root, x, SPACING.edgePadding, nodes, expandedSet, positions, savedPositions);
    const pos = positions.get(root.id);
    x += (pos?.w || NODE.minWidth) + SPACING.topLevelGap;
  }

  return positions;
}

function layoutSimple(node, x, y, nodes, expandedSet, positions, savedPositions) {
  const children = getChildren(node.id, nodes);
  const isExpanded = expandedSet.has(node.id) && children.length > 0;

  const saved = savedPositions[node.id];
  const finalX = saved ? saved.x : x;
  const finalY = saved ? saved.y : y;

  if (!isExpanded) {
    const w = estimateNodeWidth(node.label, node.subtitle);
    const h = estimateNodeHeight(node.subtitle);
    positions.set(node.id, { x: finalX, y: finalY, w, h, isContainer: false });
    return;
  }

  // Container: lay children out horizontally
  const childWidths = children.map(c => {
    const w = estimateNodeWidth(c.label, c.subtitle);
    return w;
  });
  const totalW = childWidths.reduce((s, w) => s + w, 0) + (children.length - 1) * SPACING.siblingGapH;
  const containerW = Math.max(estimateNodeWidth(node.label, ''), totalW + CONTAINER.padding * 2);

  let cx = finalX + CONTAINER.padding;
  const cy = finalY + CONTAINER.headerHeight + CONTAINER.padding;
  let maxChildH = 0;

  children.forEach((child, i) => {
    layoutSimple(child, cx, cy, nodes, expandedSet, positions, savedPositions);
    const childPos = positions.get(child.id);
    maxChildH = Math.max(maxChildH, childPos?.h || 0);
    cx += (childPos?.w || childWidths[i]) + SPACING.siblingGapH;
  });

  const containerH = CONTAINER.headerHeight + CONTAINER.padding + maxChildH + CONTAINER.padding;
  positions.set(node.id, { x: finalX, y: finalY, w: containerW, h: containerH, isContainer: true });
}

function fallbackLayout(nodes, expandedSet) {
  return computeLayout(nodes, expandedSet);
}
