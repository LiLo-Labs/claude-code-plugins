<script>
  import './app.css';
  import { onMount } from 'svelte';
  import { getInitialTheme, setTheme, toggleTheme } from './lib/theme.js';
  import { appState, loadFromServer } from './lib/state.svelte.js';
  import { computeLayout, getAncestors } from './lib/layout.js';
  import Canvas from './components/Canvas.svelte';
  import NodeLeaf from './components/NodeLeaf.svelte';
  import NodeContainer from './components/NodeContainer.svelte';
  import EdgeLine from './components/EdgeLine.svelte';
  import TreeView from './components/TreeView.svelte';
  import DetailPanel from './components/DetailPanel.svelte';

  let theme = $state('dark');
  let expandedNodes = $state(new Set());

  onMount(async () => {
    theme = getInitialTheme();
    setTheme(theme);
    await loadFromServer();
    // Auto-expand root nodes
    for (const [id, node] of appState.store.getState().nodes) {
      if (!node.parent) expandedNodes.add(id);
    }
    expandedNodes = new Set(expandedNodes);
  });

  const graphState = $derived(appState.store.getState());
  const positions = $derived(computeLayout(graphState.nodes, expandedNodes));
  const unresolvedCount = $derived(graphState.comments.filter(c => !c.resolved).length);
  const selectedNode = $derived(
    appState.selectedIds.size === 1
      ? graphState.nodes.get([...appState.selectedIds][0]) || null
      : null
  );
  const selectedAncestorIds = $derived(() => {
    if (!selectedNode) return new Set();
    return new Set(getAncestors(selectedNode.id, graphState.nodes).map(n => n.id));
  });

  // Unique edge colors for arrow markers
  const edgeColors = $derived([...new Set([...graphState.edges.values()].map(e => e.color))]);

  function toggleExpand(nodeId) {
    expandedNodes.has(nodeId) ? expandedNodes.delete(nodeId) : expandedNodes.add(nodeId);
    expandedNodes = new Set(expandedNodes);
  }

  function deepToggle(nodeId) {
    const expand = !expandedNodes.has(nodeId);
    function recurse(id) {
      expand ? expandedNodes.add(id) : expandedNodes.delete(id);
      [...graphState.nodes.values()].filter(n => n.parent === id).forEach(c => recurse(c.id));
    }
    recurse(nodeId);
    expandedNodes = new Set(expandedNodes);
  }

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
          expandedNodes={expandedNodes}
          selectedIds={appState.selectedIds}
          onselect={(id) => selectNode(id)}
          ontoggle={toggleExpand}
          ondeeptoggle={deepToggle}
        />
      </aside>
    {/if}

    <!-- Canvas -->
    <Canvas>
      <!-- SVG defs -->
      <defs>
        {#each edgeColors as color}
          <marker id="arrow-{color.replace('#', '')}" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
            <polygon points="0 0, 10 3.5, 0 7" fill={color} />
          </marker>
        {/each}
        <pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="8" height="8" fill="var(--bg-n)" />
          <line x1="0" y1="0" x2="0" y2="8" stroke="var(--bdr)" stroke-width="2" />
        </pattern>
      </defs>

      <!-- Containers (rendered first, behind everything) -->
      {#each [...positions.entries()] as [nodeId, pos]}
        {#if pos.isContainer}
          <NodeContainer
            node={graphState.nodes.get(nodeId)}
            {pos}
            isSelected={appState.selectedIds.has(nodeId)}
            isAncestor={selectedAncestorIds().has(nodeId)}
            ontoggle={toggleExpand}
            ondeeptoggle={deepToggle}
            onselect={selectNode}
          />
        {/if}
      {/each}

      <!-- Edges — only render when BOTH endpoints are visible on canvas -->
      {#each [...graphState.edges.values()] as edge}
        {#if positions.has(edge.from) && positions.has(edge.to) && (positions.get(edge.from).isContainer || !positions.get(edge.from).hidden) && (positions.get(edge.to).isContainer || !positions.get(edge.to).hidden)}
          <EdgeLine {edge} fromPos={positions.get(edge.from)} toPos={positions.get(edge.to)} />
        {/if}
      {/each}

      <!-- Leaf nodes -->
      {#each [...positions.entries()] as [nodeId, pos]}
        {#if !pos.isContainer}
          <NodeLeaf
            node={graphState.nodes.get(nodeId)}
            {pos}
            isSelected={appState.selectedIds.has(nodeId)}
            isAncestor={selectedAncestorIds().has(nodeId)}
            children={[...graphState.nodes.values()].filter(n => n.parent === nodeId)}
            comments={graphState.comments.filter(c => c.target === nodeId && !c.resolved)}
            onselect={selectNode}
            ontoggle={toggleExpand}
            ondeeptoggle={deepToggle}
          />
        {/if}
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
    <span class="ok">&#9679; Synced</span>
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
  .inf { color: var(--tx-d); }
</style>
