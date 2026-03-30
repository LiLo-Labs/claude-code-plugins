<script>
  /**
   * Edge — renders a routed path from ELK layout or a simple bezier fallback.
   *
   * When ELK provides a route (array of points), renders a smooth spline through them.
   * When no route is available, falls back to a simple bezier between node centers.
   */
  import { EDGE, CONTAINER } from '../lib/config.js';

  let { edge, fromPos, toPos, route = null } = $props();

  // Generate SVG path from an array of points as a smooth cubic spline
  function pointsToSpline(pts) {
    if (!pts || pts.length < 2) return '';
    if (pts.length === 2) {
      return `M${pts[0].x},${pts[0].y} L${pts[1].x},${pts[1].y}`;
    }
    // Use cubic bezier through points
    let d = `M${pts[0].x},${pts[0].y}`;
    for (let i = 1; i < pts.length; i++) {
      const prev = pts[i - 1];
      const curr = pts[i];
      const mx = (prev.x + curr.x) / 2;
      const my = (prev.y + curr.y) / 2;
      if (i === 1) {
        d += ` Q${prev.x},${prev.y} ${mx},${my}`;
      } else {
        d += ` T${mx},${my}`;
      }
    }
    const last = pts[pts.length - 1];
    d += ` T${last.x},${last.y}`;
    return d;
  }

  // Fallback: simple bezier between node edges
  function fallbackPath() {
    const fromCx = fromPos.x + fromPos.w / 2;
    const fromCy = fromPos.y + (fromPos.isContainer ? CONTAINER.headerHeight / 2 : fromPos.h / 2);
    const toCx = toPos.x + toPos.w / 2;
    const toCy = toPos.y + (toPos.isContainer ? CONTAINER.headerHeight / 2 : toPos.h / 2);
    const dx = toCx - fromCx;

    let sx, sy, tx, ty;
    if (Math.abs(dx) > 20) {
      sx = dx > 0 ? fromPos.x + fromPos.w : fromPos.x;
      sy = fromCy;
      tx = dx > 0 ? toPos.x : toPos.x + toPos.w;
      ty = toCy;
    } else {
      sx = fromCx;
      sy = fromPos.y + fromPos.h;
      tx = toCx;
      ty = toPos.y;
    }
    const mx = (sx + tx) / 2;
    const my = (sy + ty) / 2;
    return `M${sx},${sy} C${mx},${sy} ${mx},${ty} ${tx},${ty}`;
  }

  const pathD = $derived(
    route && route.points && route.points.length >= 2
      ? pointsToSpline(route.points)
      : fallbackPath()
  );

  const labelPos = $derived(
    route && route.labelPos
      ? route.labelPos
      : (() => {
          const fromCx = fromPos.x + fromPos.w / 2;
          const toCx = toPos.x + toPos.w / 2;
          const fromCy = fromPos.y + fromPos.h / 2;
          const toCy = toPos.y + toPos.h / 2;
          return { x: (fromCx + toCx) / 2, y: (fromCy + toCy) / 2 };
        })()
  );

  const labelW = $derived(edge.label ? edge.label.length * 7 + EDGE.labelPaddingX * 2 : 0);
  const labelH = $derived(EDGE.labelPaddingY * 2 + EDGE.labelFontSize);
</script>

<path
  d={pathD}
  fill="none" stroke={edge.color}
  stroke-width={EDGE.strokeWidth} opacity={EDGE.opacity}
  marker-end="url(#arrow-{edge.color.replace('#', '')})"
/>

{#if edge.label}
  <rect
    x={labelPos.x - labelW / 2} y={labelPos.y - labelH / 2}
    width={labelW} height={labelH}
    rx={EDGE.labelRadius}
    fill="var(--bg-s)" stroke="var(--bdr)" stroke-width="1"
  />
  <text
    x={labelPos.x} y={labelPos.y + 4}
    text-anchor="middle" fill={edge.color}
    font-size={EDGE.labelFontSize} font-weight="500"
  >{edge.label}</text>
{/if}
