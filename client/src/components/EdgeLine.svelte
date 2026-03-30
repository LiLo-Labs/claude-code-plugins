<script>
  /**
   * Edge — bezier curve between two positioned nodes.
   * Center-to-center routing with border clipping.
   * All sizing from shared config.
   */
  import { EDGE, CONTAINER } from '../lib/config.js';

  let { edge, fromPos, toPos } = $props();

  // Center points
  const fromCx = $derived(fromPos.x + fromPos.w / 2);
  const fromCy = $derived(fromPos.y + (fromPos.isContainer ? CONTAINER.headerHeight / 2 : fromPos.h / 2));
  const toCx = $derived(toPos.x + toPos.w / 2);
  const toCy = $derived(toPos.y + (toPos.isContainer ? CONTAINER.headerHeight / 2 : toPos.h / 2));

  // Half-sizes for clipping
  const fromHW = $derived(fromPos.w / 2);
  const fromHH = $derived((fromPos.isContainer ? CONTAINER.headerHeight : fromPos.h) / 2);
  const toHW = $derived(toPos.w / 2);
  const toHH = $derived((toPos.isContainer ? CONTAINER.headerHeight : toPos.h) / 2);

  function clipAtBorder(cx, cy, tx, ty, hw, hh) {
    const dx = tx - cx, dy = ty - cy;
    if (dx === 0 && dy === 0) return { x: cx, y: cy };
    const sx = hw / Math.abs(dx || 0.001);
    const sy = hh / Math.abs(dy || 0.001);
    const s = Math.min(sx, sy);
    return { x: cx + dx * s, y: cy + dy * s };
  }

  const startPt = $derived(clipAtBorder(fromCx, fromCy, toCx, toCy, fromHW, fromHH));
  const endPt = $derived(clipAtBorder(toCx, toCy, fromCx, fromCy, toHW + 4, toHH + 4));

  // Midpoint for label
  const mx = $derived((startPt.x + endPt.x) / 2);
  const my = $derived((startPt.y + endPt.y) / 2);

  // Bezier control points with slight curve
  const dx = $derived(endPt.x - startPt.x);
  const dy = $derived(endPt.y - startPt.y);
  const curveFactor = $derived(Math.abs(dy) > Math.abs(dx) ? 0.2 : 0.15);
  const perpX = $derived(-dy * curveFactor);
  const perpY = $derived(dx * curveFactor);

  // Label dimensions
  const labelW = $derived(edge.label ? edge.label.length * 7 + EDGE.labelPaddingX * 2 : 0);
  const labelH = $derived(EDGE.labelPaddingY * 2 + EDGE.labelFontSize);
  const labelX = $derived(mx + perpX * 0.4);
  const labelY = $derived(my + perpY * 0.4);
</script>

<path
  d="M{startPt.x},{startPt.y} C{startPt.x + dx * 0.35 + perpX},{startPt.y + dy * 0.35 + perpY} {endPt.x - dx * 0.35 + perpX},{endPt.y - dy * 0.35 + perpY} {endPt.x},{endPt.y}"
  fill="none" stroke={edge.color}
  stroke-width={EDGE.strokeWidth} opacity={EDGE.opacity}
  marker-end="url(#arrow-{edge.color.replace('#', '')})"
/>

{#if edge.label}
  <rect
    x={labelX - labelW / 2} y={labelY - labelH / 2}
    width={labelW} height={labelH}
    rx={EDGE.labelRadius}
    fill="var(--bg-s)" stroke="var(--bdr)" stroke-width="1"
  />
  <text
    x={labelX} y={labelY + 4}
    text-anchor="middle" fill={edge.color}
    font-size={EDGE.labelFontSize} font-weight="500"
  >{edge.label}</text>
{/if}
