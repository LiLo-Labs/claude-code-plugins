import { EventStore, genId } from './store.js';
import { fetchEvents, postEvent, subscribeSSE } from './api.js';
import { updateShapeStatus } from './diagram-sync.js';
import { generateViewXml } from './auto-layout.js';

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

/**
 * Sync diagrams after an event.
 * - Structural changes: full re-layout (auto-places new nodes)
 * - Status changes: update shape colors in-place (preserves layout)
 */
function syncDiagrams(event) {
  if (STRUCTURAL_EVENTS.has(event.type)) {
    // Full re-layout — new node or edge was added/removed
    const state = appState.store.getState();
    for (const view of state.views) {
      const xml = generateViewXml(view, state.nodes, state.edges);
      const v = appState.store._views.find(v => v.id === view.id);
      if (v) v.drawioXml = xml;
    }
  } else if (STYLE_EVENTS.has(event.type)) {
    // In-place color update — preserves user-arranged positions
    const state = appState.store.getState();
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
    const events = await fetchEvents();
    appState.store = EventStore.fromEvents(events);

    // Generate diagrams for all views on initial load
    const state = appState.store.getState();
    for (const view of state.views) {
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
