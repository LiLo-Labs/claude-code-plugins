<script>
  import './app.css';
  import { onMount } from 'svelte';
  import { getInitialTheme, setTheme, toggleTheme } from './lib/theme.js';
  import { appState, loadFromServer, emitEvent } from './lib/state.svelte.js';
  import { genId } from './lib/events.js';
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
  });

  // Reactive graph state
  function getGraphState() {
    const _v = appState.storeVersion;
    return appState.store.getState();
  }
  const graphState = $derived(getGraphState());

  // Active tab
  const tabs = $derived(graphState.views);
  const activeTab = $derived(tabs[activeTabIdx] || tabs[0] || null);

  const selectedNode = $derived(
    appState.selectedIds.size === 1
      ? graphState.nodes.get([...appState.selectedIds][0]) || null
      : null
  );

  // Comment modal state
  let commentModal = $state({ visible: false, node: null });

  function handleSaveComment(nodeId, label, text) {
    emitEvent({
      id: genId(), type: 'comment.added', actor: 'user',
      data: { commentId: genId('c'), target: nodeId, targetLabel: label, text, actor: 'user' },
    });
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
  <!-- Topbar -->
  <header class="topbar">
    <div class="tp"><span class="dot"></span> {activeTab?.name || 'Code Canvas'}</div>
    <div class="tp-story">{activeTab?.story || ''}</div>
    <div class="tr">
      <button class="tb" onclick={handleToggleTheme}>{theme === 'dark' ? '\u2606' : '\u263E'}</button>
    </div>
  </header>

  <div class="main">
    <!-- Canvas with tab bar -->
    <div class="canvas-col">
      <ViewTabs
        views={tabs}
        activeViewId={activeTab?.id || ''}
        oncreate={() => {
          const name = prompt('Tab name:');
          if (!name) return;
          const viewId = 'tab-' + Date.now();
          emitEvent({
            id: genId(), type: 'view.created', actor: 'user',
            data: { viewId, name, story: '', tabNodes: [], tabConnections: [], drawioXml: '' },
          });
          setTimeout(() => {
            const newIdx = graphState.views.findIndex(v => v.id === viewId);
            if (newIdx >= 0) activeTabIdx = newIdx;
          }, 100);
        }}
        onswitch={(id) => {
          activeTabIdx = tabs.findIndex(t => t.id === id);
          if (activeTabIdx < 0) activeTabIdx = 0;
        }}
        onrename={(viewId, name) => {
          emitEvent({
            id: genId(), type: 'view.updated', actor: 'user',
            data: { viewId, changes: { name } },
          });
        }}
        ondelete={(viewId) => {
          emitEvent({
            id: genId(), type: 'view.deleted', actor: 'user',
            data: { viewId },
          });
          if (activeTab?.id === viewId) activeTabIdx = 0;
        }}
      />

      <!-- Draw.io editor -->
      <DrawioEmbed
        xml={activeTab?.drawioXml || ''}
        dark={theme === 'dark'}
        onchange={(xml) => {
          if (activeTab) {
            emitEvent({
              id: genId(), type: 'view.updated', actor: 'user',
              data: { viewId: activeTab.id, changes: { drawioXml: xml } },
            });
          }
        }}
      />
    </div>

    <!-- Detail panel removed — draw.io has its own format panel -->
  </div>

  <!-- Comment bar -->
  <CommentBar
    comments={graphState.comments}
    onresolve={handleResolveComment}
    ondelete={handleDeleteComment}
    onnavigate={(nodeId) => { appState.selectedIds = new Set([nodeId]); appState.panelOpen = true; }}
  />

  <!-- Comment modal -->
  <CommentModal
    visible={commentModal.visible}
    node={commentModal.node}
    onsave={handleSaveComment}
    onclose={() => commentModal = { ...commentModal, visible: false }}
  />

  <!-- Status line -->
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

  .main { flex: 1; display: flex; min-height: 0; }
  .canvas-col { flex: 1; display: flex; flex-direction: column; min-height: 0; min-width: 0; position: relative; }
  .edge-toggle { position: absolute; top: 50%; z-index: 15; width: 16px; height: 44px; background: var(--bg-s); border: 1px solid var(--bdr); display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 11px; color: var(--tx-d); transition: .15s; }
  .edge-toggle:hover { border-color: var(--ac); color: var(--ac); }
  .edge-toggle.right { right: 0; border-radius: 4px 0 0 4px; border-right: none; transform: translateY(-50%); }

  .rp { width: 280px; background: var(--gl); backdrop-filter: blur(16px); border-left: 1px solid var(--gl-b); flex-shrink: 0; }

  .sl { height: 22px; background: var(--bg-s); border-top: 1px solid var(--bdr); display: flex; align-items: center; padding: 0 14px; gap: 14px; font-size: 10px; flex-shrink: 0; }
  .ok { color: var(--gr); }
  .err { color: var(--or); }
  .inf { color: var(--tx-d); }
</style>
