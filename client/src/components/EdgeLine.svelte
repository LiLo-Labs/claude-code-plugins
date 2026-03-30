<script>
  /**
   * Edge — bezier curve between two positioned nodes with label pill and arrow.
   * Uses center-to-center routing with border clipping.
   */
  let { edge, fromPos, toPos } = $props();

  const NW = 280, NH = 90, CHDR = 40;

  // Center points of each node
  const fromCx = $derived(fromPos.x + (fromPos.isContainer ? fromPos.w / 2 : NW / 2));
  const fromCy = $derived(fromPos.y + (fromPos.isContainer ? fromPos.h / 2 : NH / 2));
  const toCx = $derived(toPos.x + (toPos.isContainer ? toPos.w / 2 : NW / 2));
  const toCy = $derived(toPos.y + (toPos.isContainer ? toPos.h / 2 : NH / 2));

  // Half-widths/heights for border clipping
  const fromHW = $derived((fromPos.isContainer ? fromPos.w : NW) / 2);
  const fromHH = $derived((fromPos.isContainer ? fromPos.h : NH) / 2);
  const toHW = $derived((toPos.isContainer ? toPos.w : NW) / 2);
  const toHH = $derived((toPos.isContainer ? toPos.h : NH) / 2);

  // Clip a line from center (cx,cy) toward target (tx,ty) at rectangle border
  function clipAtBorder(cx, cy, tx, ty, hw, hh) {
    const dx = tx - cx, dy = ty - cy;
    if (dx === 0 && dy === 0) return { x: cx, y: cy };
    const scaleX = hw / Math.abs(dx || 0.001);
    const scaleY = hh / Math.abs(dy || 0.001);
    const scale = Math.min(scaleX, scaleY);
    return { x: cx + dx * scale, y: cy + dy * scale };
  }

  // Clipped start/end points
  const startPt = $derived(clipAtBorder(fromCx, fromCy, toCx, toCy, fromHW, fromHH));
  const endPt = $derived(clipAtBorder(toCx, toCy, fromCx, fromCy, toHW + 4, toHH + 4));

  // Midpoint for label
  const mx = $derived((startPt.x + endPt.x) / 2);
  const my = $derived((startPt.y + endPt.y) / 2);

  // Bezier control points — curve slightly to avoid overlapping straight lines
  const dx = $derived(endPt.x - startPt.x);
  const dy = $derived(endPt.y - startPt.y);
  const curveFactor = $derived(Math.abs(dy) > Math.abs(dx) ? 0.2 : 0.15);
  const perpX = $derived(-dy * curveFactor);
  const perpY = $derived(dx * curveFactor);
  const cp1x = $derived(startPt.x + dx * 0.35 + perpX);
  const cp1y = $derived(startPt.y + dy * 0.35 + perpY);
  const cp2x = $derived(endPt.x - dx * 0.35 + perpX);
  const cp2y = $derived(endPt.y - dy * 0.35 + perpY);

  // Label dimensions — generous padding
  const labelW = $derived(edge.label ? edge.label.length * 8 + 24 : 0);
  const labelH = 24;

  // Label position — offset from midpoint along the perpendicular to avoid overlapping the edge
  const labelX = $derived(mx + perpX * 0.5);
  const labelY = $derived(my + perpY * 0.5);
</script>

<!-- Edge path -->
<path
  d="M{startPt.x},{startPt.y} C{cp1x},{cp1y} {cp2x},{cp2y} {endPt.x},{endPt.y}"
  fill="none" stroke={edge.color} stroke-width="2" opacity=".65"
  marker-end="url(#arrow-{edge.color.replace('#', '')})"
/>

<!-- Label pill -->
{#if edge.label}
  <rect
    x={labelX - labelW / 2} y={labelY - labelH / 2}
    width={labelW} height={labelH}
    rx="12" fill="var(--bg-s)" stroke="var(--bdr)" stroke-width="1"
  />
  <text
    x={labelX} y={labelY + 4}
    text-anchor="middle" fill={edge.color}
    font-size="11" font-weight="500"
  >{edge.label}</text>
{/if}
