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
    const { Graph, InternalEvent, ModelXmlSerializer, xmlUtils, Codec, registerAllCodecs, UndoManager, KeyHandler } = await import('@maxgraph/core');
    await import('@maxgraph/core/css/common.css');

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
    graph.setConnectable(true);
    graph.setCellsEditable(true);
    graph.setCellsMovable(true);
    graph.setCellsResizable(true);
    graph.setCellsCloneable(false);

    // Live preview during drag (move the actual shape, not an outline)
    graph.graphHandler.livePreview = true;
    graph.graphHandler.guidesEnabled = true;

    containerEl.style.background = dark ? '#1a1a2e' : '#ffffff';

    // Undo/redo
    const undoMgr = new UndoManager();
    const listener = (sender, evt) => undoMgr.undoableEditHappened(evt.getProperty('edit'));
    graph.getDataModel().addListener(InternalEvent.UNDO, listener);
    graph.getView().addListener(InternalEvent.UNDO, listener);

    // Keyboard shortcuts
    const keyHandler = new KeyHandler(graph);
    // Cmd/Ctrl+Z = undo
    keyHandler.bindControlKey(90, () => undoMgr.undo());
    // Cmd/Ctrl+Shift+Z = redo
    keyHandler.bindControlShiftKey(90, () => undoMgr.redo());
    // Cmd/Ctrl+Y = redo (Windows convention)
    keyHandler.bindControlKey(89, () => undoMgr.redo());
    // Delete/Backspace = delete selected
    keyHandler.bindKey(46, () => graph.removeCells());
    keyHandler.bindKey(8, () => graph.removeCells());

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

  // Update background when theme changes
  $effect(() => {
    if (containerEl) {
      containerEl.style.background = dark ? '#1a1a2e' : '#ffffff';
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
