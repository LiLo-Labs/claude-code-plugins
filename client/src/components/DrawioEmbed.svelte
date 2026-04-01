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
    const { Graph, InternalEvent, xmlUtils, Codec, registerAllCodecs, UndoManager, constants } = await import('@maxgraph/core');
    await import('@maxgraph/core/css/common.css');

    registerAllCodecs();

    // Container needs tabindex for keyboard events
    containerEl.setAttribute('tabindex', '0');
    containerEl.style.outline = 'none';
    containerEl.style.background = dark ? '#1a1a2e' : '#ffffff';

    try {
      graph = new Graph(containerEl);
    } catch(e) {
      console.error('Graph creation failed:', e);
      return;
    }

    // Graph settings
    graph.setEnabled(true);
    graph.setPanning(true);
    graph.setTooltips(true);
    graph.setConnectable(true);
    graph.setCellsEditable(true);
    graph.setCellsMovable(true);
    graph.setCellsResizable(true);
    graph.setCellsCloneable(false);

    // Default edge style: curved, rounded
    const edgeStyle = graph.getStylesheet().getDefaultEdgeStyle();
    edgeStyle.rounded = true;
    edgeStyle.curved = true;
    edgeStyle.strokeColor = '#999999';
    edgeStyle.fontSize = 11;
    edgeStyle.fontColor = '#888888';

    // Undo/redo manager
    const undoMgr = new UndoManager();
    const undoListener = (sender, evt) => undoMgr.undoableEditHappened(evt.getProperty('edit'));
    graph.getDataModel().addListener(InternalEvent.UNDO, undoListener);
    graph.getView().addListener(InternalEvent.UNDO, undoListener);

    // Keyboard: Ctrl/Cmd+Z = undo, Ctrl/Cmd+Shift+Z or Ctrl/Cmd+Y = redo, Delete = remove
    containerEl.addEventListener('keydown', (e) => {
      if (!graph) return;
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key === 'z' && !e.shiftKey) {
        e.preventDefault();
        undoMgr.undo();
      } else if (mod && e.key === 'z' && e.shiftKey) {
        e.preventDefault();
        undoMgr.redo();
      } else if (mod && e.key === 'y') {
        e.preventDefault();
        undoMgr.redo();
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        if (!graph.isEditing()) {
          e.preventDefault();
          graph.removeCells();
        }
      }
    });

    // Auto-focus container on click so keyboard works
    containerEl.addEventListener('mousedown', () => containerEl.focus());

    // Auto-save: serialize graph to XML on changes (debounced)
    let saveTimer = null;
    const saveChanges = () => {
      if (!graph || !onchange) return;
      try {
        const encoder = new Codec();
        const result = encoder.encode(graph.getDataModel());
        const xmlStr = xmlUtils.getXml(result);
        if (xmlStr && xmlStr !== loadedXml) {
          loadedXml = xmlStr;
          onchange(xmlStr);
        }
      } catch(e) {
        console.warn('Failed to serialize graph:', e);
      }
    };
    graph.getDataModel().addListener(InternalEvent.CHANGE, () => {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(saveChanges, 1000);
    });

    // Selection listener
    graph.getSelectionModel().addListener(InternalEvent.CHANGE, () => {
      const cells = graph.getSelectionCells();
      const ids = cells
        .filter(c => c.id && c.id !== '0' && c.id !== '1')
        .map(c => c.id);
      onselect?.(ids);
    });

    // Click handler (backup for selection)
    graph.addListener(InternalEvent.CLICK, (sender, evt) => {
      const cell = evt.getProperty('cell');
      if (cell && cell.id) {
        onselect?.([cell.id]);
      }
    });

    if (xml) {
      loadXml(xml, graph, Codec, xmlUtils);
    }

    window._canvasGraph = { graph, Codec, xmlUtils, undoMgr };
  });

  function loadXml(xmlStr, g, CodecClass, utils) {
    if (!g || !xmlStr) return;
    loadedXml = xmlStr;
    try {
      g.getDataModel().beginUpdate();
      try {
        g.getDataModel().clear();
      } finally {
        g.getDataModel().endUpdate();
      }
      const doc = utils.parseXml(xmlStr);
      const codec = new CodecClass(doc);
      codec.decode(doc.documentElement, g.getDataModel());
      g.refresh();
      // Zoom to fit
      try {
        const bounds = g.getGraphBounds();
        if (bounds && bounds.width > 0 && bounds.height > 0) {
          const cw = containerEl.offsetWidth;
          const ch = containerEl.offsetHeight;
          const pad = 40;
          const scale = Math.min((cw - pad * 2) / bounds.width, (ch - pad * 2) / bounds.height, 1.5);
          g.getView().scaleAndTranslate(scale, -bounds.x + pad / scale, -bounds.y + pad / scale);
        }
      } catch {}
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
    const currentXml = xml;
    if (graph && currentXml !== loadedXml && window._canvasGraph) {
      const { graph: g, Codec: C, xmlUtils: u } = window._canvasGraph;
      loadXml(currentXml, g, C, u);
    }
  });

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
    cursor: default;
  }
  .graph-container:focus {
    outline: none;
  }
</style>
