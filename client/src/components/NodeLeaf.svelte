<script>
  /**
   * Node card — matches study-tutor visual style.
   * Colored background per depth/subsystem, centered text, status border,
   * left depth band, status badge pill, confidence dots.
   */
  import { depthColor, statusColor, DEPTH_BG_COLORS, DEPTH_TEXT_COLORS } from '../lib/config.js';

  let {
    node,      // from registry: label, subtitle, status, depth, confidence, etc.
    tabNode,   // from tab: row, col, color, textColor overrides
    pos,       // computed position: {x, y, w, h}
    isSelected = false,
    comments = [],
    onselect,
    onstartdrag,
    oncontextmenu,
  } = $props();

  const dc = $derived(depthColor(node.depth));
  const sc = $derived(statusColor(node.status));
  // Use tab-level color overrides, then depth defaults
  const bgColor = $derived(tabNode?.color || node.color || DEPTH_BG_COLORS[node.depth] || '#1e293b');
  const txtColor = $derived(tabNode?.textColor || node.textColor || DEPTH_TEXT_COLORS[node.depth] || '#94a3b8');
  const hasComments = $derived(comments.length > 0);

  // Status border color
  const borderColor = $derived(
    hasComments ? '#3b82f6'
    : node.hasWorkaround ? '#f97316'
    : node.status === 'done' ? '#10b981'
    : node.status === 'in-progress' ? '#eab308'
    : node.status === 'blocked' ? '#ef4444'
    : '#0002'
  );
  const borderW = $derived((hasComments || node.status !== 'planned') ? '2.5' : '1');

  // Status badge text
  const badgeText = $derived(node.status === 'in-progress' ? 'in prog' : node.status);
  const badgeW = $derived(badgeText.length * 6.5 + 16);
  const depthLabel = $derived((node.depth || 'module')[0].toUpperCase());
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
  <!-- Selection outline — bright and obvious -->
  {#if isSelected}
    <rect
      x={pos.x - 3} y={pos.y - 3}
      width={pos.w + 6} height={pos.h + 6}
      rx="11" fill="none" stroke="#60a5fa"
      stroke-width="3"
    />
  {/if}

  <!-- Node background — semantic color per subsystem -->
  <rect
    x={pos.x} y={pos.y}
    width={pos.w} height={pos.h}
    rx="8" fill={bgColor}
    stroke={borderColor} stroke-width={borderW}
  />

  <!-- Left depth color band (G10) -->
  <rect
    x={pos.x} y={pos.y + 1}
    width="5" height={pos.h - 2}
    rx="3" fill={dc} opacity=".6"
  />

  <!-- Title (centered, larger) -->
  <text
    x={pos.x + pos.w / 2} y={pos.y + 28}
    text-anchor="middle" fill={txtColor}
    font-size="14" font-weight="600"
  >{node.label}</text>

  <!-- Subtitle (centered — truncation scales with node width) -->
  {#if node.subtitle}
    {@const maxChars = Math.floor((pos.w - 40) / 6.5)}
    <text
      x={pos.x + pos.w / 2} y={pos.y + 46}
      text-anchor="middle" fill={txtColor}
      font-size="11" opacity=".7"
    >{node.subtitle.length > maxChars ? node.subtitle.slice(0, maxChars - 2) + '...' : node.subtitle}</text>
  {/if}

  <!-- Status badge pill (G9) -->
  <rect
    x={pos.x + pos.w - badgeW - 8} y={pos.y + 6}
    width={badgeW} height="18" rx="9"
    fill={sc} fill-opacity=".2"
  />
  <text
    x={pos.x + pos.w - badgeW / 2 - 8} y={pos.y + 18}
    text-anchor="middle" fill={sc}
    font-size="10" font-weight="600"
  >{badgeText}</text>

  <!-- Depth badge (top left) -->
  <rect x={pos.x + 8} y={pos.y + 6} width="18" height="16" rx="4" fill={dc} opacity=".25" />
  <text x={pos.x + 17} y={pos.y + 17} text-anchor="middle" fill={dc} font-size="10" font-weight="600">{depthLabel}</text>

  <!-- Workaround warning -->
  {#if node.hasWorkaround}
    <text x={pos.x + 32} y={pos.y + 17} fill="#f97316" font-size="12">&#9888;</text>
  {/if}

  <!-- Status pill already shows "done" — no redundant checkmark needed -->

  <!-- Comment badge with count -->
  {#if hasComments}
    <circle cx={pos.x + 14} cy={pos.y + pos.h - 12} r="7" fill="#3b82f6" opacity=".9" />
    <text
      x={pos.x + 14} y={pos.y + pos.h - 8}
      text-anchor="middle" fill="white" font-size="10" font-weight="600"
    >{comments.length}</text>
  {/if}

  <!-- Confidence dots (inside card bounds) -->
  {#each [0, 1, 2] as i}
    <circle
      cx={pos.x + pos.w - 30 + i * 9}
      cy={pos.y + pos.h - 10}
      r="3" fill={i < node.confidence ? dc : 'var(--bdr)'}
      opacity=".5"
    />
  {/each}
</g>
