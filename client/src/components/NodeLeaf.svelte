<script>
  /**
   * Leaf node — rendered when a node has no visible expanded children.
   * Shows: title, status badge, confidence dots, color band, comment badge,
   * collapsed child preview, workaround warning, flesh-out prompt.
   */
  let { node, pos, isSelected = false, isAncestor = false, children = [], comments = [], onselect, ontoggle, ondeeptoggle } = $props();

  const NW = 280, NH = 90;

  const DEPTH_COLORS = { system: '#3b82f6', domain: '#a855f7', module: '#14b8a6', 'interface': '#f97316' };
  const STATUS_COLORS = { done: '#10b981', 'in-progress': '#eab308', planned: '#3b82f6', placeholder: '#64748b' };

  const dc = $derived(DEPTH_COLORS[node.depth] || '#64748b');
  const sc = $derived(STATUS_COLORS[node.status] || '#64748b');
  const hasChildren = $derived(children.length > 0);
  const badgeW = $derived(node.status.length * 6.5 + 14);
  const titleX = $derived(pos.x + (hasChildren ? 30 : 14));
</script>

<g style="cursor: grab" onmousedown={(e) => { if (e.button === 0) onselect?.(node.id, e); }}>
  <!-- Depth glow -->
  <rect
    x={pos.x - 3} y={pos.y - 3} width={NW + 6} height={NH + 6}
    rx="12" fill="none" stroke={dc}
    stroke-width={isAncestor ? '2.5' : '1.5'}
    opacity={isAncestor ? '.6' : '.2'}
  />

  <!-- Selection outline -->
  {#if isSelected}
    <rect
      x={pos.x - 5} y={pos.y - 5} width={NW + 10} height={NH + 10}
      rx="14" fill="none" stroke="#60a5fa" stroke-width="2" stroke-dasharray="6 3"
    />
  {/if}

  <!-- Background -->
  <rect
    x={pos.x} y={pos.y} width={NW} height={NH} rx="10"
    fill={node.confidence === 0 ? 'url(#hatch)' : 'var(--bg-n)'}
    stroke={node.hasWorkaround ? '#f97316' : node.confidence <= 1 ? dc : 'var(--bdr)'}
    stroke-width={node.hasWorkaround ? '2.5' : '1'}
    stroke-dasharray={node.confidence <= 1 && !node.hasWorkaround ? (node.confidence === 0 ? '6 4' : '4 3') : 'none'}
  />

  <!-- Color band -->
  <rect x={pos.x} y={pos.y} width="5" height={NH} rx="2" fill={dc} opacity=".6" />

  <!-- Workaround icon -->
  {#if node.hasWorkaround}
    <text x={pos.x + NW - 20} y={pos.y + 16} fill="#f97316" font-size="13">&#9888;</text>
  {/if}

  <!-- Expand chevron (for collapsed parents) -->
  {#if hasChildren}
    <text
      x={pos.x + 14} y={pos.y + 32} fill="var(--tx-d)" font-size="11"
      style="cursor: pointer"
      onclick={(e) => { e.stopPropagation(); ontoggle?.(node.id); }}
      ondblclick={(e) => { e.stopPropagation(); ondeeptoggle?.(node.id); }}
    >&#9654;</text>
  {/if}

  <!-- Title -->
  <text x={titleX} y={pos.y + 30} fill="var(--tx)" font-size="14" font-weight="600">
    {node.label}
  </text>

  <!-- Status badge -->
  <rect
    x={pos.x + NW - badgeW - 10} y={pos.y + 6}
    width={badgeW} height="18" rx="9"
    fill={sc} fill-opacity=".15"
  />
  <text
    x={pos.x + NW - badgeW / 2 - 10} y={pos.y + 18}
    text-anchor="middle" fill={sc} font-size="10" font-weight="600"
  >{node.status}</text>

  <!-- Confidence dots -->
  {#each [0, 1, 2] as i}
    <circle cx={pos.x + NW - 22 + i * 10} cy={pos.y + NH - 14} r="4" fill={i < node.confidence ? dc : 'var(--bdr)'} />
  {/each}

  <!-- Comment badge -->
  {#if comments.length > 0}
    <circle cx={pos.x + 16} cy={pos.y + NH - 14} r="7" fill="#3b82f6" />
    <text x={pos.x + 16} y={pos.y + NH - 10.5} text-anchor="middle" fill="white" font-size="10" font-weight="700">{comments.length}</text>
  {/if}

  <!-- Collapsed child preview -->
  {#if hasChildren}
    <text x={pos.x + 14} y={pos.y + NH - 10} fill="var(--tx-d)" font-size="10">{children.length} children</text>
    {#each children.slice(0, 6) as child, i}
      <circle cx={pos.x + 95 + i * 10} cy={pos.y + NH - 14} r="3.5" fill={STATUS_COLORS[child.status] || '#64748b'} />
    {/each}
  {/if}

  <!-- Flesh out prompt -->
  {#if node.confidence === 0}
    <text x={pos.x + NW / 2} y={pos.y + 58} text-anchor="middle" fill="var(--ac)" font-size="10" font-style="italic" style="cursor: pointer">
      Flesh out &#8594;
    </text>
  {/if}
</g>
