<script>
  /**
   * Ellipse node — UML use case style.
   * Horizontal oval with centered label. Subtitle shown below label in smaller text.
   * Same props interface as NodeLeaf for drop-in switching.
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
  const rx = $derived(pos.w / 2);
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
    <ellipse
      cx={cx} cy={cy} rx={rx + 4} ry={ry + 4}
      fill="none" stroke="#c8d8f0" stroke-width="3"
    />
  {/if}

  <ellipse
    cx={cx} cy={cy} rx={rx} ry={ry}
    fill={bgColor} stroke={dc} stroke-width="1.5"
  />

  <text
    x={cx} y={node.subtitle ? cy - 4 : cy + 5}
    text-anchor="middle" fill={txtColor}
    font-size="13" font-weight="600"
  >{node.label}</text>

  {#if node.subtitle}
    {@const maxChars = Math.floor((pos.w - 40) / 6.5)}
    <text
      x={cx} y={cy + 14}
      text-anchor="middle" fill={txtColor}
      font-size="10" opacity=".7"
    >{node.subtitle.length > maxChars ? node.subtitle.slice(0, maxChars - 2) + '...' : node.subtitle}</text>
  {/if}

  <circle cx={cx + rx - 12} cy={cy - ry + 12} r="5" fill={sc} />

  {#if comments.length > 0}
    <circle cx={cx - rx + 12} cy={cy + ry - 12} r="7" fill="#3b82f6" opacity=".9" />
    <text
      x={cx - rx + 12} y={cy + ry - 8}
      text-anchor="middle" fill="white" font-size="10" font-weight="600"
    >{comments.length}</text>
  {/if}
</g>
