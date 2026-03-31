<script>
  /**
   * ViewTabs — tab strip matching the study-tutor canvas style.
   * Each tab is an authored diagram, not a filter.
   * Right-click a tab to rename or delete it.
   */
  let { views = [], activeViewId = '', onswitch, oncreate, onrename, ondelete } = $props();

  let ctxMenu = $state({ visible: false, x: 0, y: 0, viewId: null, viewName: '' });

  function handleTabContext(e, view) {
    e.preventDefault();
    ctxMenu = { visible: true, x: e.clientX, y: e.clientY, viewId: view.id, viewName: view.name };
  }

  function closeCtx() { ctxMenu.visible = false; }

  function handleRename() {
    const name = prompt('Rename tab:', ctxMenu.viewName);
    if (name && name !== ctxMenu.viewName) onrename?.(ctxMenu.viewId, name);
    closeCtx();
  }

  function handleDelete() {
    if (confirm(`Delete tab "${ctxMenu.viewName}"?`)) ondelete?.(ctxMenu.viewId);
    closeCtx();
  }
</script>

<svelte:window onclick={closeCtx} />

<div class="tab-bar">
  {#each views as view, i}
    <button
      class="tab-btn" class:active={activeViewId === view.id}
      onclick={() => onswitch?.(view.id)}
      oncontextmenu={(e) => handleTabContext(e, view)}
    >{i + 1}. {view.name}</button>
  {/each}
  <button class="tab-btn add-tab" onclick={oncreate}>+</button>
</div>

{#if ctxMenu.visible}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="tab-ctx" style="left: {ctxMenu.x}px; top: {ctxMenu.y}px" onclick={(e) => e.stopPropagation()}>
    <div class="tab-ctx-item" onclick={handleRename}>&#9998; Rename</div>
    <div class="tab-ctx-item delete" onclick={handleDelete}>&#10005; Delete</div>
  </div>
{/if}

<style>
  .tab-bar {
    display: flex; gap: 2px; background: var(--bg-s);
    border-bottom: 1px solid var(--bdr);
    padding: 8px 12px 0; overflow-x: auto; flex-shrink: 0;
  }
  .tab-btn {
    padding: 8px 16px; border: 1px solid transparent; border-bottom: none;
    border-radius: 6px 6px 0 0; background: transparent;
    color: var(--tx-m); font-size: 13px; font-weight: 500;
    cursor: pointer; white-space: nowrap; transition: all 0.15s;
  }
  .tab-btn:hover { background: var(--bg-e); color: var(--tx); }
  .tab-btn.active { background: var(--bg); color: var(--ac); border-color: var(--bdr); font-weight: 600; }
  .add-tab { color: var(--tx-d); font-size: 16px; padding: 6px 14px; }
  .add-tab:hover { color: var(--ac); }
  .tab-ctx {
    position: fixed; z-index: 200;
    background: var(--bg-e); border: 1px solid var(--bdr);
    border-radius: 8px; padding: 4px 0; min-width: 140px;
    box-shadow: 0 8px 24px var(--sh);
  }
  .tab-ctx-item {
    padding: 6px 14px; font-size: 12px; color: var(--tx-m);
    cursor: pointer; display: flex; align-items: center; gap: 8px;
    transition: background 0.1s;
  }
  .tab-ctx-item:hover { background: rgba(59,130,246,.1); color: var(--tx); }
  .tab-ctx-item.delete:hover { background: rgba(239,68,68,.1); color: #ef4444; }
</style>
