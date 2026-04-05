<script>
  import { onMount, onDestroy } from 'svelte';
  import { createGraph, loadXml, serializeXml, zoomToFit } from '../lib/maxgraph.js';

  let { xml = '', dark = true, onchange, onselect, oncontextmenu: onctx, oncelladded, oncellremoved } = $props();

  let containerEl = $state(null);
  let graph = null;
  let loadedXml = '';
  let saveTimer = null;
  let suppressCellEvents = false; // Suppress during XML load (not user actions)

  onMount(async () => {
    const result = await createGraph(containerEl);
    graph = result.graph;

    containerEl.style.background = 'var(--graph-bg)';

    const { InternalEvent } = await import('@maxgraph/core');

    // Debounced auto-save on any change
    graph.getDataModel().addListener(InternalEvent.CHANGE, (sender, evt) => {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        const xmlStr = serializeXml(graph);
        if (xmlStr && xmlStr !== loadedXml) {
          loadedXml = xmlStr;
          onchange?.(xmlStr);
        }
      }, 1000);

      // Detect user-added cells
      if (suppressCellEvents) return;
      const changes = evt.getProperty('edit')?.changes || [];
      for (const change of changes) {
        // ChildChange = cell added or removed from model
        if (change.constructor?.name === 'ChildChange') {
          const cell = change.child;
          if (!cell || cell.id === '0' || cell.id === '1') continue;

          if (change.parent && !change.previous) {
            // Cell was added (has new parent, no previous parent)
            if (cell.isVertex() && cell.value) {
              oncelladded?.({ id: cell.id, label: String(cell.value || ''), isEdge: false });
            } else if (cell.isEdge() && cell.source && cell.target) {
              oncelladded?.({ id: cell.id, label: String(cell.value || ''), isEdge: true, from: cell.source.id, to: cell.target.id });
            }
          } else if (!change.parent && change.previous) {
            // Cell was removed (no parent, had previous parent)
            oncellremoved?.({ id: cell.id, isEdge: cell.isEdge() });
          }
        }
      }
    });

    // Selection
    graph.getSelectionModel().addListener(InternalEvent.CHANGE, () => {
      const cells = graph.getSelectionCells();
      const ids = cells.filter(c => c.id && c.id !== '0' && c.id !== '1').map(c => c.id);
      onselect?.(ids);
    });

    graph.addListener(InternalEvent.CLICK, (sender, evt) => {
      const cell = evt.getProperty('cell');
      if (cell && cell.id) onselect?.([cell.id]);
    });

    // Right-click context menu
    containerEl.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      const cell = graph.getCellAt(e.offsetX, e.offsetY);
      if (cell && cell.id && cell.id !== '0' && cell.id !== '1') {
        onctx?.({ x: e.clientX, y: e.clientY, cellId: cell.id });
      }
    });

    if (xml) {
      suppressCellEvents = true;
      loadXml(graph, xml);
      loadedXml = xml;
      zoomToFit(graph, containerEl);
      suppressCellEvents = false;
    }
  });

  onDestroy(() => {
    clearTimeout(saveTimer);
    if (graph) { graph.destroy(); graph = null; }
  });

  // React to xml prop changes (tab switching, SSE updates)
  $effect(() => {
    const currentXml = xml;
    if (graph && currentXml !== loadedXml) {
      suppressCellEvents = true;
      loadXml(graph, currentXml);
      loadedXml = currentXml;
      zoomToFit(graph, containerEl);
      suppressCellEvents = false;
    }
  });

  $effect(() => {
    if (containerEl) {
      containerEl.style.background = 'var(--graph-bg)';
    }
  });
</script>

<div class="graph-container" bind:this={containerEl}></div>

<style>
  .graph-container {
    width: 100%; height: 100%; min-height: 400px;
    overflow: hidden; position: relative; cursor: default;
  }
  .graph-container:focus { outline: none; }
</style>
