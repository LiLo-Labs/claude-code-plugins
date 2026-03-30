import { EventStore } from './events.js';

export const appState = $state({
  store: new EventStore(),
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
});

export async function loadFromServer() {
  try {
    const res = await fetch('/api/events');
    const events = await res.json();
    appState.store = EventStore.fromEvents(events);
  } catch (err) {
    console.error('Failed to load events:', err);
  }
}

export async function emitEvent(event) {
  appState.store.apply(event);
  try {
    await fetch('/api/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(event),
    });
  } catch (err) {
    console.error('Failed to save event:', err);
  }
}
