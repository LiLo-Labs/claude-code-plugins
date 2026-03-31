<script>
  /**
   * Actor node — UML stick figure style.
   * Stick figure icon with label below. Used for actors in use case diagrams.
   * Same props interface as NodeLeaf for drop-in switching.
   */
  import { depthColor, DEPTH_TEXT_COLORS } from '../lib/config.js';

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
  const txtColor = $derived(tabNode?.textColor || node.textColor || DEPTH_TEXT_COLORS[node.depth] || '#94a3b8');

  const cx = $derived(pos.x + pos.w / 2);
  const figureY = $derived(pos.y + 12);
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
      rx="8" fill="none" stroke="#c8d8f0" stroke-width="3"
    />
  {/if}

  <circle cx={cx} cy={figureY + 10} r="8" fill="none" stroke={dc} stroke-width="2" />
  <line x1={cx} y1={figureY + 18} x2={cx} y2={figureY + 38} stroke={dc} stroke-width="2" />
  <line x1={cx - 14} y1={figureY + 26} x2={cx + 14} y2={figureY + 26} stroke={dc} stroke-width="2" />
  <line x1={cx} y1={figureY + 38} x2={cx - 10} y2={figureY + 52} stroke={dc} stroke-width="2" />
  <line x1={cx} y1={figureY + 38} x2={cx + 10} y2={figureY + 52} stroke={dc} stroke-width="2" />

  <text
    x={cx} y={pos.y + pos.h - 4}
    text-anchor="middle" fill={txtColor}
    font-size="12" font-weight="600"
  >{node.label}</text>

  {#if comments.length > 0}
    <circle cx={pos.x + pos.w - 10} cy={pos.y + 10} r="7" fill="#3b82f6" opacity=".9" />
    <text
      x={pos.x + pos.w - 10} y={pos.y + 14}
      text-anchor="middle" fill="white" font-size="10" font-weight="600"
    >{comments.length}</text>
  {/if}
</g>
