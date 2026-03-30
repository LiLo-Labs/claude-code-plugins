<script>
  /**
   * Node — a single card on the canvas.
   * Matches the study-tutor visual style: colored background, centered text,
   * status-colored border, title + subtitle.
   */
  import { depthColor, statusColor } from '../lib/config.js';

  let {
    node,
    pos,
    isSelected = false,
    comments = [],
    onselect,
    onstartdrag,
  } = $props();

  const dc = $derived(depthColor(node.depth));
  const sc = $derived(statusColor(node.status));
  const textColor = $derived(node.textColor || '#e2e8f0'); // always light for readability on dark nodes
  const hasComments = $derived(comments.length > 0);
  const strokeColor = $derived(
    hasComments ? '#3b82f6'
    : node.hasWorkaround ? '#f97316'
    : node.status === 'done' ? '#10b981'
    : node.status === 'in-progress' ? '#eab308'
    : node.status === 'blocked' ? '#ef4444'
    : dc + '40'
  );
  const strokeW = $derived((hasComments || node.status !== 'planned') ? '2.5' : '1');
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<g
  data-node={node.id}
  style="cursor: grab"
  onmousedown={(e) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    onselect?.(node.id, e);
    onstartdrag?.(node.id, e);
  }}
>
  <!-- Selection outline -->
  {#if isSelected}
    <rect
      x={pos.x - 4} y={pos.y - 4}
      width={pos.w + 8} height={pos.h + 8}
      rx="12" fill="none" stroke="#60a5fa"
      stroke-width="2.5" stroke-dasharray="6 3"
    />
  {/if}

  <!-- Node background -->
  <rect
    x={pos.x} y={pos.y}
    width={pos.w} height={pos.h}
    rx="8" fill={dc}
    stroke={strokeColor} stroke-width={strokeW}
  />

  <!-- Title (centered) -->
  <text
    x={pos.x + pos.w / 2} y={node.subtitle ? pos.y + 22 : pos.y + pos.h / 2 + 5}
    text-anchor="middle" fill={textColor}
    font-size="13" font-weight="600"
  >{node.label}</text>

  <!-- Subtitle (centered, below title) -->
  {#if node.subtitle}
    <text
      x={pos.x + pos.w / 2} y={pos.y + 38}
      text-anchor="middle" fill={textColor}
      font-size="10" opacity=".7"
    >{node.subtitle.length > 36 ? node.subtitle.slice(0, 34) + '...' : node.subtitle}</text>
  {/if}

  <!-- Status checkmark for done -->
  {#if node.status === 'done'}
    <text x={pos.x + 12} y={pos.y + 18} fill="#10b981" font-size="14">&#10003;</text>
  {/if}

  <!-- Workaround warning -->
  {#if node.hasWorkaround}
    <text x={pos.x + pos.w - 18} y={pos.y + 16} fill="#f97316" font-size="13">&#9888;</text>
  {/if}

  <!-- Comment indicator -->
  {#if hasComments}
    <circle cx={pos.x + pos.w - 10} cy={pos.y + 10} r="5" fill="#3b82f6" />
  {/if}

  <!-- Confidence dots (bottom right, compact) -->
  {#each [0, 1, 2] as i}
    <circle
      cx={pos.x + pos.w - 18 + i * 7}
      cy={pos.y + pos.h - 8}
      r="2.5" fill={i < node.confidence ? dc : 'var(--bdr)'}
      opacity=".6"
    />
  {/each}
</g>
