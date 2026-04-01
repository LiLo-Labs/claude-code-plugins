<script>
  /**
   * DrawioEmbed — renders draw.io XML using maxGraph (the engine behind draw.io).
   * Same origin, no iframe, full click access.
   */
  import { onMount, onDestroy } from 'svelte';

  let { xml = '', onchange, onselect, dark = true } = $props();

  let containerEl = $state(null);
  let graph = null;
  let loadedXml = '';

  onMount(async () => {
    const { Graph, InternalEvent, ModelXmlSerializer, xmlUtils } = await import('@maxgraph/core');
    await import('@maxgraph/core/css/common.css');

    graph = new Graph(containerEl);
    graph.setEnabled(true);
    graph.setPanning(true);
    if (graph.panningHandler) {
      graph.panningHandler.useLeftButtonForPanning = true;
    }
    graph.setTooltips(true);
    graph.setConnectable(false);

    if (dark) {
      containerEl.style.background = '#1a1a2e';
    }

    // Selection listener — click a shape, get its ID
    graph.getSelectionModel().addListener(InternalEvent.CHANGE, () => {
      const cells = graph.getSelectionCells();
      const ids = cells
        .filter(c => c.id && c.id !== '0' && c.id !== '1')
        .map(c => c.id);
      onselect?.(ids);
    });

    if (xml) {
      loadXml(xml, graph, ModelXmlSerializer, xmlUtils);
    }

    window._canvasGraph = { graph, ModelXmlSerializer, xmlUtils };
  });

  function loadXml(xmlStr, g, Serializer, utils) {
    if (!g || !xmlStr) return;
    loadedXml = xmlStr;
    try {
      g.getDataModel().beginUpdate();
      try {
        const root = g.getDataModel().getRoot();
        if (root) {
          while (root.getChildCount() > 0) {
            root.remove(root.getChildAt(0));
          }
        }
        const doc = utils.parseXml(xmlStr);
        const serializer = new Serializer(g.getDataModel());
        serializer.import(doc.documentElement);
      } finally {
        g.getDataModel().endUpdate();
      }
      g.fit();
      g.center();
    } catch (e) {
      console.warn('Failed to load XML:', e);
    }
  }

  onDestroy(() => {
    if (graph) {
      graph.destroy();
      graph = null;
    }
    delete window._canvasGraph;
  });

  $effect(() => {
    if (graph && xml !== loadedXml && window._canvasGraph) {
      const { graph: g, ModelXmlSerializer, xmlUtils } = window._canvasGraph;
      loadXml(xml, g, ModelXmlSerializer, xmlUtils);
    }
  });
</script>

<div class="graph-container" bind:this={containerEl}></div>

<style>
  .graph-container {
    width: 100%;
    height: 100%;
    min-height: 400px;
    overflow: hidden;
    position: relative;
  }
</style>
