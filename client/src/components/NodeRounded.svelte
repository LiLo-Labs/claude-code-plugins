<script>
  /**
   * Rounded node — state machine style.
   * Heavily rounded rectangle, centered label, status as fill tint.
   * Same props interface as NodeLeaf.
   */
  import { depthColor, statusColor, DEPTH_BG_COLORS, DEPTH_TEXT_COLORS } from '../lib/config.js';

  let {
    node,
    tabNode,
    pos,
    isSelected = false,
    comments = [],
    onselect,
    onstartdrag,
    oncontextmenu,
  } = $props();

  const dc = $derived(depthColor(node.depth));
  const sc = $derived(statusColor(node.status));
  const bgColor = $derived(tabNode?.color || node.color || DEPTH_BG_COLORS[node.depth] || '#1e293b');
  const txtColor = $derived(tabNode?.textColor || node.textColor || DEPTH_TEXT_COLORS[node.depth] || '#94a3b8');

  const cx = $derived(pos.x + pos.w / 2);
  const cy = $derived(pos.y + pos.h / 2);
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
  oncontextmenu={(e) => {
    e.preventDefault();
    e.stopPropagation();
    oncontextmenu?.(node.id, e);
  }}
>
  {#if isSelected}
    <rect
      x={pos.x - 3} y={pos.y - 3}
      width={pos.w + 6} height={pos.h + 6}
      rx="23" fill="none" stroke="#c8d8f0" stroke-width="3"
    />
  {/if}

  <rect
    x={pos.x} y={pos.y}
    width={pos.w} height={pos.h}
    rx="20" fill={bgColor}
    stroke={dc} stroke-width="1.5"
  />

  <text
    x={cx} y={node.subtitle ? cy - 2 : cy + 5}
    text-anchor="middle" fill={txtColor}
    font-size="13" font-weight="600"
  >{node.label}</text>

  {#if node.subtitle}
    <text
      x={cx} y={cy + 14}
      text-anchor="middle" fill={txtColor}
      font-size="10" opacity=".7"
    >{node.subtitle}</text>
  {/if}

  <circle cx={pos.x + pos.w - 14} cy={pos.y + 14} r="5" fill={sc} />

  {#if comments.length > 0}
    <circle cx={pos.x + 14} cy={pos.y + pos.h - 14} r="7" fill="#3b82f6" opacity=".9" />
    <text
      x={pos.x + 14} y={pos.y + pos.h - 10}
      text-anchor="middle" fill="white" font-size="10" font-weight="600"
    >{comments.length}</text>
  {/if}
</g>
