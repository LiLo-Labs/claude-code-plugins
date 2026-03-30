<script>
  /**
   * ViewTabs — tab strip matching the study-tutor canvas style.
   * Each tab is an authored diagram, not a filter.
   */
  let { views = [], activeViewId = '', onswitch } = $props();
</script>

<div class="tab-bar">
  {#each views as view, i}
    <button
      class="tab-btn" class:active={activeViewId === view.id}
      onclick={() => onswitch?.(view.id)}
    >{i + 1}. {view.name}</button>
  {/each}
</div>

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
</style>
