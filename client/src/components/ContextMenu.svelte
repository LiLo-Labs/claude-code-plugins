<script>
  /**
   * Context menu — appears on right-click.
   * Shows actions relevant to the clicked node.
   */
  let { x = 0, y = 0, visible = false, node = null, onaction, onclose } = $props();
</script>

<svelte:window onclick={onclose} />

{#if visible && node}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="ctx" style="left: {x}px; top: {y}px" onclick={(e) => e.stopPropagation()}>
    <div class="ctx-header">{node.label}</div>
    <div class="ctx-sep"></div>
    <div class="ctx-item" onclick={() => onaction?.('comment')}>&#128172; Add Comment</div>
    <div class="ctx-sep"></div>
    <div class="ctx-item" onclick={() => onaction?.('status-done')}>
      <span style="color: #10b981">&#9679;</span> Mark Done
    </div>
    <div class="ctx-item" onclick={() => onaction?.('status-in-progress')}>
      <span style="color: #eab308">&#9679;</span> Mark In Progress
    </div>
    <div class="ctx-item" onclick={() => onaction?.('status-planned')}>
      <span style="color: #3b82f6">&#9679;</span> Mark Planned
    </div>
    <div class="ctx-sep"></div>
    <div class="ctx-item" onclick={() => onaction?.('details')}>&#128196; View Details</div>
  </div>
{/if}

<style>
  .ctx {
    position: fixed; z-index: 100;
    background: var(--bg-e); border: 1px solid var(--bdr);
    border-radius: 8px; padding: 4px 0; min-width: 200px;
    box-shadow: 0 8px 24px var(--sh);
  }
  .ctx-header {
    padding: 6px 14px; font-size: 12px; font-weight: 600;
    color: var(--tx); border-bottom: none;
  }
  .ctx-item {
    padding: 6px 14px; font-size: 12px; color: var(--tx-m);
    cursor: pointer; display: flex; align-items: center; gap: 8px;
    transition: background 0.1s;
  }
  .ctx-item:hover { background: rgba(59,130,246,.1); color: var(--tx); }
  .ctx-sep { height: 1px; background: var(--bdr); margin: 3px 0; }
</style>
