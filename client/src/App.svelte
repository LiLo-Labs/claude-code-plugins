<script>
  import './app.css';
  import { onMount } from 'svelte';
  import { getInitialTheme, setTheme, toggleTheme } from './lib/theme.js';
  import { appState, loadFromServer, emitEvent } from './lib/state.svelte.js';
  import { genId } from './lib/events.js';
  import { statusColor } from './lib/config.js';
  import ViewTabs from './components/ViewTabs.svelte';
  import DetailPanel from './components/DetailPanel.svelte';
  import CommentBar from './components/CommentBar.svelte';
  import CommentModal from './components/CommentModal.svelte';
  import DrawioEmbed from './components/DrawioEmbed.svelte';

  let theme = $state('dark');
  let activeTabIdx = $state(0);

  onMount(async () => {
    theme = getInitialTheme();
    setTheme(theme);
    await loadFromServer();
    appState.panelOpen = true;
  });

  function getGraphState() {
    const _v = appState.storeVersion;
    return appState.store.getState();
  }
  const graphState = $derived(getGraphState());
  const tabs = $derived(graphState.views);
  const activeTab = $derived(tabs[activeTabIdx] || tabs[0] || null);
  const selectedNode = $derived(
    appState.selectedIds.size === 1
      ? graphState.nodes.get([...appState.selectedIds][0]) || null
      : null
  );

  let commentModal = $state({ visible: false, node: null });

  function selectNode(nodeId) { appState.selectedIds = new Set([nodeId]); }
  function handleSaveComment(nodeId, label, text) {
    emitEvent({ id: genId(), type: 'comment.added', actor: 'user', data: { commentId: genId('c'), target: nodeId, targetLabel: label, text, actor: 'user' } });
  }
  function handleResolveComment(commentId) {
    emitEvent({ id: genId(), type: 'comment.resolved', actor: 'user', data: { commentId, actor: 'user' } });
  }
  function handleDeleteComment(commentId) {
    emitEvent({ id: genId(), type: 'comment.deleted', actor: 'user', data: { commentId } });
  }
  function handleToggleTheme() { theme = toggleTheme(); }
</script>

