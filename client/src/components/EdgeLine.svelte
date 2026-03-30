<script>
  /**
   * Edge — quadratic bezier curve between two nodes.
   * Clips at node borders, curves with perpendicular offset.
   * Matches the study-tutor canvas edge style.
   */
  import { computeEdgePath } from '../lib/layout.js';

  let { edge, fromPos, toPos } = $props();

  const edgePath = $derived(computeEdgePath(fromPos, toPos));
  const labelW = $derived(edge.label ? edge.label.length * 7.5 + 24 : 0);
</script>

<!-- Edge path — quadratic bezier -->
<path
  d={edgePath.path}
  fill="none" stroke={edge.color}
  stroke-width="2" stroke-opacity=".7"
  marker-end="url(#arrow-{edge.color.replace('#', '')})"
/>

<!-- Label pill -->
{#if edge.label}
  <rect
    x={edgePath.labelX - labelW / 2}
    y={edgePath.labelY - 14}
    width={labelW} height="24" rx="6"
    fill="var(--bg-s)" opacity=".95"
  />
  <text
    x={edgePath.labelX}
    y={edgePath.labelY}
    text-anchor="middle" fill={edge.color}
    font-size="12" font-weight="500"
  >{edge.label}</text>
{/if}
