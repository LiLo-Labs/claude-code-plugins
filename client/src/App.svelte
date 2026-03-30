<script>
  import './app.css';
  import { onMount } from 'svelte';
  import { getInitialTheme, setTheme, toggleTheme } from './lib/theme.js';
  import { appState, loadFromServer } from './lib/state.svelte.js';

  let theme = $state('dark');

  onMount(async () => {
    theme = getInitialTheme();
    setTheme(theme);
    await loadFromServer();
  });

  function handleToggleTheme() {
    theme = toggleTheme();
  }

  const graphState = $derived(appState.store.getState());
  const unresolvedCount = $derived(graphState.comments.filter(c => !c.resolved).length);
  const viewModes = ['Canvas', 'Timeline', 'Diff', 'Story'];
</script>

<div class="layout">
  <header class="topbar">
    <div class="topbar-project">
      <span class="status-dot"></span>
      Code Canvas
    </div>

    <div class="view-tabs">
      {#each viewModes as mode}
        <button
          class:active={appState.activeViewMode === mode.toLowerCase()}
          onclick={() => appState.activeViewMode = mode.toLowerCase()}
        >{mode}</button>
      {/each}
    </div>

    <div class="topbar-sep"></div>

    <div class="topbar-right">
      <button class="tbtn" onclick={() => appState.zoom = Math.max(0.15, appState.zoom - 0.15)}>-</button>
      <span class="zoom-display">{Math.round(appState.zoom * 100)}%</span>
      <button class="tbtn" onclick={() => appState.zoom = Math.min(3, appState.zoom + 0.15)}>+</button>
      <button class="tbtn" onclick={() => { appState.zoom = 1; appState.panX = 0; appState.panY = 0; }}>&#8962;</button>
      <div class="topbar-sep"></div>
      <button class="tbtn" onclick={handleToggleTheme}>
        {theme === 'dark' ? '\u2606' : '\u263E'}
      </button>
    </div>
  </header>

  <div class="main">
    {#if appState.sidebarOpen}
      <aside class="sidebar-left">
        <div class="sidebar-header">
          <div class="search-box">
            <input
              type="text"
              placeholder="Search... (\u2318K)"
              bind:value={appState.searchQuery}
            />
          </div>
        </div>
        <div class="sidebar-body">
          <p class="placeholder-text">{graphState.nodes.size} nodes</p>
          <p class="placeholder-sub">Tree view — Task 5+</p>
        </div>
      </aside>
    {/if}

    <main class="canvas-area">
      <div class="canvas-bg"></div>
      <div class="canvas-placeholder">
        <p>{graphState.nodes.size} nodes, {graphState.edges.size} edges</p>
        <p class="meta">{graphState.eventCount} events loaded</p>
        <p class="meta">View: {appState.activeViewMode}</p>
      </div>
    </main>

    {#if appState.panelOpen}
      <aside class="sidebar-right">
        <div class="panel-header">
          <span class="panel-title">Details</span>
          <button class="panel-close" onclick={() => appState.panelOpen = false}>&times;</button>
        </div>
        <div class="panel-body">
          <p class="placeholder-text">Select a node</p>
        </div>
      </aside>
    {/if}
  </div>

  <div class="comment-bar">
    <span class="comment-label">Comments</span>
    <span class="comment-badge">{unresolvedCount}</span>
  </div>

  <footer class="status-line">
    <span class="sl-ok">&#9679; Synced</span>
    <span class="sl-info">{graphState.nodes.size} nodes</span>
    <span class="sl-info">{graphState.eventCount} events</span>
  </footer>
</div>

<style>
  .layout { display: flex; flex-direction: column; height: 100vh; }

  /* ── Topbar ── */
  .topbar {
    display: flex; align-items: center; height: 44px;
    background: var(--bg-s); border-bottom: 1px solid var(--bdr);
    padding: 0 16px; flex-shrink: 0; gap: 10px;
  }
  .topbar-project {
    font-size: 14px; font-weight: 600;
    display: flex; align-items: center; gap: 6px; margin-right: 16px;
  }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--yl); }
  .view-tabs { display: flex; gap: 1px; background: var(--bdr); border-radius: 6px; overflow: hidden; }
  .view-tabs button {
    padding: 7px 16px; border: none; background: var(--bg-s);
    color: var(--tx-d); font-size: 12px; font-weight: 500; transition: 0.15s ease;
  }
  .view-tabs button:hover { color: var(--tx-m); }
  .view-tabs button.active { background: var(--bg-e); color: var(--ac); }
  .topbar-sep { width: 1px; height: 18px; background: var(--bdr); margin: 0 6px; }
  .topbar-right { margin-left: auto; display: flex; gap: 4px; align-items: center; }
  .tbtn {
    height: 32px; padding: 0 10px;
    border: 1px solid var(--bdr); border-radius: 4px;
    background: transparent; color: var(--tx-m); font-size: 12px; transition: 0.15s ease;
  }
  .tbtn:hover { border-color: var(--ac); color: var(--ac); }
  .zoom-display { font-size: 11px; color: var(--tx-d); min-width: 36px; text-align: center; }

  /* ── Main ── */
  .main { flex: 1; display: flex; min-height: 0; }

  /* ── Sidebars ── */
  .sidebar-left {
    width: 260px; background: var(--gl); backdrop-filter: blur(16px);
    border-right: 1px solid var(--gl-b); flex-shrink: 0;
    display: flex; flex-direction: column;
  }
  .sidebar-header { padding: 10px 12px; border-bottom: 1px solid var(--bdr); }
  .search-box {
    display: flex; background: var(--bg); border: 1px solid var(--bdr);
    border-radius: 6px; padding: 9px 12px;
  }
  .search-box input {
    background: none; border: none; color: var(--tx);
    font-size: 12px; outline: none; width: 100%;
  }
  .sidebar-body { flex: 1; padding: 12px; overflow-y: auto; }

  .sidebar-right {
    width: 300px; background: var(--gl); backdrop-filter: blur(16px);
    border-left: 1px solid var(--gl-b); flex-shrink: 0;
    display: flex; flex-direction: column;
  }
  .panel-header {
    padding: 12px 14px; border-bottom: 1px solid var(--bdr);
    display: flex; align-items: center; justify-content: space-between;
  }
  .panel-title { font-size: 14px; font-weight: 600; }
  .panel-close {
    border: none; background: transparent; color: var(--tx-d);
    font-size: 14px; border-radius: 3px; width: 20px; height: 20px;
    display: flex; align-items: center; justify-content: center;
  }
  .panel-close:hover { background: var(--bg-e); color: var(--tx); }
  .panel-body { flex: 1; padding: 14px; overflow-y: auto; }

  /* ── Canvas ── */
  .canvas-area { flex: 1; position: relative; overflow: hidden; }
  .canvas-bg {
    position: absolute; inset: 0;
    background: radial-gradient(circle at 1px 1px, var(--gd) 1px, transparent 0);
    background-size: 28px 28px;
  }
  .canvas-placeholder {
    position: absolute; inset: 0;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    color: var(--tx-d); font-size: 14px; gap: 4px;
  }

  /* ── Comment bar ── */
  .comment-bar {
    height: 28px; background: var(--gl); backdrop-filter: blur(16px);
    border-top: 1px solid var(--gl-b);
    display: flex; align-items: center; padding: 0 14px; gap: 6px; flex-shrink: 0;
  }
  .comment-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--tx-d); }
  .comment-badge {
    font-size: 10px; background: var(--ac); color: white;
    padding: 0 5px; border-radius: 7px; font-weight: 600;
  }

  /* ── Status line ── */
  .status-line {
    height: 22px; background: var(--bg-s); border-top: 1px solid var(--bdr);
    display: flex; align-items: center; padding: 0 14px; gap: 14px;
    font-size: 10px; flex-shrink: 0;
  }
  .sl-ok { color: var(--gr); }
  .sl-info { color: var(--tx-d); }

  .placeholder-text { font-size: 12px; color: var(--tx-d); text-align: center; }
  .placeholder-sub { font-size: 11px; color: var(--tx-d); text-align: center; margin-top: 4px; }
  .meta { font-size: 12px; }
</style>
