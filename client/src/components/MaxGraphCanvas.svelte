<script>
  import { onMount, onDestroy } from 'svelte';
  import { createGraph, loadXml, serializeXml, zoomToFit } from '../lib/maxgraph.js';

  let { xml = '', dark = true, onchange, onselect, oncontextmenu: onctx } = $props();

  let containerEl = $state(null);
  let graph = null;
  let loadedXml = '';
  let saveTimer = null;

  onMount(async () => {
    const result = await createGraph(containerEl);
    graph = result.graph;

    containerEl.style.background = 'var(--graph-bg)';

    const { InternalEvent } = await import('@maxgraph/core');

    graph.getDataModel().addListener(InternalEvent.CHANGE, () => {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        const xmlStr = serializeXml(graph);
        if (xmlStr && xmlStr !== loadedXml) {
          loadedXml = xmlStr;
          onchange?.(xmlStr);
        }
      }, 1000);
    });

    graph.getSelectionModel().addListener(InternalEvent.CHANGE, () => {
      const cells = graph.getSelectionCells();
      const ids = cells.filter(c => c.id && c.id !== '0' && c.id !== '1').map(c => c.id);
      onselect?.(ids);
    });

    graph.addListener(InternalEvent.CLICK, (sender, evt) => {
      const cell = evt.getProperty('cell');
      if (cell && cell.id) onselect?.([cell.id]);
    });

    containerEl.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      const cell = graph.getCellAt(e.offsetX, e.offsetY);
      if (cell && cell.id && cell.id !== '0' && cell.id !== '1') {
        onctx?.({ x: e.clientX, y: e.clientY, cellId: cell.id });
      }
    });

    if (xml) {
      loadXml(graph, xml);
      loadedXml = xml;
      zoomToFit(graph, containerEl);
    }
  });

  onDestroy(() => {
    clearTimeout(saveTimer);
    if (graph) { graph.destroy(); graph = null; }
  });

  $effect(() => {
    const currentXml = xml;
    if (graph && currentXml !== loadedXml) {
      loadXml(graph, currentXml);
      loadedXml = currentXml;
      zoomToFit(graph, containerEl);
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
