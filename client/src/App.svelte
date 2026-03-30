<script>
  import './app.css';
  import { onMount } from 'svelte';
  import { getInitialTheme, setTheme, toggleTheme } from './lib/theme.js';
  import { appState, loadFromServer } from './lib/state.svelte.js';
  import { computeLayout, getAncestors } from './lib/layout.js';
  import { createDragState, toSvgPoint } from './lib/drag.js';
  import Canvas from './components/Canvas.svelte';
  import NodeLeaf from './components/NodeLeaf.svelte';
  import EdgeLine from './components/EdgeLine.svelte';
  import ViewTabs from './components/ViewTabs.svelte';
  import TreeView from './components/TreeView.svelte';
  import DetailPanel from './components/DetailPanel.svelte';

  let theme = $state('dark');
  let activeTabIdx = $state(0);
  let savedPositions = $state({});
  let drag = $state(createDragState());
  let treeExpanded = $state(new Set());

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
    if (drag.active) drag = createDragState();
  }

  // Tree
  function toggleTreeNode(nodeId) {
    treeExpanded.has(nodeId) ? treeExpanded.delete(nodeId) : treeExpanded.add(nodeId);
    treeExpanded = new Set(treeExpanded);
  }

  function handleToggleTheme() { theme = toggleTheme(); }
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
      <button class="tb" onclick={() => { appState.zoom = 1; appState.panX = 0; appState.panY = 0; }}>&#8962;</button>
      <div class="sep"></div>
      <button class="tb" onclick={handleToggleTheme}>{theme === 'dark' ? '\u2606' : '\u263E'}</button>
    </div>
  </header>

  <div class="main">
    <!-- Left sidebar -->
    {#if appState.sidebarOpen}
      <aside class="sb">
        <div class="sh">
          <div class="si"><input type="text" placeholder="Search... (\u2318K)" bind:value={appState.searchQuery} /></div>
        </div>
        <TreeView
          nodes={graphState.nodes}
          expandedNodes={treeExpanded}
          selectedIds={appState.selectedIds}
          onselect={(id) => selectNode(id)}
          ontoggle={toggleTreeNode}
        />
      </aside>
    {/if}

    <!-- Canvas with tab bar — single unified tab strip (G6) -->
    <div class="canvas-col">
      <ViewTabs
        views={tabs}
        activeViewId={activeTab?.id || ''}
        onswitch={(id) => { activeTabIdx = tabs.findIndex(t => t.id === id); if (activeTabIdx < 0) activeTabIdx = 0; savedPositions = {}; }}
      />

      <Canvas>
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
            />
          {/if}
        {/each}
      </Canvas>
    </div>

    <!-- Right panel -->
    {#if appState.panelOpen}
      <aside class="rp">
        <DetailPanel
          node={selectedNode}
          nodes={graphState.nodes}
          store={appState.store}
          onselect={(id) => selectNode(id)}
          onclose={() => appState.panelOpen = false}
        />
      </aside>
    {/if}
  </div>

  <!-- Comment bar -->
  <div class="cbar">
    <span class="cl">Comments</span>
    <span class="cb">{unresolvedCount}</span>
  </div>

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
  .canvas-col { flex: 1; display: flex; flex-direction: column; min-height: 0; min-width: 0; }

  .sb { width: 240px; background: var(--gl); backdrop-filter: blur(16px); border-right: 1px solid var(--gl-b); flex-shrink: 0; display: flex; flex-direction: column; }
  .sh { padding: 10px 12px; border-bottom: 1px solid var(--bdr); }
  .si { display: flex; background: var(--bg); border: 1px solid var(--bdr); border-radius: 6px; padding: 9px 12px; }
  .si input { background: none; border: none; color: var(--tx); font-size: 12px; outline: none; width: 100%; }
  .rp { width: 280px; background: var(--gl); backdrop-filter: blur(16px); border-left: 1px solid var(--gl-b); flex-shrink: 0; }

  .cbar { height: 28px; background: var(--gl); backdrop-filter: blur(16px); border-top: 1px solid var(--gl-b); display: flex; align-items: center; padding: 0 14px; gap: 6px; flex-shrink: 0; }
  .cl { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: var(--tx-d); }
  .cb { font-size: 10px; background: var(--ac); color: white; padding: 0 5px; border-radius: 7px; font-weight: 600; }

  .sl { height: 22px; background: var(--bg-s); border-top: 1px solid var(--bdr); display: flex; align-items: center; padding: 0 14px; gap: 14px; font-size: 10px; flex-shrink: 0; }
  .ok { color: var(--gr); }
  .err { color: var(--or); }
  .inf { color: var(--tx-d); }
</style>
