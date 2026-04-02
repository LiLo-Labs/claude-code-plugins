export async function fetchEvents() {
  const res = await fetch('/api/events');
  return res.json();
}

export async function postEvent(event) {
  const res = await fetch('/api/events', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(event),
  });
  return res.json();
}

export async function postEventBatch(events) {
  const res = await fetch('/api/events/batch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(events),
  });
  return res.json();
}

export async function fetchState(level) {
  const url = level ? `/api/state?level=${level}` : '/api/state';
  const res = await fetch(url);
  return res.json();
}

export function subscribeSSE(onEvent) {
  const es = new EventSource('/api/events/stream');
  es.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data);
      if (event.type !== 'connected') onEvent(event);
    } catch {}
  };
  return es;
}
