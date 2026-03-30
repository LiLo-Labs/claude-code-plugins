<script>
  /**
   * Edge — bezier curve between two nodes with label pill and arrow marker.
   */
  let { edge, fromPos, toPos } = $props();

  const NW = 280, NH = 90, CHDR = 40;

  const fx = $derived(fromPos.x + (fromPos.isContainer ? fromPos.w : NW));
  const fy = $derived(fromPos.y + (fromPos.isContainer ? CHDR / 2 : NH / 2));
  const tx = $derived(toPos.x);
  const ty = $derived(toPos.y + (toPos.isContainer ? CHDR / 2 : NH / 2));
  const mx = $derived((fx + tx) / 2);
  const my = $derived((fy + ty) / 2);
  const labelW = $derived(edge.label ? edge.label.length * 7 + 14 : 0);
</script>

<path
  d="M{fx},{fy} C{fx + (tx - fx) * 0.5},{fy} {tx - (tx - fx) * 0.5},{ty} {tx},{ty}"
  fill="none" stroke={edge.color} stroke-width="2" opacity=".65"
  marker-end="url(#arrow-{edge.color.replace('#', '')})"
/>

{#if edge.label}
  <rect
    x={mx - labelW / 2} y={my - 10} width={labelW} height="20"
    rx="10" fill="var(--bg-s)" stroke="var(--bdr)" stroke-width="1"
  />
  <text x={mx} y={my + 4} text-anchor="middle" fill={edge.color} font-size="11" font-weight="500">
    {edge.label}
  </text>
{/if}
