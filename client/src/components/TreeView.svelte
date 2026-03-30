<script>
  let { nodes, expandedNodes, selectedIds, onselect, ontoggle, ondeeptoggle } = $props();

  const DEPTH_COLORS = { system: '#3b82f6', domain: '#a855f7', module: '#14b8a6', 'interface': '#f97316' };
  const STATUS_COLORS = { done: '#10b981', 'in-progress': '#eab308', planned: '#3b82f6', placeholder: '#64748b' };

  const roots = $derived([...nodes.values()].filter(n => !n.parent));

  function getChildren(nodeId) {
    return [...nodes.values()].filter(n => n.parent === nodeId);
  }
</script>

<div class="tree">
  {#each roots as rootNode}
    {@render item(rootNode, 0)}
  {/each}
</div>

{#snippet item(node, depth)}
  {@const children = getChildren(node.id)}
  {@const isExpanded = expandedNodes.has(node.id)}
  {@const isSelected = selectedIds.has(node.id)}
  {@const dc = DEPTH_COLORS[node.depth] || '#64748b'}
  {@const sc = STATUS_COLORS[node.status] || '#64748b'}

  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div
    class="ti" class:selected={isSelected}
    style="padding-left: {10 + depth * 16}px"
    onclick={() => onselect?.(node.id)}
  >
    {#if children.length > 0}
      <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
      <span
        class="chev" class:exp={isExpanded}
        onclick={(e) => { e.stopPropagation(); ontoggle?.(node.id); }}
        ondblclick={(e) => { e.stopPropagation(); ondeeptoggle?.(node.id); }}
      >&#9654;</span>
    {:else}
      <span class="chev leaf"></span>
    {/if}
    <span class="dot" style="background: {sc}"></span>
    <span class="lbl">{node.label}</span>
    {#if node.hasWorkaround}
      <span class="warn">&#9888;</span>
    {/if}
    <span class="dep" style="border-color: {dc}; color: {dc}">{(node.depth?.[0] || '?').toUpperCase()}</span>
  </div>

  {#if isExpanded}
    {#each children as child}
      {@render item(child, depth + 1)}
    {/each}
  {/if}
{/snippet}

<style>
  .tree { flex: 1; overflow-y: auto; padding: 6px 0; }
  .tree::-webkit-scrollbar { width: 4px; }
  .tree::-webkit-scrollbar-thumb { background: var(--bdr); border-radius: 2px; }
  .ti { display: flex; align-items: center; padding: 5px 12px; gap: 5px; cursor: pointer; font-size: 12px; min-height: 32px; transition: background 0.1s; }
  .ti:hover { background: rgba(59,130,246,.06); }
  .ti.selected { background: rgba(59,130,246,.12); }
  .chev { width: 14px; font-size: 10px; color: var(--tx-d); text-align: center; flex-shrink: 0; transition: transform 0.15s; cursor: pointer; }
  .chev.exp { transform: rotate(90deg); }
  .chev.leaf { visibility: hidden; }
  .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .lbl { color: var(--tx-m); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ti.selected .lbl { color: var(--tx); font-weight: 500; }
  .dep { font-size: 10px; padding: 1px 4px; border-radius: 3px; border: 1px solid; }
  .warn { color: var(--or); font-size: 10px; }
</style>
