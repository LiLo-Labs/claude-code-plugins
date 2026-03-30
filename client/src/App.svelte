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
  import TreeView from './components/TreeView.svelte';
  import DetailPanel from './components/DetailPanel.svelte';

  let theme = $state('dark');
  let savedPositions = $state({}); // user drag overrides: { nodeId: {x, y} }
  let drag = $state(createDragState());
  let canvasComponent = $state(null);

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

  // Grid layout + user drag overrides
  const activePositions = $derived(computeLayout(graphState.nodes, savedPositions));

  // Drag handlers
  function startDrag(nodeId, e) {
    const svgEl = canvasComponent?.getSvgEl?.() || document.querySelector('.canvas-svg');
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
    const dx = pt.x - drag.startX;
    const dy = pt.y - drag.startY;
    savedPositions = { ...savedPositions, [drag.nodeId]: { x: drag.origX + dx, y: drag.origY + dy } };
  }

  function handleMouseUp() {
    if (drag.active) {
      drag = createDragState();
      // TODO: persist savedPositions to server layout API
    }
  }
  const unresolvedCount = $derived(graphState.comments.filter(c => !c.resolved).length);
  const selectedNode = $derived(
    appState.selectedIds.size === 1
      ? graphState.nodes.get([...appState.selectedIds][0]) || null
      : null
  );
  const selectedAncestorIds = $derived(
    selectedNode
      ? new Set(getAncestors(selectedNode.id, graphState.nodes).map(n => n.id))
      : new Set()
  );

  const edgeColors = $derived([...new Set([...graphState.edges.values()].map(e => e.color))]);

  function selectNode(nodeId, e) {
    if (e?.shiftKey) {
      const next = new Set(appState.selectedIds);
      next.has(nodeId) ? next.delete(nodeId) : next.add(nodeId);
      appState.selectedIds = next;
    } else {
      appState.selectedIds = new Set([nodeId]);
    }
  }

  function handleToggleTheme() { theme = toggleTheme(); }

  const viewModes = ['Canvas', 'Timeline', 'Diff', 'Story'];
</script>

<svelte:window onmousemove={handleMouseMove} onmouseup={handleMouseUp} />

<div class="layout">
  <!-- Topbar -->
  <header class="topbar">
    <div class="tp"><span class="dot"></span> Code Canvas</div>
    <div class="vt">
      {#each viewModes as mode}
        <button class:active={appState.activeViewMode === mode.toLowerCase()} onclick={() => appState.activeViewMode = mode.toLowerCase()}>{mode}</button>
      {/each}
    </div>
    <div class="sep"></div>
    <div class="tr">
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
          expandedNodes={new Set()}
          selectedIds={appState.selectedIds}
          onselect={(id) => selectNode(id)}
        />
      </aside>
    {/if}

    <!-- Canvas -->
    <Canvas>
      <!-- Arrow markers -->
      <defs>
        {#each edgeColors as color}
          <marker id="arrow-{color.replace('#', '')}" markerWidth="12" markerHeight="8" refX="11" refY="4" orient="auto">
            <polygon points="0 0, 12 4, 0 8" fill={color} />
          </marker>
        {/each}
      </defs>

      <!-- Edges (drawn first, behind nodes) -->
      {#each [...graphState.edges.values()] as edge}
        {#if activePositions.has(edge.from) && activePositions.has(edge.to)}
          <EdgeLine {edge} fromPos={activePositions.get(edge.from)} toPos={activePositions.get(edge.to)} />
        {/if}
      {/each}

      <!-- Nodes -->
      {#each [...activePositions.entries()] as [nodeId, pos]}
        <NodeLeaf
          node={graphState.nodes.get(nodeId)}
          {pos}
          isSelected={appState.selectedIds.has(nodeId)}
          comments={graphState.comments.filter(c => c.target === nodeId && !c.resolved)}
          onselect={selectNode}
          onstartdrag={startDrag}
        />
      {/each}
    </Canvas>

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
    <span class="inf">{graphState.edges.size} edges</span>
    <span class="inf">{graphState.eventCount} events</span>
  </footer>
</div>

<style>
  .layout { display: flex; flex-direction: column; height: 100vh; }
  .topbar { display: flex; align-items: center; height: 44px; background: var(--bg-s); border-bottom: 1px solid var(--bdr); padding: 0 16px; flex-shrink: 0; gap: 10px; }
  .tp { font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 6px; margin-right: 16px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--yl); }
  .vt { display: flex; gap: 1px; background: var(--bdr); border-radius: 6px; overflow: hidden; }
  .vt button { padding: 7px 16px; border: none; background: var(--bg-s); color: var(--tx-d); font-size: 12px; font-weight: 500; transition: .15s; }
  .vt button:hover { color: var(--tx-m); }
  .vt button.active { background: var(--bg-e); color: var(--ac); }
  .sep { width: 1px; height: 18px; background: var(--bdr); margin: 0 6px; }
  .tr { margin-left: auto; display: flex; gap: 4px; align-items: center; }
  .tb { height: 32px; padding: 0 10px; border: 1px solid var(--bdr); border-radius: 4px; background: transparent; color: var(--tx-m); font-size: 12px; transition: .15s; }
  .tb:hover { border-color: var(--ac); color: var(--ac); }
  .zd { font-size: 11px; color: var(--tx-d); min-width: 36px; text-align: center; }

  .main { flex: 1; display: flex; min-height: 0; }
  .sb { width: 260px; background: var(--gl); backdrop-filter: blur(16px); border-right: 1px solid var(--gl-b); flex-shrink: 0; display: flex; flex-direction: column; }
  .sh { padding: 10px 12px; border-bottom: 1px solid var(--bdr); }
  .si { display: flex; background: var(--bg); border: 1px solid var(--bdr); border-radius: 6px; padding: 9px 12px; }
  .si input { background: none; border: none; color: var(--tx); font-size: 12px; outline: none; width: 100%; }
  .rp { width: 300px; background: var(--gl); backdrop-filter: blur(16px); border-left: 1px solid var(--gl-b); flex-shrink: 0; }

  .cbar { height: 28px; background: var(--gl); backdrop-filter: blur(16px); border-top: 1px solid var(--gl-b); display: flex; align-items: center; padding: 0 14px; gap: 6px; flex-shrink: 0; }
  .cl { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: var(--tx-d); }
  .cb { font-size: 10px; background: var(--ac); color: white; padding: 0 5px; border-radius: 7px; font-weight: 600; }

  .sl { height: 22px; background: var(--bg-s); border-top: 1px solid var(--bdr); display: flex; align-items: center; padding: 0 14px; gap: 14px; font-size: 10px; flex-shrink: 0; }
  .ok { color: var(--gr); }
  .err { color: var(--or); }
  .inf { color: var(--tx-d); }
</style>
