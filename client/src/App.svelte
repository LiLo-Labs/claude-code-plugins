<script>
  import { onMount } from 'svelte';
  import { getInitialTheme, setTheme, toggleTheme } from './lib/theme.js';
  import { appState, loadFromServer, emitEvent, subscribeToEvents } from './lib/store.svelte.js';
  import { genId } from './lib/store.js';
  import ViewTabs from './components/ViewTabs.svelte';
  import SvgCanvas from './components/SvgCanvas.svelte';
  import DetailPanel from './components/DetailPanel.svelte';
  import ContextMenu from './components/ContextMenu.svelte';
  import CommentBar from './components/CommentBar.svelte';
  import CommentModal from './components/CommentModal.svelte';

  let theme = $state('dark');
  let activeTabIdx = $state(0);
  let ctxMenu = $state({ visible: false, x: 0, y: 0, nodeId: null });
  let commentModal = $state({ visible: false, node: null });

  onMount(async () => {
    theme = getInitialTheme();
    setTheme(theme);
    await loadFromServer();
    subscribeToEvents();
  });

  function getGraphState() {
    const _v = appState.storeVersion;
    return appState.store.getState();
  }

  const graphState = $derived(getGraphState());
  const tabs = $derived(graphState.views);
  const activeTab = $derived(tabs[activeTabIdx] || tabs[0] || null);
  const selectedNodeId = $derived(
    appState.selectedIds.size === 1 ? [...appState.selectedIds][0] : null
  );
  const selectedNode = $derived(
    selectedNodeId ? graphState.nodes.get(selectedNodeId) || null : null
  );

  function selectNode(nodeId) { appState.selectedIds = new Set([nodeId]); }

  function handleContextMenu({ x, y, cellId }) {
    ctxMenu = { visible: true, x, y, nodeId: cellId };
  }

  function getNodeOrStub(cellId) {
    return graphState.nodes.get(cellId) || { id: cellId, label: cellId, subtitle: '', status: 'planned', depth: 'module', category: 'arch', completeness: 0, files: [] };
  }

  function handleContextAction(action) {
    const nodeId = ctxMenu.nodeId;
    if (!nodeId) return;
    if (action === 'details') {
      selectNode(nodeId);
    } else if (action === 'comment') {
      commentModal = { visible: true, node: getNodeOrStub(nodeId) };
    } else if (action.startsWith('status-')) {
      const status = action.replace('status-', '');
      emitEvent({ id: genId(), type: 'node.status', actor: 'user', data: { nodeId, status } });
    }
  }

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
      <button class="tb" onclick={handleToggleTheme}>{theme === 'dark' ? '\u2606' : '\u263E'}</button>
    </div>
  </header>

  <div class="main">
    {#if selectedNodeId}
      <aside class="panel-left">
        {#if selectedNode}
          <DetailPanel
            node={selectedNode}
            store={appState.store}
            comments={graphState.comments}
            onselect={selectNode}
            onclose={() => { appState.selectedIds = new Set(); }}
            onaddcomment={(node) => { commentModal = { visible: true, node }; }}
            onresolve={handleResolveComment}
            ondelete={handleDeleteComment}
          />
        {:else}
          {@const cellComments = graphState.comments.filter(c => c.target === selectedNodeId)}
          {@const openCellComments = cellComments.filter(c => !c.resolved)}
          <div class="panel-mini">
            <div class="pm-hdr">
              <span class="pm-id">{selectedNodeId}</span>
              <button class="pm-close" onclick={() => { appState.selectedIds = new Set(); }}>&times;</button>
            </div>
            <p class="pm-note">Diagram-only shape (not a semantic node).</p>
            {#if openCellComments.length > 0}
              <div class="pm-section">
                {#each openCellComments as comment}
                  <div class="pm-comment">
                    <span class="pm-ctxt">{comment.text}</span>
                    <button class="pm-btn" onclick={() => handleResolveComment(comment.id)}>&#10003;</button>
                    <button class="pm-btn pm-del" onclick={() => handleDeleteComment(comment.id)}>&times;</button>
                  </div>
                {/each}
              </div>
            {/if}
            <div class="pm-add" onclick={() => { commentModal = { visible: true, node: getNodeOrStub(selectedNodeId) }; }}>+ Add Comment</div>
          </div>
        {/if}
      </aside>
    {/if}

    <div class="canvas-col">
      <ViewTabs
        views={tabs}
        activeViewId={activeTab?.id || ''}
        oncreate={() => {
          const name = prompt('Tab name:');
          if (!name) return;
          const viewId = 'tab-' + Date.now();
          emitEvent({ id: genId(), type: 'view.created', actor: 'user', data: { viewId, name, drawioXml: '' } });
          setTimeout(() => { const i = graphState.views.findIndex(v => v.id === viewId); if (i >= 0) activeTabIdx = i; }, 100);
        }}
        onswitch={(id) => { activeTabIdx = tabs.findIndex(t => t.id === id); if (activeTabIdx < 0) activeTabIdx = 0; }}
        onrename={(viewId, name) => { emitEvent({ id: genId(), type: 'view.updated', actor: 'user', data: { viewId, changes: { name } } }); }}
        ondelete={(viewId) => { emitEvent({ id: genId(), type: 'view.deleted', actor: 'user', data: { viewId } }); if (activeTab?.id === viewId) activeTabIdx = 0; }}
      />
      <SvgCanvas
        xml={activeTab?.drawioXml || ''}
        dark={theme === 'dark'}
        onchange={(xml) => { if (activeTab) emitEvent({ id: genId(), type: 'view.updated', actor: 'user', data: { viewId: activeTab.id, changes: { drawioXml: xml } } }); }}
        onselect={(ids) => {
          if (ids.length >= 1) selectNode(ids[0]);
          else appState.selectedIds = new Set();
        }}
        oncontextmenu={handleContextMenu}
        oncelladded={(cell) => {
          if (!cell.isEdge) {
            // User drew a shape → create a node in the store
            const nodeId = cell.id.startsWith('n_') ? cell.id : 'n_' + cell.id;
            if (!graphState.nodes.has(nodeId) && !graphState.nodes.has(cell.id)) {
              emitEvent({ id: genId(), type: 'node.created', actor: 'user', data: { nodeId, label: cell.label || 'New Node', subtitle: '', depth: 'module', category: 'arch', status: 'planned', files: [] } });
            }
          } else if (cell.from && cell.to) {
            // User drew an edge → create an edge in the store
            const edgeId = cell.id.startsWith('e_') ? cell.id : 'e_' + cell.id;
            emitEvent({ id: genId(), type: 'edge.created', actor: 'user', data: { edgeId, from: cell.from, to: cell.to, label: cell.label || '' } });
          }
        }}
        oncellremoved={(cell) => {
          if (!cell.isEdge) {
            // Check both with and without n_ prefix
            const id = graphState.nodes.has(cell.id) ? cell.id : 'n_' + cell.id;
            if (graphState.nodes.has(id)) {
              emitEvent({ id: genId(), type: 'node.deleted', actor: 'user', data: { nodeId: id } });
            }
          } else {
            const id = graphState.edges.has(cell.id) ? cell.id : 'e_' + cell.id;
            if (graphState.edges.has(id)) {
              emitEvent({ id: genId(), type: 'edge.deleted', actor: 'user', data: { edgeId: id } });
            }
          }
        }}
      />
    </div>
  </div>

  <CommentBar
    comments={graphState.comments}
    onresolve={handleResolveComment}
    ondelete={handleDeleteComment}
    onnavigate={(nodeId) => { selectNode(nodeId); }}
  />

  <ContextMenu
    visible={ctxMenu.visible}
    x={ctxMenu.x} y={ctxMenu.y}
    nodeId={ctxMenu.nodeId}
    nodeLabel={ctxMenu.nodeId ? (graphState.nodes.get(ctxMenu.nodeId)?.label || ctxMenu.nodeId) : ''}
    onaction={handleContextAction}
    onclose={() => { ctxMenu.visible = false; }}
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
  .tr { margin-left: auto; display: flex; gap: 4px; align-items: center; }
  .tb { height: 32px; padding: 0 10px; border: 1px solid var(--bdr); border-radius: 4px; background: transparent; color: var(--tx-m); font-size: 12px; transition: .15s; cursor: pointer; }
  .tb:hover { border-color: var(--ac); color: var(--ac); }
  .main { flex: 1; display: flex; min-height: 0; overflow: hidden; }
  .panel-left { width: 280px; background: var(--bg-s); border-right: 1px solid var(--bdr); flex-shrink: 0; overflow-y: auto; z-index: 10; }
  .canvas-col { flex: 1; display: flex; flex-direction: column; min-height: 0; min-width: 0; }
  .sl { height: 22px; background: var(--bg-s); border-top: 1px solid var(--bdr); display: flex; align-items: center; padding: 0 14px; gap: 14px; font-size: 10px; flex-shrink: 0; }
  .ok { color: var(--gr); }
  .err { color: var(--or); }
  .inf { color: var(--tx-d); }
  .panel-mini { padding: 14px; }
  .pm-hdr { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
  .pm-id { font-size: 12px; font-family: monospace; color: var(--tx-m); }
  .pm-close { border: none; background: transparent; color: var(--tx-d); font-size: 14px; cursor: pointer; }
  .pm-close:hover { color: var(--tx); }
  .pm-note { font-size: 11px; color: var(--tx-d); line-height: 1.4; margin-bottom: 10px; }
  .pm-section { margin-bottom: 8px; }
  .pm-comment { display: flex; align-items: center; gap: 6px; padding: 4px 0; border-bottom: 1px solid var(--bdr); font-size: 12px; }
  .pm-ctxt { color: var(--tx-m); flex: 1; }
  .pm-btn { background: none; border: none; font-size: 13px; padding: 0 2px; cursor: pointer; color: var(--gr); }
  .pm-btn.pm-del { color: var(--tx-d); }
  .pm-btn.pm-del:hover { color: var(--rd); }
  .pm-add { font-size: 11px; color: var(--ac); cursor: pointer; padding: 6px 0; text-align: center; border: 1px dashed var(--bdr); border-radius: 4px; transition: .15s; }
  .pm-add:hover { border-color: var(--ac); background: rgba(59,130,246,.05); }
</style>
