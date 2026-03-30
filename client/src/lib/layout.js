/**
 * Layout engine — computes node positions for the canvas.
 *
 * Design:
 * - Top-level children arrange horizontally (side by side)
 * - Children inside a container arrange horizontally (side by side)
 * - Containers auto-size to wrap their children
 * - Nodes have variable width based on content
 * - Saved positions override computed positions
 *
 * Two-pass algorithm:
 *   1. Bottom-up: compute sizes (leaf → root)
 *   2. Top-down: assign positions (root → leaf)
 */

import {
  NODE, CONTAINER, SPACING,
  estimateNodeWidth, estimateNodeHeight,
} from './config.js';

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

// ── Pass 1: Compute Sizes ──

/**
 * Compute the bounding box a node needs.
 * Returns { w, h, isContainer, childSizes }
 */
export function computeSize(node, nodes, expandedSet) {
  const children = getChildren(node.id, nodes);
  const isExpanded = expandedSet.has(node.id) && children.length > 0;

  if (!isExpanded) {
    // Leaf node (or collapsed parent) — size from content
    const w = estimateNodeWidth(node.label, node.subtitle);
    const h = estimateNodeHeight(node.subtitle);
    return { w, h, isContainer: false, childSizes: [] };
  }

  // Container — size from children arranged horizontally
  const childSizes = children.map(c => computeSize(c, nodes, expandedSet));
  const totalChildW = childSizes.reduce((sum, s) => sum + s.w, 0)
    + (children.length - 1) * SPACING.siblingGapH;
  const maxChildH = Math.max(...childSizes.map(s => s.h));

  const w = Math.max(
    estimateNodeWidth(node.label, ''), // at least as wide as the header
    totalChildW + CONTAINER.padding * 2,
  );
  const h = CONTAINER.headerHeight + CONTAINER.padding + maxChildH + CONTAINER.padding;

  return { w, h, isContainer: true, childSizes };
}

// ── Pass 2: Assign Positions ──

/**
 * Recursively assign positions to nodes.
 * Returns Map<nodeId, { x, y, w, h, isContainer }>
 */
function assignPositions(node, x, y, nodes, expandedSet, positions, savedPositions) {
  const children = getChildren(node.id, nodes);
  const size = computeSize(node, nodes, expandedSet);

  // Use saved position if available
  const saved = savedPositions[node.id];
  const finalX = saved ? saved.x : x;
  const finalY = saved ? saved.y : y;

  positions.set(node.id, {
    x: finalX,
    y: finalY,
    w: size.w,
    h: size.h,
    isContainer: size.isContainer,
  });

  if (size.isContainer) {
    // Arrange children horizontally, centered within the container
    const totalChildW = size.childSizes.reduce((sum, s) => sum + s.w, 0)
      + (children.length - 1) * SPACING.siblingGapH;
    let cx = finalX + (size.w - totalChildW) / 2; // center children
    const cy = finalY + CONTAINER.headerHeight + CONTAINER.padding;

    children.forEach((child, i) => {
      assignPositions(child, cx, cy, nodes, expandedSet, positions, savedPositions);
      cx += size.childSizes[i].w + SPACING.siblingGapH;
    });
  }
}

/**
 * Compute layout for all visible nodes.
 * Main entry point.
 */
export function computeLayout(nodes, expandedSet, savedPositions = {}) {
  const positions = new Map();
  const roots = [...nodes.values()].filter(n => !n.parent);

  // Arrange roots horizontally
  let x = SPACING.edgePadding;
  for (const root of roots) {
    const size = computeSize(root, nodes, expandedSet);
    assignPositions(root, x, SPACING.edgePadding, nodes, expandedSet, positions, savedPositions);
    x += size.w + SPACING.topLevelGap;
  }

  return positions;
}
