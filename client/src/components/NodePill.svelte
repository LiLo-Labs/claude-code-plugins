<script>
  /**
   * Pill node — fully rounded ends, compact label.
   * For sequence diagram participants, tags, minimal labels.
   * Same props interface as NodeLeaf.
   */
  import { depthColor, DEPTH_BG_COLORS, DEPTH_TEXT_COLORS } from '../lib/config.js';

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
  const bgColor = $derived(tabNode?.color || node.color || DEPTH_BG_COLORS[node.depth] || '#1e293b');
  const txtColor = $derived(tabNode?.textColor || node.textColor || DEPTH_TEXT_COLORS[node.depth] || '#94a3b8');
  const ry = $derived(pos.h / 2);
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
      rx={ry + 3} fill="none" stroke="#c8d8f0" stroke-width="3"
    />
  {/if}

  <rect
    x={pos.x} y={pos.y}
    width={pos.w} height={pos.h}
    rx={ry} fill={bgColor}
    stroke={dc} stroke-width="1.5"
  />

  <text
    x={pos.x + pos.w / 2} y={pos.y + pos.h / 2 + 5}
    text-anchor="middle" fill={txtColor}
    font-size="13" font-weight="600"
  >{node.label}</text>

  {#if comments.length > 0}
    <circle cx={pos.x + pos.w - 8} cy={pos.y + 8} r="6" fill="#3b82f6" opacity=".9" />
    <text
      x={pos.x + pos.w - 8} y={pos.y + 12}
      text-anchor="middle" fill="white" font-size="9" font-weight="600"
    >{comments.length}</text>
  {/if}
</g>
