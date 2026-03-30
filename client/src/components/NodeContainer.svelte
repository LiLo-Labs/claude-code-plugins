<script>
  /**
   * Container node — rendered when a parent is expanded.
   * Shows: tinted background, header with label, status dot, collapse chevron.
   */
  let { node, pos, isSelected = false, isAncestor = false, ontoggle, ondeeptoggle, onselect } = $props();

  const DEPTH_COLORS = { system: '#3b82f6', domain: '#a855f7', module: '#14b8a6', 'interface': '#f97316' };
  const STATUS_COLORS = { done: '#10b981', 'in-progress': '#eab308', planned: '#3b82f6', placeholder: '#64748b' };
  const TINTS = { system: 'rgba(59,130,246,', domain: 'rgba(168,85,247,', module: 'rgba(20,184,166,', 'interface': 'rgba(249,115,22,' };

  const dc = $derived(DEPTH_COLORS[node.depth] || '#64748b');
  const sc = $derived(STATUS_COLORS[node.status] || '#64748b');
  const tint = $derived(TINTS[node.depth] || 'rgba(100,100,100,');
</script>

<!-- Container background -->
<rect
  x={pos.x} y={pos.y} width={pos.w} height={pos.h}
  rx="14" fill="{tint}{isAncestor ? '.08)' : '.04)'}"
  stroke={dc} stroke-width={isAncestor ? '2' : '1'}
  stroke-opacity={isAncestor ? '.5' : '.2'}
/>

{#if isSelected}
  <rect
    x={pos.x - 4} y={pos.y - 4} width={pos.w + 8} height={pos.h + 8}
    rx="16" fill="none" stroke="#60a5fa" stroke-width="2" stroke-dasharray="6 3"
  />
{/if}

<!-- Header label -->
<text
  x={pos.x + 14} y={pos.y + 24}
  fill={dc} font-size="14" font-weight="700" opacity=".9"
  style="cursor: pointer"
  onclick={(e) => onselect?.(node.id, e)}
>{node.label}</text>

<!-- Status dot -->
<circle cx={pos.x + pos.w - 20} cy={pos.y + 20} r="4" fill={sc} />

<!-- Collapse chevron -->
<text
  x={pos.x + pos.w - 36} y={pos.y + 24}
  fill={dc} font-size="12" opacity=".6"
  style="cursor: pointer"
  onclick={() => ontoggle?.(node.id)}
  ondblclick={() => ondeeptoggle?.(node.id)}
>&#9660;</text>
