<script>
  /**
   * Leaf node — a single node card on the canvas.
   * Shows: title (centered), subtitle, status badge, confidence dots,
   * depth-colored border, comment badge, collapsed child preview.
   *
   * All sizing from shared config — no hardcoded values.
   */
  import { NODE, depthColor, statusColor } from '../lib/config.js';

  let {
    node,
    pos,
    isSelected = false,
    isAncestor = false,
    children = [],
    comments = [],
    onselect,
    ontoggle,
    ondeeptoggle,
  } = $props();

  const dc = $derived(depthColor(node.depth));
  const sc = $derived(statusColor(node.status));
  const hasChildren = $derived(children.length > 0);
  const hasSubtitle = $derived(!!node.subtitle);

  // Vertical centering
  const titleY = $derived(hasSubtitle ? pos.y + pos.h * 0.4 : pos.y + pos.h * 0.5 + 5);
  const subtitleY = $derived(pos.y + pos.h * 0.4 + NODE.subtitleSize + 6);
  const centerX = $derived(pos.x + pos.w / 2);

  // Status badge sizing
  const badgeText = $derived(node.status);
  const badgeW = $derived(badgeText.length * 6.5 + 16);
</script>

<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<g
  style="cursor: grab"
  onmousedown={(e) => { if (e.button === 0) onselect?.(node.id, e); }}
>
  <!-- Selection outline -->
  {#if isSelected}
    <rect
      x={pos.x - 4} y={pos.y - 4}
      width={pos.w + 8} height={pos.h + 8}
      rx="14" fill="none" stroke="#60a5fa"
      stroke-width="2.5" stroke-dasharray="6 3"
    />
  {/if}

  <!-- Node background with depth-colored border -->
  <rect
    x={pos.x} y={pos.y}
    width={pos.w} height={pos.h}
    rx={NODE.borderRadius}
    fill={node.confidence === 0 ? 'url(#hatch)' : 'var(--bg-n)'}
    stroke={node.hasWorkaround ? '#f97316' : dc}
    stroke-width={node.hasWorkaround ? '2.5' : isAncestor ? '2' : '1.5'}
    stroke-opacity={isAncestor ? '.8' : node.confidence <= 1 ? '.6' : '.4'}
    stroke-dasharray={node.confidence <= 1 && !node.hasWorkaround ? (node.confidence === 0 ? '6 4' : '4 3') : 'none'}
  />

  <!-- Workaround icon -->
  {#if node.hasWorkaround}
    <text x={pos.x + 10} y={pos.y + 16} fill="#f97316" font-size="13">&#9888;</text>
  {/if}

  <!-- Expand chevron (collapsed parent with children) -->
  {#if hasChildren}
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <text
      x={pos.x + 12} y={titleY + 1}
      fill="var(--tx-d)" font-size="11"
      style="cursor: pointer"
      onclick={(e) => { e.stopPropagation(); ontoggle?.(node.id); }}
      ondblclick={(e) => { e.stopPropagation(); ondeeptoggle?.(node.id); }}
    >&#9654;</text>
  {/if}

  <!-- Title (centered) -->
  <text
    x={centerX} y={titleY}
    text-anchor="middle"
    fill="var(--tx)" font-size={NODE.titleSize} font-weight="600"
  >{node.label}</text>

  <!-- Subtitle (centered, below title) -->
  {#if hasSubtitle}
    <text
      x={centerX} y={subtitleY}
      text-anchor="middle"
      fill="var(--tx-m)" font-size={NODE.subtitleSize}
    >{node.subtitle.length > 40 ? node.subtitle.slice(0, 38) + '...' : node.subtitle}</text>
  {/if}

  <!-- Status badge (top right) -->
  <rect
    x={pos.x + pos.w - badgeW - 8} y={pos.y + 6}
    width={badgeW} height="18" rx="9"
    fill={sc} fill-opacity=".15"
  />
  <text
    x={pos.x + pos.w - badgeW / 2 - 8} y={pos.y + 18}
    text-anchor="middle" fill={sc} font-size="10" font-weight="600"
  >{badgeText}</text>

  <!-- Confidence dots (bottom right) -->
  {#each [0, 1, 2] as i}
    <circle
      cx={pos.x + pos.w - 20 + i * 10}
      cy={pos.y + pos.h - 12}
      r="4" fill={i < node.confidence ? dc : 'var(--bdr)'}
    />
  {/each}

  <!-- Comment badge (bottom left) -->
  {#if comments.length > 0}
    <circle cx={pos.x + 16} cy={pos.y + pos.h - 12} r="7" fill="#3b82f6" />
    <text
      x={pos.x + 16} y={pos.y + pos.h - 8.5}
      text-anchor="middle" fill="white" font-size="10" font-weight="700"
    >{comments.length}</text>
  {/if}

  <!-- Collapsed child preview -->
  {#if hasChildren}
    <text x={pos.x + 30} y={pos.y + pos.h - 8} fill="var(--tx-d)" font-size="10">
      {children.length} children
    </text>
    {#each children.slice(0, 6) as child, i}
      <circle
        cx={pos.x + 105 + i * 12}
        cy={pos.y + pos.h - 12}
        r="3.5" fill={statusColor(child.status)}
      />
    {/each}
  {/if}

  <!-- Flesh out prompt for placeholders -->
  {#if node.confidence === 0}
    <text
      x={centerX} y={pos.y + pos.h - 8}
      text-anchor="middle" fill="var(--ac)"
      font-size="10" font-style="italic" style="cursor: pointer"
    >Flesh out &#8594;</text>
  {/if}
</g>
