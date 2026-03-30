<script>
  /**
   * ViewTabs — tab bar for switching between canvas views/lenses.
   * Each tab is a filtered projection of the graph.
   */
  let { views = [], activeViewId = 'all', onswitch } = $props();
</script>

<div class="view-tabs">
  <button
    class="vtab" class:active={activeViewId === 'all'}
    onclick={() => onswitch?.('all')}
  >All</button>
  {#each views as view}
    <button
      class="vtab" class:active={activeViewId === view.id}
      onclick={() => onswitch?.(view.id)}
    >{view.name}</button>
  {/each}
</div>

<style>
  .view-tabs {
    display: flex; gap: 2px; padding: 6px 12px 0;
    border-bottom: 1px solid var(--bdr);
    overflow-x: auto; flex-shrink: 0;
  }
  .vtab {
    padding: 7px 14px; border: 1px solid transparent; border-bottom: none;
    border-radius: 6px 6px 0 0; background: transparent;
    color: var(--tx-d); font-size: 12px; font-weight: 500;
    cursor: pointer; white-space: nowrap; transition: all 0.15s;
  }
  .vtab:hover { background: var(--bg-e); color: var(--tx-m); }
  .vtab.active { background: var(--bg); color: var(--ac); border-color: var(--bdr); font-weight: 600; }
</style>
