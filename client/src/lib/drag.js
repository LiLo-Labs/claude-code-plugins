/**
 * Drag system — tracks node dragging state.
 * Used by App.svelte to handle mousemove/mouseup at document level.
 */

export function createDragState() {
  return {
    active: false,
    nodeId: null,
    startX: 0,
    startY: 0,
    origX: 0,
    origY: 0,
  };
}

/**
 * Convert a mouse event to SVG coordinates.
 */
export function toSvgPoint(e, svgEl) {
  const pt = svgEl.createSVGPoint();
  pt.x = e.clientX;
  pt.y = e.clientY;
  return pt.matrixTransform(svgEl.getScreenCTM().inverse());
}
