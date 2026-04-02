<script>
  let { x = 0, y = 0, visible = false, nodeId = null, nodeLabel = '', onaction, onclose } = $props();
</script>

<svelte:window onclick={onclose} onkeydown={(e) => { if (e.key === 'Escape') onclose?.(); }} />

{#if visible}
  <div class="ctx" style="left: {x}px; top: {y}px" onclick={(e) => e.stopPropagation()}>
    <div class="ctx-header">{nodeLabel}</div>
    <div class="ctx-sep"></div>
    <div class="ctx-item" onclick={() => { onaction?.('comment'); onclose?.(); }}>Add Comment</div>
    <div class="ctx-item" onclick={() => { onaction?.('details'); onclose?.(); }}>View Details</div>
    <div class="ctx-sep"></div>
    <div class="ctx-sub">Change Status</div>
    <div class="ctx-item" onclick={() => { onaction?.('status-done'); onclose?.(); }}>
      <span class="dot" style="background: #10b981"></span> Done
    </div>
    <div class="ctx-item" onclick={() => { onaction?.('status-in-progress'); onclose?.(); }}>
      <span class="dot" style="background: #eab308"></span> In Progress
    </div>
    <div class="ctx-item" onclick={() => { onaction?.('status-planned'); onclose?.(); }}>
      <span class="dot" style="background: #3b82f6"></span> Planned
    </div>
    <div class="ctx-item" onclick={() => { onaction?.('status-blocked'); onclose?.(); }}>
      <span class="dot" style="background: #f85149"></span> Blocked
    </div>
  </div>
{/if}

<style>
  .ctx { position: fixed; z-index: 100; background: var(--bg-e); border: 1px solid var(--bdr); border-radius: 8px; padding: 4px 0; min-width: 180px; box-shadow: 0 8px 24px var(--sh); }
  .ctx-header { padding: 6px 14px; font-size: 12px; font-weight: 600; color: var(--tx); }
  .ctx-sub { padding: 6px 14px 2px; font-size: 10px; text-transform: uppercase; letter-spacing: .06em; color: var(--tx-d); }
  .ctx-item { padding: 6px 14px; font-size: 12px; color: var(--tx-m); cursor: pointer; display: flex; align-items: center; gap: 8px; transition: background 0.1s; }
  .ctx-item:hover { background: rgba(59,130,246,.1); color: var(--tx); }
  .ctx-sep { height: 1px; background: var(--bdr); margin: 3px 0; }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
</style>
