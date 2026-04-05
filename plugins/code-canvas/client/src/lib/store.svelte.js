import { EventStore, genId } from './store.js';
import { fetchEvents, postEvent, subscribeSSE, fetchUserShapes, fetchCustomShapes } from './api.js';
import { updateShapeStatus } from './diagram-sync.js';
import { generateViewXml } from './auto-layout.js';
import { loadCustomShapes, getStyledShape } from './shapes/registry.js';

const pendingIds = new Set();

export const appState = $state({
  store: new EventStore(),
  storeVersion: 0,
  selectedIds: new Set(),
  syncError: false,
});

// Structural changes require full re-layout (new shapes, removed shapes, new views)
const STRUCTURAL_EVENTS = new Set([
  'node.created', 'node.deleted',
  'edge.created', 'edge.deleted',
  'view.created',
]);

// Style-only changes just update colors in-place (preserves user-arranged positions)
const STYLE_EVENTS = new Set([
  'node.status',
]);

/** Escape a string for safe use in XML attributes. */
function esc(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/** Splice a single new node cell into existing draw.io XML, placed below the lowest existing shape. */
function spliceNodeIntoXml(xml, node, nodeId) {
  const shape = getStyledShape(node);
  // Find max Y position in existing XML to place new node below
  const yMatches = [...xml.matchAll(/y="(\d+)"/g)];
  const maxY = yMatches.length > 0 ? Math.max(...yMatches.map(m => parseInt(m[1]))) : 0;
  const newY = maxY + 100;

  const label = node.subtitle
    ? `${esc(node.label)}&#xa;${esc(node.subtitle)}`
    : esc(node.label);

  const cell = `<mxCell id="${esc(nodeId)}" value="${label}" style="${shape.style}" vertex="1" parent="1"><mxGeometry x="40" y="${newY}" width="${shape.width}" height="${shape.height}" as="geometry"/></mxCell>`;

  return xml.replace('</root>', cell + '</root>');
}

/** Splice a single new edge cell into existing draw.io XML (only if both endpoints exist). */
function spliceEdgeIntoXml(xml, edge, edgeId) {
  if (!xml.includes(`id="${esc(edge.from)}"`) || !xml.includes(`id="${esc(edge.to)}"`)) return xml;

  const label = edge.label ? ` value="${esc(edge.label)}"` : '';
  const color = edge.color || '#8b949e';
  const cell = `<mxCell id="${esc(edgeId)}"${label} style="rounded=1;curved=1;strokeColor=${color};fontColor=#8b949e;fontSize=11;" edge="1" source="${esc(edge.from)}" target="${esc(edge.to)}" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>`;

  return xml.replace('</root>', cell + '</root>');
}

/** Remove an mxCell (node or edge) from draw.io XML by its ID using string search. */
function removeFromXml(xml, cellId) {
  const needle = `id="${esc(cellId)}"`;
  let result = xml;
  let searchFrom = 0;
  while (true) {
    const idx = result.indexOf(needle, searchFrom);
    if (idx === -1) break;
    // Walk back to find the opening '<mxCell'
    const tagStart = result.lastIndexOf('<mxCell', idx);
    if (tagStart === -1) { searchFrom = idx + needle.length; continue; }
    // Check for self-closing '/>' or closing '</mxCell>'
    const selfClose = result.indexOf('/>', tagStart);
    const childClose = result.indexOf('</mxCell>', tagStart);
    let tagEnd;
    if (selfClose !== -1 && (childClose === -1 || selfClose < childClose)) {
      tagEnd = selfClose + 2;
    } else if (childClose !== -1) {
      tagEnd = childClose + '</mxCell>'.length;
    } else {
      searchFrom = idx + needle.length; continue;
    }
    result = result.slice(0, tagStart) + result.slice(tagEnd);
    // Don't advance searchFrom — next match may now be at same position
  }
  return result;
}

/**
 * Sync diagrams after an event.
 * - Structural changes: full re-layout for views without XML; incremental splice for views with XML
 * - Status changes: update shape colors in-place (preserves layout)
 */
function syncDiagrams(event) {
  const state = appState.store.getState();

  if (STRUCTURAL_EVENTS.has(event.type)) {
    for (const view of state.views) {
      const v = appState.store._views.find(v => v.id === view.id);
      if (!v) continue;

      if (!view.drawioXml) {
        // No existing XML — full auto-layout
        v.drawioXml = generateViewXml(view, state.nodes, state.edges);
      } else if (event.type === 'node.created') {
        const nodeId = event.data.nodeId || event.data.id;
        const isInView = !view.tabNodes?.length || view.tabNodes.some(tn => (typeof tn === 'string' ? tn : tn.nodeId) === nodeId);
        if (isInView && nodeId) {
          const node = state.nodes instanceof Map ? state.nodes.get(nodeId) : state.nodes[nodeId];
          if (node) v.drawioXml = spliceNodeIntoXml(view.drawioXml, node, nodeId);
        }
      } else if (event.type === 'edge.created') {
        const edgeId = event.data.edgeId || event.data.id;
        const edge = state.edges instanceof Map ? state.edges.get(edgeId) : state.edges[edgeId];
        if (edge) v.drawioXml = spliceEdgeIntoXml(view.drawioXml, edge, edgeId);
      } else if (event.type === 'node.deleted') {
        const nodeId = event.data.nodeId;
        if (nodeId) v.drawioXml = removeFromXml(view.drawioXml, nodeId);
      } else if (event.type === 'edge.deleted') {
        const edgeId = event.data.edgeId;
        if (edgeId) v.drawioXml = removeFromXml(view.drawioXml, edgeId);
      }
      // view.created with existing XML — leave it alone
    }
  } else if (STYLE_EVENTS.has(event.type)) {
    // In-place color update — preserves positions
    for (const view of state.views) {
      if (view.drawioXml) {
        const updated = updateShapeStatus(view.drawioXml, event.data.nodeId, event.data.status);
        if (updated !== view.drawioXml) {
          const v = appState.store._views.find(v => v.id === view.id);
          if (v) v.drawioXml = updated;
        }
      }
    }
  }
}

export async function loadFromServer() {
  try {
    // Load shapes: user-level first, then project-level (project overrides user)
    try {
      const user = await fetchUserShapes();
      if (user && Object.keys(user).length > 0) loadCustomShapes(user);
    } catch {}
    try {
      const project = await fetchCustomShapes();
      if (project && Object.keys(project).length > 0) loadCustomShapes(project);
    } catch {}

    const events = await fetchEvents();
    appState.store = EventStore.fromEvents(events);

    // Generate diagrams only for views without existing XML (fallback auto-layout)
    const state = appState.store.getState();
    for (const view of state.views) {
      if (view.drawioXml) continue;
      const xml = generateViewXml(view, state.nodes, state.edges);
      const v = appState.store._views.find(v => v.id === view.id);
      if (v) v.drawioXml = xml;
    }

    appState.storeVersion++;
    appState.syncError = false;
  } catch (err) {
    console.error('Failed to load events:', err);
    appState.syncError = true;
  }
}

export async function emitEvent(event) {
  event.id = event.id || genId();
  pendingIds.add(event.id);
  appState.store.apply(event);
  syncDiagrams(event);
  appState.storeVersion++;
  try {
    await postEvent(event);
    appState.syncError = false;
  } catch (err) {
    console.error('Failed to save event:', err);
    appState.syncError = true;
  }
}

export function subscribeToEvents() {
  return subscribeSSE((event) => {
    if (pendingIds.has(event.id)) {
      pendingIds.delete(event.id);
      return;
    }
    appState.store.apply(event);
    syncDiagrams(event);
    appState.storeVersion++;
  });
}
