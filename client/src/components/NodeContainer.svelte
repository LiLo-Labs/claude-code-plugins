<script>
  /**
   * Container node — rendered when a parent is expanded.
   * Shows a tinted background wrapping children, with a header bar
   * containing the label, status dot, and collapse chevron.
   *
   * Border color matches the node's depth color.
   */
  import { CONTAINER, depthColor, statusColor, depthTint } from '../lib/config.js';

  let {
    node,
    pos,
    isSelected = false,
    isAncestor = false,
    ontoggle,
    ondeeptoggle,
    onselect,
  } = $props();

  const dc = $derived(depthColor(node.depth));
  const sc = $derived(statusColor(node.status));
  const bgTint = $derived(depthTint(node.depth, isAncestor ? CONTAINER.tintOpacityHighlight : CONTAINER.tintOpacity));
  const borderOp = $derived(isAncestor ? CONTAINER.borderOpacityHighlight : CONTAINER.borderOpacity);
  const headerCenterY = $derived(pos.y + CONTAINER.headerHeight / 2 + 5);
</script>

<!-- Container background -->
<rect
  x={pos.x} y={pos.y}
  width={pos.w} height={pos.h}
  rx={CONTAINER.borderRadius}
  fill={bgTint}
  stroke={dc}
  stroke-width={isSelected ? '2.5' : isAncestor ? '2' : '1.5'}
  stroke-opacity={borderOp}
/>

<!-- Selection outline -->
{#if isSelected}
  <rect
    x={pos.x - 4} y={pos.y - 4}
    width={pos.w + 8} height={pos.h + 8}
    rx="16" fill="none" stroke="#60a5fa"
    stroke-width="2.5" stroke-dasharray="6 3"
  />
{/if}

<!-- Header label (left-aligned) -->
<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<text
  x={pos.x + 16} y={headerCenterY}
  fill={dc} font-size={CONTAINER.headerFontSize} font-weight="700"
  style="cursor: pointer"
  onclick={(e) => onselect?.(node.id, e)}
>{node.label}</text>

<!-- Status dot -->
<circle cx={pos.x + pos.w - 22} cy={pos.y + CONTAINER.headerHeight / 2} r="5" fill={sc} />

<!-- Collapse chevron -->
<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
<text
  x={pos.x + pos.w - 38} y={headerCenterY}
  fill={dc} font-size="12" opacity=".6"
  style="cursor: pointer"
  onclick={() => ontoggle?.(node.id)}
  ondblclick={() => ondeeptoggle?.(node.id)}
>&#9660;</text>