<div class="layout">
  <header class="topbar">
    <div class="tp"><span class="dot"></span> {activeTab?.name || 'Code Canvas'}</div>
    <div class="tp-story">{activeTab?.description || ''}</div>
    <div class="tr">
      <button class="tb" onclick={() => appState.panelOpen = !appState.panelOpen}>
        {appState.panelOpen ? 'Hide Panel' : 'Show Panel'}
      </button>
      <div class="sep"></div>
      <button class="tb" onclick={handleToggleTheme}>{theme === 'dark' ? '\u2606' : '\u263E'}</button>
    </div>
  </header>

  <div class="main">
    <!-- Left panel: node browser or detail view -->
    {#if appState.panelOpen}
      <aside class="panel-left">
        {#if selectedNode}
          <DetailPanel
            node={selectedNode}
            nodes={graphState.nodes}
            store={appState.store}
            comments={graphState.comments}
            onselect={selectNode}
            onclose={() => { appState.selectedIds = new Set(); }}
            onaddcomment={(node) => { commentModal = { visible: true, node }; }}
            onresolve={handleResolveComment}
            ondelete={handleDeleteComment}
          />
        {:else}
          <div class="node-browser">
            <div class="nb-hdr">
              <span class="nb-title">Nodes</span>
              <button class="nb-close" onclick={() => appState.panelOpen = false}>&times;</button>
            </div>
            <div class="nb-list">
              {#each [...graphState.nodes.values()] as node}
                <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                <div class="nb-item" onclick={() => selectNode(node.id)}>
                  <span class="nb-dot" style="background: {statusColor(node.status)}"></span>
                  <div class="nb-content">
                    <span class="nb-label">{node.label}</span>
                    <span class="nb-sub">{node.subtitle}</span>
                  </div>
                  <span class="nb-depth">{(node.depth || 'M')[0].toUpperCase()}</span>
                </div>
              {/each}
            </div>
          </div>
        {/if}
      </aside>
    {/if}

    <!-- Draw.io canvas -->
    <div class="canvas-col">
      <ViewTabs
        views={tabs}
        activeViewId={activeTab?.id || ''}
        oncreate={() => {
          const name = prompt('Tab name:');
          if (!name) return;
          const viewId = 'tab-' + Date.now();
          emitEvent({ id: genId(), type: 'view.created', actor: 'user', data: { viewId, name, tabNodes: [], tabConnections: [], drawioXml: '' } });
          setTimeout(() => { const i = graphState.views.findIndex(v => v.id === viewId); if (i >= 0) activeTabIdx = i; }, 100);
        }}
        onswitch={(id) => { activeTabIdx = tabs.findIndex(t => t.id === id); if (activeTabIdx < 0) activeTabIdx = 0; }}
        onrename={(viewId, name) => { emitEvent({ id: genId(), type: 'view.updated', actor: 'user', data: { viewId, changes: { name } } }); }}
        ondelete={(viewId) => { emitEvent({ id: genId(), type: 'view.deleted', actor: 'user', data: { viewId } }); if (activeTab?.id === viewId) activeTabIdx = 0; }}
      />
      <DrawioEmbed
        xml={activeTab?.drawioXml || ''}
        dark={theme === 'dark'}
        onchange={(xml) => { if (activeTab) emitEvent({ id: genId(), type: 'view.updated', actor: 'user', data: { viewId: activeTab.id, changes: { drawioXml: xml } } }); }}
        onselect={(ids) => {
          if (ids.length >= 1 && graphState.nodes.has(ids[0])) {
            selectNode(ids[0]);
          } else if (ids.length === 0) {
            appState.selectedIds = new Set();
          }
        }}
      />
    </div>
  </div>

  <CommentBar
    comments={graphState.comments}
    onresolve={handleResolveComment}
    ondelete={handleDeleteComment}
    onnavigate={(nodeId) => { selectNode(nodeId); appState.panelOpen = true; }}
  />

  <CommentModal
    visible={commentModal.visible}
    node={commentModal.node}
    onsave={handleSaveComment}
    onclose={() => commentModal = { ...commentModal, visible: false }}
  />

  <footer class="sl">
    {#if appState.syncError}
      <span class="err">&#9888; Sync failed</span>
    {:else}
      <span class="ok">&#9679; Synced</span>
    {/if}
    <span class="inf">{graphState.nodes.size} nodes</span>
    <span class="inf">{tabs.length} tabs</span>
    <span class="inf">{graphState.eventCount} events</span>
  </footer>
</div>

<style>
  .layout { display: flex; flex-direction: column; height: 100vh; }
  .topbar { display: flex; align-items: center; height: 44px; background: var(--bg-s); border-bottom: 1px solid var(--bdr); padding: 0 16px; flex-shrink: 0; gap: 10px; }
  .tp { font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 6px; }
  .tp-story { font-size: 11px; color: var(--tx-d); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--yl); }
  .sep { width: 1px; height: 18px; background: var(--bdr); margin: 0 4px; }
  .tr { margin-left: auto; display: flex; gap: 4px; align-items: center; }
  .tb { height: 32px; padding: 0 10px; border: 1px solid var(--bdr); border-radius: 4px; background: transparent; color: var(--tx-m); font-size: 12px; transition: .15s; cursor: pointer; }
  .tb:hover { border-color: var(--ac); color: var(--ac); }

  .main { flex: 1; display: flex; min-height: 0; overflow: hidden; }

  .panel-left { width: 280px; background: var(--bg-s); border-right: 1px solid var(--bdr); flex-shrink: 0; overflow-y: auto; z-index: 10; }
  .canvas-col { flex: 1; display: flex; flex-direction: column; min-height: 0; min-width: 0; }

  .node-browser { display: flex; flex-direction: column; height: 100%; }
  .nb-hdr { padding: 12px 14px; border-bottom: 1px solid var(--bdr); display: flex; align-items: center; justify-content: space-between; }
  .nb-title { font-size: 14px; font-weight: 600; }
  .nb-close { border: none; background: transparent; color: var(--tx-d); font-size: 16px; cursor: pointer; padding: 2px 6px; }
  .nb-close:hover { color: var(--tx); }
  .nb-list { flex: 1; overflow-y: auto; }
  .nb-item { display: flex; align-items: center; gap: 8px; padding: 10px 14px; cursor: pointer; transition: background 0.1s; border-bottom: 1px solid var(--bdr); }
  .nb-item:hover { background: var(--bg-e); }
  .nb-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .nb-content { flex: 1; min-width: 0; }
  .nb-label { font-size: 13px; font-weight: 500; display: block; color: var(--tx); }
  .nb-sub { font-size: 11px; color: var(--tx-d); display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin-top: 2px; }
  .nb-depth { font-size: 10px; font-weight: 600; color: var(--tx-d); background: var(--bg); border: 1px solid var(--bdr); width: 20px; height: 20px; border-radius: 4px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }

  .sl { height: 22px; background: var(--bg-s); border-top: 1px solid var(--bdr); display: flex; align-items: center; padding: 0 14px; gap: 14px; font-size: 10px; flex-shrink: 0; }
  .ok { color: var(--gr); }
  .err { color: var(--or); }
  .inf { color: var(--tx-d); }
</style>
