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
    const { Graph, InternalEvent, ModelXmlSerializer, xmlUtils, Codec, registerAllCodecs } = await import('@maxgraph/core');
    await import('@maxgraph/core/css/common.css');

    // Register all codecs so we can parse draw.io XML
    registerAllCodecs();

    try {
      graph = new Graph(containerEl);
    } catch(e) {
      console.error('Graph creation failed:', e);
      containerEl.textContent = 'Graph failed to load: ' + e.message;
      return;
    }
    graph.setEnabled(true);
    graph.setPanning(true);
    graph.setTooltips(true);
    graph.setConnectable(false);
    graph.setCellsEditable(false);    // no inline text editing
    graph.setCellsMovable(false);     // no dragging shapes
    graph.setCellsResizable(false);   // no resize handles
    graph.setCellsDeletable(false);   // no delete
    graph.setCellsCloneable(false);   // no clone on drag
    graph.setDropEnabled(false);      // no drop

    if (dark) {
      containerEl.style.background = '#1a1a2e';
    }

    // Selection listener — click a shape, get its ID
    graph.getSelectionModel().addListener(InternalEvent.CHANGE, () => {
      const cells = graph.getSelectionCells();
      const ids = cells
        .filter(c => c.id && c.id !== '0' && c.id !== '1')
        .map(c => c.id);
      console.log('SELECTION:', ids);
      onselect?.(ids);
    });

    // Also try direct click handler as backup
    graph.addListener(InternalEvent.CLICK, (sender, evt) => {
      const cell = evt.getProperty('cell');
      if (cell && cell.id) {
        console.log('CLICK on cell:', cell.id, cell.value);
        onselect?.([cell.id]);
      }
    });

    if (xml) {
      loadXml(xml, graph, Codec, xmlUtils);
    }

    window._canvasGraph = { graph, Codec, xmlUtils };
  });

  function loadXml(xmlStr, g, CodecClass, utils) {
    if (!g || !xmlStr) return;
    loadedXml = xmlStr;
    try {
      const doc = utils.parseXml(xmlStr);
      const codec = new CodecClass(doc);
      codec.decode(doc.documentElement, g.getDataModel());
      g.refresh();
      try { g.fit(); } catch {}
      try { g.center(); } catch {}
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
      const { graph: g, Codec: C, xmlUtils: u } = window._canvasGraph;
      loadXml(xml, g, C, u);
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
