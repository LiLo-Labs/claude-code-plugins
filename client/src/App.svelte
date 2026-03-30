<script>
  import './app.css';
  import { onMount } from 'svelte';
  import { getInitialTheme, setTheme, toggleTheme } from './lib/theme.js';
  import { appState, loadFromServer, emitEvent } from './lib/state.svelte.js';
  import { genId } from './lib/events.js';
  import { computeLayout, getAncestors } from './lib/layout.js';
  import { createDragState, toSvgPoint } from './lib/drag.js';
  import Canvas from './components/Canvas.svelte';
  import NodeLeaf from './components/NodeLeaf.svelte';
  import EdgeLine from './components/EdgeLine.svelte';
  import ViewTabs from './components/ViewTabs.svelte';
  import TreeView from './components/TreeView.svelte';
  import DetailPanel from './components/DetailPanel.svelte';
  import ContextMenu from './components/ContextMenu.svelte';
  import CommentBar from './components/CommentBar.svelte';
  import CommentModal from './components/CommentModal.svelte';

  let theme = $state('dark');
  let activeTabIdx = $state(0);
  let savedPositions = $state({});
  let drag = $state(createDragState());
  let treeExpanded = $state(new Set());

  onMount(async () => {
    theme = getInitialTheme();
    setTheme(theme);
    await loadFromServer();
    // Load saved positions for first tab
    const state = appState.store.getState();
    if (state.views.length > 0) {
      try {
        const r = await fetch(`/api/layouts/${state.views[0].id}`);
        savedPositions = await r.json() || {};
      } catch {}
    }
    // Auto-fit on first load (after a tick so layout is computed)
    setTimeout(fitToContent, 50);
  });

  // Reactive graph state
  function getGraphState() {
    const _v = appState.storeVersion;
    return appState.store.getState();
  }
  const graphState = $derived(getGraphState());

  // Active tab — a DIAGRAM, not a filter
  const tabs = $derived(graphState.views);
  const activeTab = $derived(tabs[activeTabIdx] || tabs[0] || null);

  // Tab's authored node list + connection list
  const tabNodes = $derived(activeTab?.tabNodes || []);
  const tabConnections = $derived(activeTab?.tabConnections || []);

  // Merge tab node data with registry node data
  function getNodeWithOverrides(tabNode) {
    const registry = graphState.nodes.get(tabNode.nodeId || tabNode.id);
    if (!registry) return null;
    return {
      ...registry,
      // Tab-level overrides
      color: tabNode.color || registry.color,
      textColor: tabNode.textColor || registry.textColor,
    };
  }

  // Layout from tab's node positions
  const activePositions = $derived(computeLayout(tabNodes, savedPositions));

  // Edge colors for arrow markers
  const edgeColors = $derived([...new Set(tabConnections.map(c => c.color).filter(Boolean))]);

  const unresolvedCount = $derived(graphState.comments.filter(c => !c.resolved).length);
  const selectedNode = $derived(
    appState.selectedIds.size === 1
      ? graphState.nodes.get([...appState.selectedIds][0]) || null
      : null
  );

  function selectNode(nodeId, e) {
    // If in connect mode, complete the connection
    if (connectMode.active) {
      if (connectMode.fromId !== nodeId) {
        const label = prompt('Connection label:') || '';
        activeTab.tabConnections = [...activeTab.tabConnections, { from: connectMode.fromId, to: nodeId, label, color: '#64748b' }];
        appState.storeVersion++;
      }
      connectMode = { active: false, fromId: null };
      return;
    }
    if (e?.shiftKey) {
      const next = new Set(appState.selectedIds);
      next.has(nodeId) ? next.delete(nodeId) : next.add(nodeId);
      appState.selectedIds = next;
    } else {
      appState.selectedIds = new Set([nodeId]);
    }
  }

  // Drag
  function startDrag(nodeId, e) {
    const svgEl = document.querySelector('.canvas-svg');
    if (!svgEl) return;
    const pt = toSvgPoint(e, svgEl);
    const pos = activePositions.get(nodeId);
    if (!pos) return;
    drag = { active: true, nodeId, startX: pt.x, startY: pt.y, origX: pos.x, origY: pos.y };
  }
  function handleMouseMove(e) {
    if (!drag.active) return;
    const svgEl = document.querySelector('.canvas-svg');
    if (!svgEl) return;
    const pt = toSvgPoint(e, svgEl);
    savedPositions = { ...savedPositions, [drag.nodeId]: { x: drag.origX + (pt.x - drag.startX), y: drag.origY + (pt.y - drag.startY) } };
  }
  function handleMouseUp() {
    if (drag.active) {
      drag = createDragState();
      // Persist to server
      const viewId = activeTab?.id || 'default';
      fetch(`/api/layouts/${viewId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(savedPositions),
      }).catch(() => {});
    }
  }

  // Tree
  function toggleTreeNode(nodeId) {
    treeExpanded.has(nodeId) ? treeExpanded.delete(nodeId) : treeExpanded.add(nodeId);
    treeExpanded = new Set(treeExpanded);
  }

  // Context menu state
  let ctxMenu = $state({ visible: false, x: 0, y: 0, node: null, isCanvas: false });
  let connectMode = $state({ active: false, fromId: null }); // for drawing connections

  function handleContextMenu(nodeId, e) {
    e.preventDefault();
    if (connectMode.active) {
      // Complete the connection
      const label = prompt('Connection label:') || '';
      if (connectMode.fromId !== nodeId) {
        activeTab.tabConnections = [...activeTab.tabConnections, { from: connectMode.fromId, to: nodeId, label, color: '#64748b' }];
        appState.storeVersion++;
      }
      connectMode = { active: false, fromId: null };
      return;
    }
    const node = graphState.nodes.get(nodeId);
    if (!node) return;
    ctxMenu = { visible: true, x: e.clientX, y: e.clientY, node, isCanvas: false };
  }

  function handleCanvasContextMenu(e) {
    // Only fire if clicking on the background, not on a node
    if (e.target.closest('[data-node]')) return;
    e.preventDefault();
    ctxMenu = { visible: true, x: e.clientX, y: e.clientY, node: null, isCanvas: true };
  }

  function handleCtxAction(action) {
    const node = ctxMenu.node;
    const isCanvas = ctxMenu.isCanvas;
    ctxMenu = { ...ctxMenu, visible: false };

    // Canvas-level actions (no node)
    if (isCanvas) {
      if (action === 'new-node') {
        const label = prompt('Node name:');
        if (!label) return;
        const subtitle = prompt('Description (optional):') || '';
        const nodeId = genId('node');
        // Create in registry
        emitEvent({ id: genId(), type: 'node.created', actor: 'user', data: { nodeId, label, subtitle, parent: null, depth: 'module', category: 'arch', confidence: 1 } });
        // Add to current tab
        if (activeTab) {
          const maxRow = activeTab.tabNodes.reduce((m, tn) => Math.max(m, tn.row || 0), -1);
          activeTab.tabNodes = [...activeTab.tabNodes, { nodeId, row: maxRow + 1, col: 0, cols: 3 }];
        }
      }
      return;
    }

    if (!node) return;

    if (action === 'comment') {
      commentModal = { visible: true, node };
    } else if (action.startsWith('status-')) {
      const status = action.replace('status-', '');
      emitEvent({ id: genId(), type: 'node.status', actor: 'user', data: { nodeId: node.id, status, prev: node.status } });
    } else if (action === 'details') {
      appState.selectedIds = new Set([node.id]);
      appState.panelOpen = true;
    } else if (action === 'connect') {
      connectMode = { active: true, fromId: node.id };
    } else if (action === 'remove-from-tab') {
      // Remove node from current tab's tabNodes
      if (activeTab) {
        activeTab.tabNodes = activeTab.tabNodes.filter(tn => (tn.nodeId || tn.id) !== node.id);
        activeTab.tabConnections = activeTab.tabConnections.filter(c => c.from !== node.id && c.to !== node.id);
        // Force re-render
        appState.storeVersion++;
      }
    }
  }

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

  function fitToContent() {
    if (activePositions.size === 0) { appState.zoom = 1; appState.panX = 0; appState.panY = 0; return; }
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const [, pos] of activePositions) {
      minX = Math.min(minX, pos.x);
      minY = Math.min(minY, pos.y);
      maxX = Math.max(maxX, pos.x + pos.w);
      maxY = Math.max(maxY, pos.y + pos.h);
    }
    // Add padding around the content
    const pad = 60;
    const contentW = maxX - minX + pad * 2;
    const contentH = maxY - minY + pad * 2;
    // Estimate available canvas area (subtract sidebars)
    const availW = Math.max(400, window.innerWidth - (appState.sidebarOpen ? 260 : 0) - (appState.panelOpen ? 300 : 0));
    const availH = Math.max(300, window.innerHeight - 44 - 130); // topbar + comment bar
    const zoom = Math.min(1, availW / contentW, availH / contentH);
    appState.zoom = Math.max(0.2, Math.round(zoom * 20) / 20); // round to nearest 5%
    appState.panX = -(minX - pad) * appState.zoom + (availW - contentW * appState.zoom) / 2;
    appState.panY = -(minY - pad) * appState.zoom + (availH - contentH * appState.zoom) / 2;
  }
</script>

<svelte:window onmousemove={handleMouseMove} onmouseup={handleMouseUp} />

<div class="layout">
  <!-- Topbar — clean, no dead buttons -->
  <header class="topbar">
    <div class="tp"><span class="dot"></span> {activeTab?.name || 'Code Canvas'}</div>
    <div class="tp-story">{activeTab?.story || ''}</div>
    <div class="tr">
      <button class="tb" onclick={() => appState.sidebarOpen = !appState.sidebarOpen}>&#9776;</button>
      <div class="sep"></div>
      <button class="tb" onclick={() => appState.zoom = Math.max(0.15, appState.zoom - 0.15)}>-</button>
      <span class="zd">{Math.round(appState.zoom * 100)}%</span>
      <button class="tb" onclick={() => appState.zoom = Math.min(3, appState.zoom + 0.15)}>+</button>
      <button class="tb" onclick={fitToContent}>&#8962;</button>
      <div class="sep"></div>
      <button class="tb" onclick={handleToggleTheme}>{theme === 'dark' ? '\u2606' : '\u263E'}</button>
    </div>
  </header>

  <div class="main">
    <!-- Left sidebar -->
    {#if appState.sidebarOpen}
      <aside class="sb">
        <div class="sh">
          <div class="si"><input type="text" placeholder="Search... (⌘K)" bind:value={appState.searchQuery} /></div>
        </div>
        <TreeView
          nodes={graphState.nodes}
          expandedNodes={treeExpanded}
          selectedIds={appState.selectedIds}
          onselect={(id) => selectNode(id)}
          ontoggle={toggleTreeNode}
          ondblclick={(nodeId) => {
            if (!activeTab) return;
            // Don't add if already in tab
            if (activeTab.tabNodes.some(tn => (tn.nodeId || tn.id) === nodeId)) return;
            // Add to next available grid position
            const maxRow = activeTab.tabNodes.reduce((m, tn) => Math.max(m, tn.row || 0), -1);
            activeTab.tabNodes = [...activeTab.tabNodes, { nodeId, row: maxRow + 1, col: 0, cols: 3 }];
            appState.storeVersion++;
          }}
        />
        {#if activeTab}
          <div class="add-to-tab-hint">
            Double-click a tree node to add it to this tab
          </div>
        {/if}
      </aside>
    {/if}

    <!-- Canvas with tab bar -->
    <div class="canvas-col">
      <!-- Left edge toggle -->
      <button class="edge-toggle left" onclick={() => appState.sidebarOpen = !appState.sidebarOpen}>
        {appState.sidebarOpen ? '\u2039' : '\u203A'}
      </button>
      <!-- Right edge toggle -->
      <button class="edge-toggle right" onclick={() => appState.panelOpen = !appState.panelOpen}>
        {appState.panelOpen ? '\u203A' : '\u2039'}
      </button>
      <ViewTabs
        views={tabs}
        activeViewId={activeTab?.id || ''}
        oncreate={() => {
          const name = prompt('Tab name:');
          if (!name) return;
          const viewId = 'tab-' + Date.now();
          emitEvent({
            id: genId(), type: 'view.created', actor: 'user',
            data: { viewId, name, story: '', tabNodes: [], tabConnections: [] },
          });
          // Switch to new tab after a tick
          setTimeout(() => {
            const newIdx = graphState.views.findIndex(v => v.id === viewId);
            if (newIdx >= 0) activeTabIdx = newIdx;
          }, 100);
        }}
        onswitch={(id) => {
          activeTabIdx = tabs.findIndex(t => t.id === id);
          if (activeTabIdx < 0) activeTabIdx = 0;
          // Load saved positions for this tab
          fetch(`/api/layouts/${id}`).then(r => r.json()).then(data => {
            savedPositions = data || {};
          }).catch(() => { savedPositions = {}; });
        }}
      />

      <!-- Connect mode indicator -->
      {#if connectMode.active}
        <div class="connect-hint">Click target node to connect from "{graphState.nodes.get(connectMode.fromId)?.label}" — right-click to cancel</div>
      {/if}

      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div oncontextmenu={handleCanvasContextMenu}>
      <Canvas>
        <!-- Tab story overlay — visible context for what this diagram shows -->
        {#if activeTab?.story || activeTab?.description}
          <foreignObject x="12" y="12" width="440" height="80">
            <div xmlns="http://www.w3.org/1999/xhtml" style="background: var(--bg-s); border: 1px solid var(--bdr); border-radius: 8px; padding: 10px 14px; font-size: 12px; color: var(--tx-m); font-family: system-ui; line-height: 1.4; max-width: 420px;">
              <strong style="color: var(--tx); font-size: 13px; display: block; margin-bottom: 3px;">{activeTab.name}</strong>
              {activeTab.story || activeTab.description}
            </div>
          </foreignObject>
        {/if}

        <!-- Arrow markers -->
        <defs>
          {#each edgeColors as color}
            <marker id="arrow-{color.toLowerCase().replace('#', '')}" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
              <polygon points="0 0, 10 3.5, 0 7" fill={color} />
            </marker>
          {/each}
        </defs>

        <!-- Tab connections (authored edges for this diagram) -->
        {#each tabConnections as conn}
          {@const fromId = conn.from}
          {@const toId = conn.to}
          {#if activePositions.has(fromId) && activePositions.has(toId)}
            <EdgeLine
              edge={{ id: fromId + '-' + toId, ...conn }}
              fromPos={activePositions.get(fromId)}
              toPos={activePositions.get(toId)}
            />
          {/if}
        {/each}

        <!-- Nodes -->
        {#each tabNodes as tabNode}
          {@const nodeId = tabNode.nodeId || tabNode.id}
          {@const node = getNodeWithOverrides(tabNode)}
          {@const pos = activePositions.get(nodeId)}
          {#if node && pos}
            <NodeLeaf
              {node}
              {tabNode}
              {pos}
              isSelected={appState.selectedIds.has(nodeId)}
              comments={graphState.comments.filter(c => c.target === nodeId && !c.resolved)}
              onselect={selectNode}
              onstartdrag={startDrag}
              oncontextmenu={handleContextMenu}
            />
          {/if}
        {/each}
      </Canvas>
      </div>
    </div>

    <!-- Right panel -->
    {#if appState.panelOpen}
      <aside class="rp">
        <DetailPanel
          node={selectedNode}
          nodes={graphState.nodes}
          store={appState.store}
          comments={graphState.comments}
          onselect={(id) => selectNode(id)}
          onclose={() => appState.panelOpen = false}
          onaddcomment={(node) => { commentModal = { visible: true, node }; }}
          onresolve={handleResolveComment}
          ondelete={handleDeleteComment}
        />
      </aside>
    {/if}
  </div>

  <!-- Comment bar -->
  <CommentBar
    comments={graphState.comments}
    onresolve={handleResolveComment}
    ondelete={handleDeleteComment}
    onnavigate={(nodeId) => { appState.selectedIds = new Set([nodeId]); appState.panelOpen = true; }}
  />

  <!-- Context menu -->
  <ContextMenu
    x={ctxMenu.x} y={ctxMenu.y}
    visible={ctxMenu.visible}
    node={ctxMenu.node}
    isCanvas={ctxMenu.isCanvas}
    onaction={handleCtxAction}
    onclose={() => ctxMenu = { ...ctxMenu, visible: false }}
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
  .zd { font-size: 11px; color: var(--tx-d); min-width: 36px; text-align: center; }

  .main { flex: 1; display: flex; min-height: 0; }
  .canvas-col { flex: 1; display: flex; flex-direction: column; min-height: 0; min-width: 0; position: relative; }
  .edge-toggle { position: absolute; top: 50%; z-index: 15; width: 16px; height: 44px; background: var(--bg-s); border: 1px solid var(--bdr); display: flex; align-items: center; justify-content: center; cursor: pointer; font-size: 11px; color: var(--tx-d); transition: .15s; }
  .edge-toggle:hover { border-color: var(--ac); color: var(--ac); }
  .edge-toggle.left { left: 0; border-radius: 0 4px 4px 0; border-left: none; transform: translateY(-50%); }
  .edge-toggle.right { right: 0; border-radius: 4px 0 0 4px; border-right: none; transform: translateY(-50%); }

  .sb { width: 240px; background: var(--gl); backdrop-filter: blur(16px); border-right: 1px solid var(--gl-b); flex-shrink: 0; display: flex; flex-direction: column; }
  .sh { padding: 10px 12px; border-bottom: 1px solid var(--bdr); }
  .si { display: flex; background: var(--bg); border: 1px solid var(--bdr); border-radius: 6px; padding: 9px 12px; }
  .si input { background: none; border: none; color: var(--tx); font-size: 12px; outline: none; width: 100%; }
  .connect-hint { position: absolute; top: 50px; left: 50%; transform: translateX(-50%); z-index: 20; background: var(--ac); color: white; padding: 6px 14px; border-radius: 6px; font-size: 12px; pointer-events: none; }
  .add-to-tab-hint { font-size: 10px; color: var(--tx-d); text-align: center; padding: 6px 12px; border-top: 1px solid var(--bdr); }
  .rp { width: 280px; background: var(--gl); backdrop-filter: blur(16px); border-left: 1px solid var(--gl-b); flex-shrink: 0; }

  /* CommentBar component handles its own styling */

  .sl { height: 22px; background: var(--bg-s); border-top: 1px solid var(--bdr); display: flex; align-items: center; padding: 0 14px; gap: 14px; font-size: 10px; flex-shrink: 0; }
  .ok { color: var(--gr); }
  .err { color: var(--or); }
  .inf { color: var(--tx-d); }
</style>
