import { EventStore, genId } from './store.js';
import { fetchEvents, postEvent, subscribeSSE } from './api.js';
import { updateShapeStatus } from './diagram-sync.js';

const pendingIds = new Set();

export const appState = $state({
  store: new EventStore(),
  storeVersion: 0,
  selectedIds: new Set(),
  syncError: false,
});

/**
 * After any event is applied, sync diagram XML if needed.
 * Status changes update shape colors in all views' drawioXml.
 */
function syncDiagramsAfterEvent(event) {
  if (event.type === 'node.status') {
    const state = appState.store.getState();
    for (const view of state.views) {
      if (view.drawioXml) {
        const updated = updateShapeStatus(view.drawioXml, event.data.nodeId, event.data.status);
        if (updated !== view.drawioXml) {
          // Update the view's XML in the store directly (internal, no event needed)
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
  syncDiagramsAfterEvent(event);
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
    syncDiagramsAfterEvent(event);
    appState.storeVersion++;
  });
}
