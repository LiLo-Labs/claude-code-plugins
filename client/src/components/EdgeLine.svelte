<script>
  /**
   * Edge — quadratic bezier between two nodes.
   * Matches study-tutor style: clip at borders, curved path, labeled pill.
   */
  import { computeEdgePath } from '../lib/layout.js';

  let { edge, fromPos, toPos, shapes = {} } = $props();

  const color = $derived(edge.color || '#64748b');
  const edgePath = $derived(computeEdgePath(fromPos, toPos, shapes));
  const labelW = $derived(edge.label ? edge.label.length * 7.5 + 24 : 0);
</script>

<path
  d={edgePath.path}
  fill="none" stroke={color}
  stroke-width="2" stroke-opacity=".7"
  marker-end="url(#arrow-{color.toLowerCase().replace('#', '')})"
/>

{#if edge.label}
  <rect
    x={edgePath.labelX - labelW / 2}
    y={edgePath.labelY - 10}
    width={labelW} height="20" rx="10"
    fill="var(--bg-s)" stroke="var(--bdr)" stroke-width="1"
    opacity=".95"
  />
  <text
    x={edgePath.labelX}
    y={edgePath.labelY + 4}
    text-anchor="middle" fill={color}
    font-size="11" font-weight="500"
  >{edge.label}</text>
{/if}
