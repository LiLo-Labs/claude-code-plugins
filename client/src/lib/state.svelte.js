import { EventStore } from './events.js';

export const appState = $state({
  store: new EventStore(),
  storeVersion: 0,  // bumped on every event to trigger Svelte re-derivation
  selectedIds: new Set(),
  activeView: 'all',
  activePanel: 'details',
  activeViewMode: 'canvas',
  zoom: 1,
  panX: 0,
  panY: 0,
  theme: 'dark',
  searchQuery: '',
  sidebarOpen: true,
  panelOpen: true,
  commentsOpen: true,
  syncError: false,
});

export async function loadFromServer() {
  try {
    const res = await fetch('/api/events');
    const events = await res.json();
    appState.store = EventStore.fromEvents(events);
    appState.storeVersion++;
    appState.syncError = false;
  } catch (err) {
    console.error('Failed to load events:', err);
    appState.syncError = true;
  }
}

export async function emitEvent(event) {
  appState.store.apply(event);
  appState.storeVersion++;  // trigger reactivity
  try {
    await fetch('/api/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(event),
    });
    appState.syncError = false;
  } catch (err) {
    console.error('Failed to save event:', err);
    appState.syncError = true;
  }
}

/**
 * Subscribe to real-time events via SSE.
 * Applies incoming events to the local store so the UI updates live.
 */
export function subscribeToEvents() {
  const es = new EventSource('/api/events/stream');
  es.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data);
      if (event.type === 'connected') return;
      // Apply to local store (will be a no-op if we posted it ourselves)
      appState.store.apply(event);
      appState.storeVersion++;
    } catch {}
  };
  es.onerror = () => {
    // Reconnects automatically
  };
  return es;
}
