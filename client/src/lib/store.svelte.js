import { EventStore, genId } from './store.js';
import { fetchEvents, postEvent, subscribeSSE } from './api.js';

const pendingIds = new Set();

export const appState = $state({
  store: new EventStore(),
  storeVersion: 0,
  selectedIds: new Set(),
  syncError: false,
});

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
    appState.storeVersion++;
  });
}
