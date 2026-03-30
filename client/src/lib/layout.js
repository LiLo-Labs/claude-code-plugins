/**
 * Layout engine — computes node positions.
 * Bottom-up sizing (containers wrap children), top-down positioning.
 */

const NW = 280;
const NH = 90;
const CPAD = 32;  // container internal padding
const CHDR = 40;  // container header height
const NGAP = 20;  // gap between sibling nodes
const TGAP = 40;  // gap between top-level nodes

export { NW, NH, CPAD, CHDR, NGAP };

/**
 * Get direct children of a node from the nodes map.
 */
function getChildren(nodeId, nodes) {
  return [...nodes.values()].filter(n => n.parent === nodeId);
}

/**
 * Compute the size a node needs (recursively includes children if expanded).
 * Returns { w, h }
 */
export function computeNodeSize(node, nodes, expandedSet) {
  const children = getChildren(node.id, nodes);
  const isExpanded = expandedSet.has(node.id) && children.length > 0;

  if (!isExpanded) {
    return { w: NW, h: NH };
  }

  const childSizes = children.map(c => computeNodeSize(c, nodes, expandedSet));
  const totalH = childSizes.reduce((sum, s) => sum + s.h, 0) + (children.length - 1) * NGAP;
  const maxW = Math.max(NW, ...childSizes.map(s => s.w));

  return {
    w: maxW + CPAD * 2,
    h: CHDR + CPAD + totalH + CPAD,
  };
}

/**
 * Compute positions for all visible nodes.
 * Returns Map<nodeId, { x, y, w, h, isContainer }>
 */
export function computeLayout(nodes, expandedSet, savedPositions = {}) {
  const positions = new Map();
  const roots = [...nodes.values()].filter(n => !n.parent);

  function layoutNode(node, x, y) {
    const children = getChildren(node.id, nodes);
    const isExpanded = expandedSet.has(node.id) && children.length > 0;
    const size = computeNodeSize(node, nodes, expandedSet);

    // Use saved position if available, otherwise computed
    const saved = savedPositions[node.id];
    const finalX = saved ? saved.x : x;
    const finalY = saved ? saved.y : y;

    positions.set(node.id, {
      x: finalX,
      y: finalY,
      w: size.w,
      h: size.h,
      isContainer: isExpanded,
    });

    if (isExpanded) {
      let cy = finalY + CHDR + CPAD;
      for (const child of children) {
        const childSize = computeNodeSize(child, nodes, expandedSet);
        layoutNode(child, finalX + CPAD, cy);
        cy += childSize.h + NGAP;
      }
    }
  }

  let x = 50;
  for (const root of roots) {
    const size = computeNodeSize(root, nodes, expandedSet);
    layoutNode(root, x, 50);
    x += size.w + TGAP;
  }

  return positions;
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
 * Find the nearest visible ancestor for a node that has a position.
 * Used for edge re-routing when an endpoint is collapsed.
 */
export function findVisibleEndpoint(nodeId, nodes, positions) {
  if (positions.has(nodeId)) return nodeId;
  const node = nodes.get(nodeId);
  if (!node || !node.parent) return null;
  return findVisibleEndpoint(node.parent, nodes, positions);
}
