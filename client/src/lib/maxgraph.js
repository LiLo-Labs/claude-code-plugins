// client/src/lib/maxgraph.js

let mgModules = null;

async function getModules() {
  if (mgModules) return mgModules;
  const mg = await import('@maxgraph/core');
  await import('@maxgraph/core/css/common.css');
  mg.registerAllCodecs();
  mgModules = mg;
  return mg;
}

export async function createGraph(container) {
  const { Graph, InternalEvent, UndoManager } = await getModules();

  container.setAttribute('tabindex', '0');
  container.style.outline = 'none';

  const graph = new Graph(container);
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

  // Undo manager
  const undoMgr = new UndoManager();
  const undoListener = (sender, evt) => undoMgr.undoableEditHappened(evt.getProperty('edit'));
  graph.getDataModel().addListener(InternalEvent.UNDO, undoListener);
  graph.getView().addListener(InternalEvent.UNDO, undoListener);

  // Native keyboard for undo/redo (KeyHandler is unreliable)
  container.addEventListener('keydown', (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key === 'z' && !e.shiftKey) { e.preventDefault(); undoMgr.undo(); }
    else if (mod && (e.key === 'z' && e.shiftKey || e.key === 'y')) { e.preventDefault(); undoMgr.redo(); }
    else if ((e.key === 'Delete' || e.key === 'Backspace') && !graph.isEditing()) { e.preventDefault(); graph.removeCells(); }
  });

  // Auto-focus on click
  container.addEventListener('mousedown', () => container.focus());

  return { graph, undoMgr };
}

export function loadXml(graph, xmlStr) {
  if (!graph || !xmlStr) return;
  const { Codec, xmlUtils } = mgModules;
  try {
    // model.clear() first — codec merges, doesn't replace
    graph.getDataModel().beginUpdate();
    try { graph.getDataModel().clear(); } finally { graph.getDataModel().endUpdate(); }

    const doc = xmlUtils.parseXml(xmlStr);
    const codec = new Codec(doc);
    codec.decode(doc.documentElement, graph.getDataModel());
    graph.refresh();
  } catch (e) {
    console.warn('Failed to load XML:', e);
  }
}

export function serializeXml(graph) {
  if (!graph) return '';
  const { Codec, xmlUtils } = mgModules;
  try {
    const encoder = new Codec();
    const result = encoder.encode(graph.getDataModel());
    return xmlUtils.getXml(result);
  } catch (e) {
    console.warn('Failed to serialize graph:', e);
    return '';
  }
}

export function zoomToFit(graph, container) {
  if (!graph || !container) return;
  try {
    const bounds = graph.getGraphBounds();
    if (bounds && bounds.width > 0 && bounds.height > 0) {
      const cw = container.offsetWidth;
      const ch = container.offsetHeight;
      const pad = 40;
      const scale = Math.min((cw - pad * 2) / bounds.width, (ch - pad * 2) / bounds.height, 1.5);
      graph.getView().scaleAndTranslate(scale, -bounds.x + pad / scale, -bounds.y + pad / scale);
    }
  } catch {}
}
