<script>
  /**
   * Edge — orthogonal-style routing between nodes.
   *
   * Determines which sides to exit/enter based on relative positions:
   * - Horizontal: exit right side → enter left side (with a mid-point dogleg)
   * - Vertical: exit bottom → enter top
   * - Mixed: combination with rounded corners
   *
   * All sizing from shared config.
   */
  import { EDGE, CONTAINER } from '../lib/config.js';

  let { edge, fromPos, toPos } = $props();

  // Node centers and bounds
  const fromCx = $derived(fromPos.x + fromPos.w / 2);
  const fromCy = $derived(fromPos.y + (fromPos.isContainer ? CONTAINER.headerHeight / 2 : fromPos.h / 2));
  const toCx = $derived(toPos.x + toPos.w / 2);
  const toCy = $derived(toPos.y + (toPos.isContainer ? CONTAINER.headerHeight / 2 : toPos.h / 2));

  // Determine primary direction and compute path
  const pathD = $derived(() => {
    const dx = toCx - fromCx;
    const dy = toCy - fromCy;
    const absDx = Math.abs(dx);
    const absDy = Math.abs(dy);

    // Source and target edge points
    let sx, sy, tx, ty;

    if (absDx > absDy * 0.5) {
      // Primarily horizontal — exit right/left sides
      if (dx > 0) {
        sx = fromPos.x + fromPos.w;
        sy = fromCy;
        tx = toPos.x;
        ty = toCy;
      } else {
        sx = fromPos.x;
        sy = fromCy;
        tx = toPos.x + toPos.w;
        ty = toCy;
      }
      // Horizontal path with midpoint dogleg
      const midX = (sx + tx) / 2;
      return `M${sx},${sy} C${midX},${sy} ${midX},${ty} ${tx},${ty}`;
    } else {
      // Primarily vertical — exit bottom/top
      if (dy > 0) {
        sx = fromCx;
        sy = fromPos.y + (fromPos.isContainer ? fromPos.h : fromPos.h);
        tx = toCx;
        ty = toPos.y;
      } else {
        sx = fromCx;
        sy = fromPos.y;
        tx = toCx;
        ty = toPos.y + (toPos.isContainer ? toPos.h : toPos.h);
      }
      // Vertical path with midpoint dogleg
      const midY = (sy + ty) / 2;
      return `M${sx},${sy} C${sx},${midY} ${tx},${midY} ${tx},${ty}`;
    }
  });

  // Label position at midpoint
  const labelPos = $derived(() => {
    const dx = toCx - fromCx;
    const dy = toCy - fromCy;
    if (Math.abs(dx) > Math.abs(dy) * 0.5) {
      const sx = dx > 0 ? fromPos.x + fromPos.w : fromPos.x;
      const tx = dx > 0 ? toPos.x : toPos.x + toPos.w;
      return { x: (sx + tx) / 2, y: (fromCy + toCy) / 2 };
    } else {
      const sy = dy > 0 ? fromPos.y + fromPos.h : fromPos.y;
      const ty = dy > 0 ? toPos.y : toPos.y + toPos.h;
      return { x: (fromCx + toCx) / 2, y: (sy + ty) / 2 };
    }
  });

  const labelW = $derived(edge.label ? edge.label.length * 7 + EDGE.labelPaddingX * 2 : 0);
  const labelH = $derived(EDGE.labelPaddingY * 2 + EDGE.labelFontSize);
</script>

<path
  d={pathD()}
  fill="none" stroke={edge.color}
  stroke-width={EDGE.strokeWidth} opacity={EDGE.opacity}
  marker-end="url(#arrow-{edge.color.replace('#', '')})"
/>

{#if edge.label}
  {@const lp = labelPos()}
  <rect
    x={lp.x - labelW / 2} y={lp.y - labelH / 2}
    width={labelW} height={labelH}
    rx={EDGE.labelRadius}
    fill="var(--bg-s)" stroke="var(--bdr)" stroke-width="1"
  />
  <text
    x={lp.x} y={lp.y + 4}
    text-anchor="middle" fill={edge.color}
    font-size={EDGE.labelFontSize} font-weight="500"
  >{edge.label}</text>
{/if}
