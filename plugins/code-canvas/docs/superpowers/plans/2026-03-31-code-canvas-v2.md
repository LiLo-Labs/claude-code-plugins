# Code Canvas v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean rebuild of code-canvas with maxGraph renderer, event-sourced state, and all v1 lessons baked in from line 1.

**Architecture:** Three layers — Svelte 5 client (maxGraph rendering), Node HTTP server (JSONL events + SSE), Claude hooks (unchanged). The EventStore is a shared pure-JS class used by both client and server.

**Tech Stack:** Svelte 5, @maxgraph/core, Vite, Node (zero deps), vitest

---

## File Structure

```
client/src/
  main.js                          — mount App
  App.svelte                       — shell layout, state wiring
  app.css                          — CSS custom properties (dark/light), base styles
  components/
    MaxGraphCanvas.svelte           — maxGraph renderer wrapper
    DetailPanel.svelte              — node detail on click (left side)
    ContextMenu.svelte              — right-click menu on shapes
    ViewTabs.svelte                 — tab bar with rename/delete/create
    CommentBar.svelte               — bottom comment strip
    CommentModal.svelte             — add comment dialog
  lib/
    store.js                        — pure EventStore class (shared with server)
    store.svelte.js                 — Svelte $state wrapper around EventStore
    api.js                          — fetch helpers + SSE subscription
    maxgraph.js                     — createGraph, loadXml, serializeXml, zoomToFit
    theme.js                        — getInitialTheme, setTheme, toggleTheme
    config.js                       — status colors, depth colors, constants

server/
  index.js                          — HTTP server, imports EventStore from client/src/lib/store.js

client/src/lib/store.test.js        — EventStore unit tests
server/index.test.js                — Server API tests
```

---

### Task 1: Clean up workspace — remove v1 client code and stale deps

**Files:**
- Delete: `client/src/App.svelte`, `client/src/app.css`, `client/src/main.js`
- Delete: `client/src/components/*.svelte`
- Delete: `client/src/lib/*.js`
- Modify: `client/package.json` — remove excalidraw/react deps

- [ ] **Step 1: Delete all client source files**

```bash
rm -rf client/src/components client/src/lib client/src/App.svelte client/src/app.css client/src/main.js
```

- [ ] **Step 2: Remove excalidraw and react deps from client/package.json**

Edit `client/package.json` — remove the `dependencies` block entirely (excalidraw, react, react-dom). The only dependency is `@maxgraph/core` which lives in the root `package.json`.

```json
{
  "name": "code-canvas-client",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "devDependencies": {
    "@sveltejs/vite-plugin-svelte": "^5.0.0",
    "svelte": "^5.0.0",
    "vite": "^6.0.0",
    "vitest": "^3.0.0"
  }
}
```

- [ ] **Step 3: Reinstall to clean lock file**

```bash
rm -rf node_modules client/node_modules package-lock.json && npm install
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "chore: remove v1 client code and stale deps for v2 rebuild"
```

---

### Task 2: EventStore — pure JS class with tests

**Files:**
- Create: `client/src/lib/store.js`
- Create: `client/src/lib/store.test.js`

- [ ] **Step 1: Write the EventStore tests**

```js
// client/src/lib/store.test.js
import { describe, it, expect } from 'vitest';
import { EventStore, genId } from './store.js';

describe('genId', () => {
  it('generates unique prefixed IDs', () => {
    const a = genId('ev');
    const b = genId('ev');
    expect(a).not.toBe(b);
    expect(a).toMatch(/^ev_/);
  });
});

describe('EventStore', () => {
  it('starts empty', () => {
    const store = new EventStore();
    const state = store.getState();
    expect(state.nodes.size).toBe(0);
    expect(state.edges.size).toBe(0);
    expect(state.comments).toEqual([]);
    expect(state.decisions).toEqual([]);
    expect(state.views).toEqual([]);
  });

  it('creates and updates nodes', () => {
    const store = new EventStore();
    store.apply({ type: 'node.created', data: { nodeId: 'n1', label: 'Auth', status: 'planned' } });
    expect(store.getState().nodes.get('n1').label).toBe('Auth');

    store.apply({ type: 'node.updated', data: { nodeId: 'n1', changes: { label: 'Auth v2' } } });
    expect(store.getState().nodes.get('n1').label).toBe('Auth v2');
  });

  it('deletes nodes and cleans orphaned edges', () => {
    const store = new EventStore();
    store.apply({ type: 'node.created', data: { nodeId: 'n1', label: 'A' } });
    store.apply({ type: 'node.created', data: { nodeId: 'n2', label: 'B' } });
    store.apply({ type: 'edge.created', data: { edgeId: 'e1', from: 'n1', to: 'n2' } });
    expect(store.getState().edges.size).toBe(1);

    store.apply({ type: 'node.deleted', data: { nodeId: 'n1' } });
    expect(store.getState().nodes.size).toBe(1);
    expect(store.getState().edges.size).toBe(0);
  });

  it('handles node.status events', () => {
    const store = new EventStore();
    store.apply({ type: 'node.created', data: { nodeId: 'n1', label: 'X', status: 'planned' } });
    store.apply({ type: 'node.status', data: { nodeId: 'n1', status: 'done' } });
    expect(store.getState().nodes.get('n1').status).toBe('done');
  });

  it('manages edges', () => {
    const store = new EventStore();
    store.apply({ type: 'node.created', data: { nodeId: 'n1', label: 'A' } });
    store.apply({ type: 'node.created', data: { nodeId: 'n2', label: 'B' } });
    store.apply({ type: 'edge.created', data: { edgeId: 'e1', from: 'n1', to: 'n2', label: 'uses' } });
    expect(store.getState().edges.get('e1').label).toBe('uses');

    store.apply({ type: 'edge.updated', data: { edgeId: 'e1', changes: { label: 'depends on' } } });
    expect(store.getState().edges.get('e1').label).toBe('depends on');

    store.apply({ type: 'edge.deleted', data: { edgeId: 'e1' } });
    expect(store.getState().edges.size).toBe(0);
  });

  it('manages comments lifecycle', () => {
    const store = new EventStore();
    store.apply({ type: 'comment.added', actor: 'user', data: { commentId: 'c1', target: 'n1', text: 'Fix this' } });
    expect(store.getUnresolvedComments()).toHaveLength(1);

    store.apply({ type: 'comment.resolved', actor: 'user', data: { commentId: 'c1' } });
    expect(store.getUnresolvedComments()).toHaveLength(0);
    expect(store.getState().comments[0].resolved).toBe(true);

    store.apply({ type: 'comment.reopened', data: { commentId: 'c1' } });
    expect(store.getUnresolvedComments()).toHaveLength(1);

    store.apply({ type: 'comment.deleted', data: { commentId: 'c1' } });
    expect(store.getState().comments).toHaveLength(0);
  });

  it('records decisions', () => {
    const store = new EventStore();
    store.apply({ type: 'node.created', data: { nodeId: 'n1', label: 'DB' } });
    store.apply({ type: 'decision.recorded', actor: 'claude', ts: '2026-01-01', data: { nodeId: 'n1', type: 'decision', chosen: 'Postgres', alternatives: ['MySQL', 'SQLite'], reason: 'Better JSON support' } });
    expect(store.getNodeDecisions('n1')).toHaveLength(1);
    expect(store.getNodeDecisions('n1')[0].chosen).toBe('Postgres');
  });

  it('manages views', () => {
    const store = new EventStore();
    store.apply({ type: 'view.created', data: { viewId: 'v1', name: 'Architecture', drawioXml: '<xml/>' } });
    expect(store.getState().views).toHaveLength(1);

    store.apply({ type: 'view.updated', data: { viewId: 'v1', changes: { name: 'Arch v2' } } });
    expect(store.getState().views[0].name).toBe('Arch v2');

    store.apply({ type: 'view.deleted', data: { viewId: 'v1' } });
    expect(store.getState().views).toHaveLength(0);
  });

  it('computes completeness from children', () => {
    const store = new EventStore();
    store.apply({ type: 'node.created', data: { nodeId: 'parent', label: 'System' } });
    store.apply({ type: 'node.created', data: { nodeId: 'c1', label: 'A', parent: 'parent', status: 'done' } });
    store.apply({ type: 'node.created', data: { nodeId: 'c2', label: 'B', parent: 'parent', status: 'planned' } });
    expect(store.getState().nodes.get('parent').completeness).toBe(0.5);
  });

  it('replays from event array', () => {
    const events = [
      { type: 'node.created', data: { nodeId: 'n1', label: 'Hello' } },
      { type: 'node.created', data: { nodeId: 'n2', label: 'World' } },
    ];
    const store = EventStore.fromEvents(events);
    expect(store.getState().nodes.size).toBe(2);
  });
});
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
npm test -- --workspace=client
```

Expected: FAIL — `store.js` doesn't exist yet.

- [ ] **Step 3: Write the EventStore implementation**

```js
// client/src/lib/store.js
let idCounter = 0;
export function genId(prefix = 'ev') {
  return `${prefix}_${Date.now()}_${++idCounter}`;
}

export class EventStore {
  constructor() {
    this.events = [];
    this._nodes = new Map();
    this._edges = new Map();
    this._comments = [];
    this._decisions = [];
    this._views = [];
  }

  static fromEvents(events) {
    const store = new EventStore();
    for (const event of events) store.apply(event);
    return store;
  }

  apply(event) {
    this.events.push(event);
    const d = event.data;
    switch (event.type) {
      case 'node.created':
        this._nodes.set(d.nodeId, {
          id: d.nodeId, label: d.label || '', subtitle: d.subtitle || '',
          parent: d.parent || null, status: d.status || 'planned',
          depth: d.depth || 'module', category: d.category || 'arch',
          confidence: d.confidence ?? 1, files: d.files || [],
          row: d.row ?? 0, col: d.col ?? 0, cols: d.cols ?? 3,
          color: d.color || null, textColor: d.textColor || null,
          hasWorkaround: false, completeness: 0,
        });
        this._recomputeCompleteness();
        break;
      case 'node.updated':
        if (this._nodes.has(d.nodeId)) {
          Object.assign(this._nodes.get(d.nodeId), d.changes);
          this._recomputeCompleteness();
        }
        break;
      case 'node.deleted':
        this._nodes.delete(d.nodeId);
        this._cleanOrphanedEdges();
        this._recomputeCompleteness();
        break;
      case 'node.status':
        if (this._nodes.has(d.nodeId)) {
          this._nodes.get(d.nodeId).status = d.status;
          this._recomputeCompleteness();
        }
        break;
      case 'edge.created':
        this._edges.set(d.edgeId, {
          id: d.edgeId, from: d.from, to: d.to,
          label: d.label || '', edgeType: d.edgeType || 'dependency',
          color: d.color || '#64748b',
        });
        break;
      case 'edge.updated':
        if (this._edges.has(d.edgeId)) Object.assign(this._edges.get(d.edgeId), d.changes);
        break;
      case 'edge.deleted':
        this._edges.delete(d.edgeId);
        break;
      case 'decision.recorded':
        this._decisions.push({
          nodeId: d.nodeId, type: d.type || 'decision', chosen: d.chosen,
          alternatives: d.alternatives || [], reason: d.reason || '',
          ts: event.ts, actor: event.actor,
        });
        if (d.type === 'workaround' && this._nodes.has(d.nodeId)) {
          this._nodes.get(d.nodeId).hasWorkaround = true;
        }
        break;
      case 'comment.added':
        this._comments.push({
          id: d.commentId, target: d.target, targetLabel: d.targetLabel || '',
          text: d.text, actor: d.actor || event.actor,
          resolved: false, resolvedAt: null, resolvedBy: null, ts: event.ts,
        });
        break;
      case 'comment.resolved': {
        const c = this._comments.find(c => c.id === d.commentId);
        if (c) { c.resolved = true; c.resolvedAt = event.ts; c.resolvedBy = d.actor || event.actor; }
        break;
      }
      case 'comment.reopened': {
        const c = this._comments.find(c => c.id === d.commentId);
        if (c) { c.resolved = false; c.resolvedAt = null; c.resolvedBy = null; }
        break;
      }
      case 'comment.deleted':
        this._comments = this._comments.filter(c => c.id !== d.commentId);
        break;
      case 'view.created':
        this._views.push({
          id: d.viewId, name: d.name, story: d.story || '',
          description: d.description || '', rendering: d.rendering || {},
          tabNodes: d.tabNodes || [], tabConnections: d.tabConnections || [],
          drawioXml: d.drawioXml || '', filter: d.filter || null,
        });
        break;
      case 'view.updated': {
        const v = this._views.find(v => v.id === d.viewId);
        if (v) Object.assign(v, d.changes);
        break;
      }
      case 'view.deleted':
        this._views = this._views.filter(v => v.id !== d.viewId);
        break;
    }
  }

  _cleanOrphanedEdges() {
    for (const [edgeId, edge] of this._edges) {
      if (!this._nodes.has(edge.from) || !this._nodes.has(edge.to)) this._edges.delete(edgeId);
    }
  }

  _recomputeCompleteness() {
    for (const [id, node] of this._nodes) {
      const children = [...this._nodes.values()].filter(n => n.parent === id);
      if (children.length === 0) {
        node.completeness = node.status === 'done' ? 1 : 0;
      } else {
        node.completeness = children.filter(c => c.status === 'done').length / children.length;
      }
    }
  }

  getAncestors(nodeId) {
    const result = [];
    let current = this._nodes.get(nodeId);
    while (current && current.parent) {
      const parent = this._nodes.get(current.parent);
      if (parent) result.unshift(parent);
      current = parent;
    }
    return result;
  }

  getState() {
    return {
      nodes: new Map(this._nodes), edges: new Map(this._edges),
      comments: [...this._comments], decisions: [...this._decisions],
      views: [...this._views], eventCount: this.events.length,
    };
  }

  getNodeDecisions(nodeId) { return this._decisions.filter(d => d.nodeId === nodeId); }

  getNodeHistory(nodeId) {
    return this.events.filter(e => {
      const d = e.data;
      return d.nodeId === nodeId || d.target === nodeId || d.from === nodeId || d.to === nodeId;
    });
  }

  getUnresolvedComments() { return this._comments.filter(c => !c.resolved); }
}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
npm test -- --workspace=client
```

Expected: All 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add client/src/lib/store.js client/src/lib/store.test.js
git commit -m "feat(v2): EventStore with full test coverage"
```

---

### Task 3: Server — rewrite with shared EventStore

**Files:**
- Create: `server/index.js` (overwrite)
- Create: `server/index.test.js` (overwrite)

- [ ] **Step 1: Write server tests**

```js
// server/index.test.js
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

let serverProcess;
let baseUrl;
let tmpDir;

function fetch(urlPath, options = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlPath, baseUrl);
    const req = http.request(url, {
      method: options.method || 'GET',
      headers: options.headers || {},
    }, (res) => {
      let body = '';
      res.on('data', c => body += c);
      res.on('end', () => {
        try { resolve({ status: res.statusCode, json: () => JSON.parse(body), text: () => body }); }
        catch { resolve({ status: res.statusCode, json: () => ({}), text: () => body }); }
      });
    });
    req.on('error', reject);
    if (options.body) req.write(options.body);
    req.end();
  });
}

describe('Server API', () => {
  beforeAll(async () => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'canvas-test-'));
    const { spawn } = await import('node:child_process');
    serverProcess = spawn('node', ['server/index.js', '--project-dir', tmpDir, '--port', '0'], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    // Wait for server to output its port
    baseUrl = await new Promise((resolve) => {
      serverProcess.stdout.on('data', (data) => {
        try {
          const info = JSON.parse(data.toString());
          if (info.url) resolve(info.url);
        } catch {}
      });
    });
  }, 10000);

  afterAll(() => {
    serverProcess?.kill('SIGINT');
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it('GET /api/health returns ok', async () => {
    const res = await fetch('/api/health');
    expect(res.status).toBe(200);
    const body = res.json();
    expect(body.status).toBe('ok');
  });

  it('GET /api/events returns empty array initially', async () => {
    const res = await fetch('/api/events');
    expect(res.json()).toEqual([]);
  });

  it('POST /api/events appends an event', async () => {
    const res = await fetch('/api/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'node.created', data: { nodeId: 'n1', label: 'Test' } }),
    });
    expect(res.json().saved).toBe(true);

    const events = (await fetch('/api/events')).json();
    expect(events).toHaveLength(1);
    expect(events[0].data.nodeId).toBe('n1');
  });

  it('POST /api/events/batch appends multiple', async () => {
    const res = await fetch('/api/events/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify([
        { type: 'node.created', data: { nodeId: 'n2', label: 'A' } },
        { type: 'node.created', data: { nodeId: 'n3', label: 'B' } },
      ]),
    });
    expect(res.json().appended).toBe(2);
  });

  it('GET /api/state returns computed state', async () => {
    const res = await fetch('/api/state');
    const body = res.json();
    expect(body.nodes.n1).toBeDefined();
    expect(body.nodes.n1.label).toBe('Test');
  });

  it('GET /api/state?level=L0 returns summary', async () => {
    const res = await fetch('/api/state?level=L0');
    const body = res.json();
    expect(body.summary).toContain('Nodes:');
  });

  it('PUT/GET /api/layouts/:viewId round-trips', async () => {
    await fetch('/api/layouts/test-view', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ positions: { n1: { x: 10, y: 20 } } }),
    });
    const res = await fetch('/api/layouts/test-view');
    expect(res.json().positions.n1.x).toBe(10);
  });
});
```

- [ ] **Step 2: Write the server**

```js
// server/index.js
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import { fileURLToPath } from 'node:url';
import { EventStore } from '../client/src/lib/store.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ── CLI Args ──
const args = process.argv.slice(2);
let projectDir = '.';
let requestedPort = 0;
const host = '127.0.0.1';

for (let i = 0; i < args.length; i++) {
  if (args[i] === '--project-dir' && args[i + 1]) projectDir = args[++i];
  else if (args[i] === '--port' && args[i + 1]) requestedPort = parseInt(args[++i], 10);
}

// ── Paths ──
const canvasDir = path.join(projectDir, '.code-canvas');
const eventsFile = path.join(canvasDir, 'events.jsonl');
const layoutsDir = path.join(canvasDir, 'layouts');
const serverInfoFile = path.join(canvasDir, '.server-info');
const clientDist = path.join(__dirname, '..', 'client', 'dist');

if (!fs.existsSync(canvasDir)) fs.mkdirSync(canvasDir, { recursive: true });
if (!fs.existsSync(layoutsDir)) fs.mkdirSync(layoutsDir, { recursive: true });
if (!fs.existsSync(eventsFile)) fs.writeFileSync(eventsFile, '');

// ── Port Discovery ──
async function findFreePort(start) {
  for (let p = start; p < start + 200; p++) {
    const ok = await new Promise(r => {
      const s = net.createServer();
      s.once('error', () => r(false));
      s.once('listening', () => { s.close(); r(true); });
      s.listen(p, host);
    });
    if (ok) return p;
  }
  return 0;
}

// ── Event I/O ──
function readEvents() {
  const content = fs.readFileSync(eventsFile, 'utf-8').trim();
  if (!content) return [];
  const events = [];
  for (const line of content.split('\n')) {
    if (!line.trim()) continue;
    try { events.push(JSON.parse(line)); } catch {}
  }
  return events;
}

let eventCount = readEvents().length;

function appendEvent(event) {
  fs.appendFileSync(eventsFile, JSON.stringify(event) + '\n');
  eventCount++;
}

// ── State formatting (for hooks) ──
function formatL0(state) {
  const nodes = [...state.nodes.values()];
  const sc = {};
  for (const n of nodes) sc[n.status] = (sc[n.status] || 0) + 1;
  const sp = Object.entries(sc).map(([s, c]) => `${c} ${s}`).join(', ');
  const uc = state.comments.filter(c => !c.resolved).length;
  return [
    `Nodes: ${nodes.length}${sp ? ` (${sp})` : ''}`,
    `Edges: ${state.edges.size} connections`,
    `Views: ${state.views.map(v => v.name).join(', ') || 'none'}`,
    `Comments: ${uc} unresolved`,
    `Decisions: ${state.decisions.length} recorded`,
    `Last activity: ${state.eventCount > 0 ? 'recent' : 'none'}`,
  ].join('\n');
}

function formatL1(state) {
  const lines = ['Nodes:'];
  for (const [id, n] of state.nodes) {
    const fp = n.files.length > 0 ? ` files: ${n.files.join(', ')}` : '';
    lines.push(`- ${id}: ${n.label} [${n.status}] (${n.depth})${fp}`);
  }
  if (state.edges.size > 0) {
    lines.push('', 'Edges:');
    for (const [, e] of state.edges) lines.push(`- ${e.from} -> ${e.to}: ${e.label}`);
  }
  if (state.views.length > 0) {
    lines.push('', 'Views:');
    for (const v of state.views) lines.push(`- ${v.name}: ${v.tabNodes.length} nodes`);
  }
  const ur = state.comments.filter(c => !c.resolved);
  if (ur.length > 0) {
    lines.push('', 'Unresolved comments:');
    for (const c of ur) lines.push(`- ${c.targetLabel || c.target}: "${c.text}" (${c.actor})`);
  }
  return lines.join('\n');
}

// ── HTTP Helpers ──
function sendJSON(res, data, status = 200) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

const MAX_BODY = 1024 * 1024;
function readBody(req) {
  return new Promise(resolve => {
    let body = '';
    req.on('data', chunk => {
      body += chunk;
      if (body.length > MAX_BODY) { req.destroy(); resolve(null); }
    });
    req.on('end', () => {
      try { resolve(JSON.parse(body)); } catch { resolve(null); }
    });
  });
}

const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.woff2': 'font/woff2', '.woff': 'font/woff',
};

function serveStatic(res, urlPath) {
  const safePath = urlPath === '/' ? '/index.html' : urlPath;
  const resolved = path.resolve(clientDist, '.' + safePath);
  if (!resolved.startsWith(path.resolve(clientDist))) {
    res.writeHead(403); res.end('Forbidden'); return true;
  }
  if (fs.existsSync(resolved) && fs.statSync(resolved).isFile()) {
    const ext = path.extname(resolved);
    res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
    fs.createReadStream(resolved).pipe(res);
    return true;
  }
  return false;
}

// ── SSE ──
const sseClients = new Set();

function broadcastEvent(event) {
  const data = JSON.stringify(event);
  for (const client of sseClients) {
    try { client.write(`data: ${data}\n\n`); } catch { sseClients.delete(client); }
  }
}

// ── Server ──
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${host}`);
  const p = url.pathname;

  // CORS for dev mode (Vite proxy)
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    });
    res.end(); return;
  }
  res.setHeader('Access-Control-Allow-Origin', '*');

  // SSE
  if (p === '/api/events/stream' && req.method === 'GET') {
    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    });
    res.write('data: {"type":"connected"}\n\n');
    sseClients.add(res);
    req.on('close', () => sseClients.delete(res));
    return;
  }

  // GET /api/events
  if (p === '/api/events' && req.method === 'GET') return sendJSON(res, readEvents());

  // POST /api/events
  if (p === '/api/events' && req.method === 'POST') {
    const body = await readBody(req);
    if (!body || !body.type) return sendJSON(res, { error: 'Missing event type' }, 400);
    body.ts = body.ts || new Date().toISOString();
    appendEvent(body);
    broadcastEvent(body);
    return sendJSON(res, { saved: true });
  }

  // POST /api/events/batch
  if (p === '/api/events/batch' && req.method === 'POST') {
    const body = await readBody(req);
    if (!Array.isArray(body)) return sendJSON(res, { error: 'Expected array' }, 400);
    for (const e of body) {
      if (!e || !e.type) return sendJSON(res, { error: 'Each event needs a type' }, 400);
    }
    const lines = body.map(e => { e.ts = e.ts || new Date().toISOString(); return JSON.stringify(e); }).join('\n') + '\n';
    fs.appendFileSync(eventsFile, lines);
    eventCount += body.length;
    for (const e of body) broadcastEvent(e);
    return sendJSON(res, { appended: body.length });
  }

  // GET /api/state
  if (p === '/api/state' && req.method === 'GET') {
    const store = EventStore.fromEvents(readEvents());
    const state = store.getState();
    const level = url.searchParams.get('level');
    if (level === 'L0') return sendJSON(res, { summary: formatL0(state) });
    if (level === 'L1') return sendJSON(res, { summary: formatL1(state) });
    return sendJSON(res, {
      nodes: Object.fromEntries(state.nodes),
      edges: Object.fromEntries(state.edges),
      comments: state.comments,
      decisions: state.decisions,
      views: state.views,
    });
  }

  // Layouts
  const layoutMatch = p.match(/^\/api\/layouts\/([a-zA-Z0-9_-]+)$/);
  if (layoutMatch && req.method === 'GET') {
    const file = path.resolve(layoutsDir, layoutMatch[1] + '.json');
    if (!file.startsWith(path.resolve(layoutsDir))) return sendJSON(res, { error: 'Invalid' }, 400);
    if (fs.existsSync(file)) return sendJSON(res, JSON.parse(fs.readFileSync(file, 'utf-8')));
    return sendJSON(res, {});
  }
  if (layoutMatch && req.method === 'PUT') {
    const file = path.resolve(layoutsDir, layoutMatch[1] + '.json');
    if (!file.startsWith(path.resolve(layoutsDir))) return sendJSON(res, { error: 'Invalid' }, 400);
    const body = await readBody(req);
    fs.writeFileSync(file, JSON.stringify(body, null, 2));
    return sendJSON(res, { saved: true });
  }

  // Health
  if (p === '/api/health' && req.method === 'GET') {
    return sendJSON(res, { status: 'ok', eventCount, project: path.basename(path.resolve(projectDir)) });
  }

  // Static files
  if (req.method === 'GET') {
    if (serveStatic(res, p)) return;
    if (serveStatic(res, '/')) return;
  }

  res.writeHead(404); res.end('Not found');
});

// ── Start ──
async function start() {
  const port = requestedPort || await findFreePort(9100);
  server.listen(port, host, () => {
    const addr = server.address();
    const info = {
      type: 'server-started', port: addr.port, host,
      url: `http://localhost:${addr.port}`,
      pid: process.pid,
      project: path.basename(path.resolve(projectDir)),
      startedAt: new Date().toISOString(),
    };
    fs.writeFileSync(serverInfoFile, JSON.stringify(info, null, 2));
    console.log(JSON.stringify(info));
  });
  process.stdin.resume();
  process.stdin.on('error', () => {});
}
start();

process.on('SIGINT', () => { try { fs.unlinkSync(serverInfoFile); } catch {} process.exit(0); });
process.on('SIGHUP', () => {});
process.on('SIGTERM', () => {});
process.on('uncaughtException', (err) => { console.error('Uncaught:', err.message); });
```

- [ ] **Step 3: Run tests — verify they pass**

```bash
npm test -- --workspace=server
```

Expected: All 7 tests pass.

- [ ] **Step 4: Commit**

```bash
git add server/index.js server/index.test.js
git commit -m "feat(v2): server with shared EventStore, SSE, layouts"
```

---

### Task 4: Client foundation — theme, config, API, Svelte state wrapper

**Files:**
- Create: `client/src/app.css`
- Create: `client/src/lib/theme.js`
- Create: `client/src/lib/config.js`
- Create: `client/src/lib/api.js`
- Create: `client/src/lib/store.svelte.js`
- Create: `client/src/main.js`

- [ ] **Step 1: Write app.css with CSS custom properties**

```css
/* client/src/app.css */
:root, [data-theme="dark"] {
  --bg: #0d1117; --bg-s: #161b22; --bg-e: #1c2128;
  --tx: #e6edf3; --tx-m: #8b949e; --tx-d: #484f58;
  --bdr: #30363d;
  --ac: #58a6ff; --gr: #3fb950; --or: #d29922; --rd: #f85149; --pu: #bc8cff; --yl: #d29922;
  --sh: rgba(0,0,0,.4);
  --gl: rgba(22,27,34,.85); --gl-b: rgba(48,54,61,.6);
  --graph-bg: #1a1a2e;
}
[data-theme="light"] {
  --bg: #ffffff; --bg-s: #f6f8fa; --bg-e: #eaeef2;
  --tx: #1f2328; --tx-m: #656d76; --tx-d: #8b949e;
  --bdr: #d0d7de;
  --ac: #0969da; --gr: #1a7f37; --or: #9a6700; --rd: #cf222e; --pu: #8250df; --yl: #9a6700;
  --sh: rgba(0,0,0,.1);
  --gl: rgba(246,248,250,.9); --gl-b: rgba(208,215,222,.6);
  --graph-bg: #ffffff;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html, body, #app { height: 100%; overflow: hidden; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: var(--bg); color: var(--tx); }
```

- [ ] **Step 2: Write theme.js (unchanged from v1)**

```js
// client/src/lib/theme.js
const STORAGE_KEY = 'code-canvas-theme';

export function getInitialTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {}
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  try { localStorage.setItem(STORAGE_KEY, theme); } catch {}
}

export function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  setTheme(next);
  return next;
}
```

- [ ] **Step 3: Write config.js (status colors + constants)**

```js
// client/src/lib/config.js
export const STATUS_COLORS = {
  done: '#10b981', 'in-progress': '#eab308', planned: '#3b82f6',
  blocked: '#f85149', cut: '#8b949e', placeholder: '#64748b',
};

export const DEPTH_COLORS = {
  system: '#5580a8', domain: '#7a5fa0', module: '#3d8a85', 'interface': '#a06830',
};

export function statusColor(status) { return STATUS_COLORS[status] || '#64748b'; }
export function depthColor(depth) { return DEPTH_COLORS[depth] || '#64748b'; }
```

- [ ] **Step 4: Write api.js (fetch + SSE)**

```js
// client/src/lib/api.js
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
```

- [ ] **Step 5: Write store.svelte.js (reactive wrapper)**

```js
// client/src/lib/store.svelte.js
import { EventStore } from './store.js';
import { fetchEvents, postEvent, subscribeSSE } from './api.js';

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
    appState.store.apply(event);
    appState.storeVersion++;
  });
}
```

- [ ] **Step 6: Write main.js**

```js
// client/src/main.js
import { mount } from 'svelte';
import App from './App.svelte';
import './app.css';

const app = mount(App, { target: document.getElementById('app') });
export default app;
```

- [ ] **Step 7: Commit**

```bash
git add client/src/app.css client/src/lib/theme.js client/src/lib/config.js client/src/lib/api.js client/src/lib/store.svelte.js client/src/main.js
git commit -m "feat(v2): client foundation — theme, config, API, state wrapper"
```

---

### Task 5: maxGraph wrapper — createGraph, loadXml, serializeXml

**Files:**
- Create: `client/src/lib/maxgraph.js`

- [ ] **Step 1: Write the maxGraph utility module**

```js
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
```

- [ ] **Step 2: Commit**

```bash
git add client/src/lib/maxgraph.js
git commit -m "feat(v2): maxGraph wrapper — create, load, serialize, zoom"
```

---

### Task 6: MaxGraphCanvas.svelte — the renderer component

**Files:**
- Create: `client/src/components/MaxGraphCanvas.svelte`

- [ ] **Step 1: Write the component**

```svelte
<!-- client/src/components/MaxGraphCanvas.svelte -->
<script>
  import { onMount, onDestroy } from 'svelte';
  import { createGraph, loadXml, serializeXml, zoomToFit } from '../lib/maxgraph.js';

  let { xml = '', dark = true, onchange, onselect, oncontextmenu: onctx } = $props();

  let containerEl = $state(null);
  let graph = null;
  let loadedXml = '';
  let saveTimer = null;

  onMount(async () => {
    const result = await createGraph(containerEl);
    graph = result.graph;

    containerEl.style.background = dark ? 'var(--graph-bg)' : 'var(--graph-bg)';

    // Debounced auto-save on changes
    const { InternalEvent } = await import('@maxgraph/core');

    graph.getDataModel().addListener(InternalEvent.CHANGE, () => {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        const xmlStr = serializeXml(graph);
        if (xmlStr && xmlStr !== loadedXml) {
          loadedXml = xmlStr;
          onchange?.(xmlStr);
        }
      }, 1000);
    });

    // Selection
    graph.getSelectionModel().addListener(InternalEvent.CHANGE, () => {
      const cells = graph.getSelectionCells();
      const ids = cells.filter(c => c.id && c.id !== '0' && c.id !== '1').map(c => c.id);
      onselect?.(ids);
    });

    // Right-click context menu on cells
    graph.addListener(InternalEvent.CLICK, (sender, evt) => {
      const cell = evt.getProperty('cell');
      if (cell && cell.id) onselect?.([cell.id]);
    });

    containerEl.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      const pt = graph.getPointForEvent(e);
      const cell = graph.getCellAt(e.offsetX, e.offsetY);
      if (cell && cell.id && cell.id !== '0' && cell.id !== '1') {
        onctx?.({ x: e.clientX, y: e.clientY, cellId: cell.id });
      }
    });

    if (xml) {
      loadXml(graph, xml);
      loadedXml = xml;
      zoomToFit(graph, containerEl);
    }
  });

  onDestroy(() => {
    clearTimeout(saveTimer);
    if (graph) { graph.destroy(); graph = null; }
  });

  // React to xml prop changes (tab switching)
  $effect(() => {
    const currentXml = xml;
    if (graph && currentXml !== loadedXml) {
      loadXml(graph, currentXml);
      loadedXml = currentXml;
      zoomToFit(graph, containerEl);
    }
  });

  // React to theme changes
  $effect(() => {
    if (containerEl) {
      containerEl.style.background = 'var(--graph-bg)';
    }
  });
</script>

<div class="graph-container" bind:this={containerEl}></div>

<style>
  .graph-container {
    width: 100%; height: 100%; min-height: 400px;
    overflow: hidden; position: relative; cursor: default;
  }
  .graph-container:focus { outline: none; }
</style>
```

- [ ] **Step 2: Commit**

```bash
git add client/src/components/MaxGraphCanvas.svelte
git commit -m "feat(v2): MaxGraphCanvas component with context menu support"
```

---

### Task 7: UI components — ViewTabs, DetailPanel, ContextMenu, CommentBar, CommentModal

**Files:**
- Create: `client/src/components/ViewTabs.svelte`
- Create: `client/src/components/DetailPanel.svelte`
- Create: `client/src/components/ContextMenu.svelte`
- Create: `client/src/components/CommentBar.svelte`
- Create: `client/src/components/CommentModal.svelte`

- [ ] **Step 1: Write ViewTabs.svelte**

```svelte
<!-- client/src/components/ViewTabs.svelte -->
<script>
  let { views = [], activeViewId = '', onswitch, oncreate, onrename, ondelete } = $props();
  let ctxMenu = $state({ visible: false, x: 0, y: 0, viewId: null, viewName: '' });

  function handleCtx(e, view) {
    e.preventDefault();
    ctxMenu = { visible: true, x: e.clientX, y: e.clientY, viewId: view.id, viewName: view.name };
  }
  function closeCtx() { ctxMenu.visible = false; }
  function handleRename() {
    const name = prompt('Rename tab:', ctxMenu.viewName);
    if (name && name !== ctxMenu.viewName) onrename?.(ctxMenu.viewId, name);
    closeCtx();
  }
  function handleDelete() {
    if (confirm(`Delete tab "${ctxMenu.viewName}"?`)) ondelete?.(ctxMenu.viewId);
    closeCtx();
  }
</script>

<svelte:window onclick={closeCtx} />

<div class="tab-bar">
  {#each views as view, i}
    <button
      class="tab-btn" class:active={activeViewId === view.id}
      onclick={() => onswitch?.(view.id)}
      oncontextmenu={(e) => handleCtx(e, view)}
    >{i + 1}. {view.name}</button>
  {/each}
  <button class="tab-btn add-tab" onclick={oncreate}>+</button>
</div>

{#if ctxMenu.visible}
  <div class="tab-ctx" style="left: {ctxMenu.x}px; top: {ctxMenu.y}px" onclick={(e) => e.stopPropagation()}>
    <div class="tab-ctx-item" onclick={handleRename}>Rename</div>
    <div class="tab-ctx-item delete" onclick={handleDelete}>Delete</div>
  </div>
{/if}

<style>
  .tab-bar { display: flex; gap: 2px; background: var(--bg-s); border-bottom: 1px solid var(--bdr); padding: 8px 12px 0; overflow-x: auto; flex-shrink: 0; }
  .tab-btn { padding: 8px 16px; border: 1px solid transparent; border-bottom: none; border-radius: 6px 6px 0 0; background: transparent; color: var(--tx-m); font-size: 13px; font-weight: 500; cursor: pointer; white-space: nowrap; transition: all 0.15s; }
  .tab-btn:hover { background: var(--bg-e); color: var(--tx); }
  .tab-btn.active { background: var(--bg); color: var(--ac); border-color: var(--bdr); font-weight: 600; }
  .add-tab { color: var(--tx-d); font-size: 16px; padding: 6px 14px; }
  .add-tab:hover { color: var(--ac); }
  .tab-ctx { position: fixed; z-index: 200; background: var(--bg-e); border: 1px solid var(--bdr); border-radius: 8px; padding: 4px 0; min-width: 140px; box-shadow: 0 8px 24px var(--sh); }
  .tab-ctx-item { padding: 6px 14px; font-size: 12px; color: var(--tx-m); cursor: pointer; transition: background 0.1s; }
  .tab-ctx-item:hover { background: rgba(59,130,246,.1); color: var(--tx); }
  .tab-ctx-item.delete:hover { background: rgba(239,68,68,.1); color: #ef4444; }
</style>
```

- [ ] **Step 2: Write ContextMenu.svelte**

```svelte
<!-- client/src/components/ContextMenu.svelte -->
<script>
  let { x = 0, y = 0, visible = false, nodeId = null, nodeLabel = '', onaction, onclose } = $props();
</script>

<svelte:window onclick={onclose} onkeydown={(e) => { if (e.key === 'Escape') onclose?.(); }} />

{#if visible}
  <div class="ctx" style="left: {x}px; top: {y}px" onclick={(e) => e.stopPropagation()}>
    <div class="ctx-header">{nodeLabel}</div>
    <div class="ctx-sep"></div>
    <div class="ctx-item" onclick={() => { onaction?.('comment'); onclose?.(); }}>Add Comment</div>
    <div class="ctx-item" onclick={() => { onaction?.('details'); onclose?.(); }}>View Details</div>
    <div class="ctx-sep"></div>
    <div class="ctx-sub">Change Status</div>
    <div class="ctx-item" onclick={() => { onaction?.('status-done'); onclose?.(); }}>
      <span class="dot" style="background: #10b981"></span> Done
    </div>
    <div class="ctx-item" onclick={() => { onaction?.('status-in-progress'); onclose?.(); }}>
      <span class="dot" style="background: #eab308"></span> In Progress
    </div>
    <div class="ctx-item" onclick={() => { onaction?.('status-planned'); onclose?.(); }}>
      <span class="dot" style="background: #3b82f6"></span> Planned
    </div>
    <div class="ctx-item" onclick={() => { onaction?.('status-blocked'); onclose?.(); }}>
      <span class="dot" style="background: #f85149"></span> Blocked
    </div>
  </div>
{/if}

<style>
  .ctx { position: fixed; z-index: 100; background: var(--bg-e); border: 1px solid var(--bdr); border-radius: 8px; padding: 4px 0; min-width: 180px; box-shadow: 0 8px 24px var(--sh); }
  .ctx-header { padding: 6px 14px; font-size: 12px; font-weight: 600; color: var(--tx); }
  .ctx-sub { padding: 6px 14px 2px; font-size: 10px; text-transform: uppercase; letter-spacing: .06em; color: var(--tx-d); }
  .ctx-item { padding: 6px 14px; font-size: 12px; color: var(--tx-m); cursor: pointer; display: flex; align-items: center; gap: 8px; transition: background 0.1s; }
  .ctx-item:hover { background: rgba(59,130,246,.1); color: var(--tx); }
  .ctx-sep { height: 1px; background: var(--bdr); margin: 3px 0; }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
</style>
```

- [ ] **Step 3: Write DetailPanel.svelte**

```svelte
<!-- client/src/components/DetailPanel.svelte -->
<script>
  import { statusColor } from '../lib/config.js';

  let { node = null, store, comments = [], onselect, onclose, onaddcomment, onresolve, ondelete } = $props();

  const ancestors = $derived(node ? store.getAncestors(node.id) : []);
  const decisions = $derived(node ? store.getNodeDecisions(node.id) : []);
  const nodeComments = $derived(node ? comments.filter(c => c.target === node.id) : []);
  const openComments = $derived(nodeComments.filter(c => !c.resolved));
  const resolvedComments = $derived(nodeComments.filter(c => c.resolved));
</script>

<div class="panel">
  <div class="hdr">
    <span class="title">{node?.label || 'Details'}</span>
    <button class="close" onclick={onclose}>&times;</button>
  </div>
  <div class="body">
    {#if node}
      {#if ancestors.length > 0}
        <div class="breadcrumb">
          {#each ancestors as anc}
            <span class="bc-item" onclick={() => onselect?.(anc.id)}>{anc.label}</span>
            <span class="bc-sep">&rsaquo;</span>
          {/each}
          <span class="bc-current">{node.label}</span>
        </div>
      {/if}

      <div class="section">
        <div class="sec-title">Properties</div>
        <div class="field"><span class="fl">Type</span><span class="fv">{node.depth}</span></div>
        <div class="field"><span class="fl">Category</span><span class="fv">{node.category}</span></div>
        <div class="field">
          <span class="fl">Status</span>
          <span class="fv" style="color: {statusColor(node.status)}">{node.status}</span>
        </div>
        <div class="field"><span class="fl">Completeness</span><span class="fv">{Math.round(node.completeness * 100)}%</span></div>
      </div>

      {#if node.subtitle}
        <div class="section">
          <div class="sec-title">Description</div>
          <p class="desc">{node.subtitle}</p>
        </div>
      {/if}

      {#if node.files?.length > 0}
        <div class="section">
          <div class="sec-title">Files</div>
          {#each node.files as pattern}
            <div class="file-pattern">{pattern}</div>
          {/each}
        </div>
      {/if}

      <div class="section">
        <div class="sec-title">
          Comments
          {#if openComments.length > 0}<span class="badge">{openComments.length}</span>{/if}
        </div>
        {#if openComments.length === 0 && resolvedComments.length === 0}
          <p class="empty-msg">No comments</p>
        {/if}
        {#each openComments as comment}
          <div class="comment-row">
            <span class="actor-dot" class:user={comment.actor === 'user'} class:claude={comment.actor === 'claude'}></span>
            <span class="comment-text">{comment.text}</span>
            <button class="act-btn resolve" onclick={() => onresolve?.(comment.id)}>&#10003;</button>
            <button class="act-btn del" onclick={() => ondelete?.(comment.id)}>&times;</button>
          </div>
        {/each}
        {#if resolvedComments.length > 0}
          <div class="resolved-label">Resolved ({resolvedComments.length})</div>
          {#each resolvedComments as comment}
            <div class="comment-row faded">
              <span class="actor-dot"></span>
              <span class="comment-text">{comment.text}</span>
            </div>
          {/each}
        {/if}
        <div class="add-comment" onclick={() => onaddcomment?.(node)}>+ Add Comment</div>
      </div>

      {#if decisions.length > 0}
        <div class="section">
          <div class="sec-title">Decisions</div>
          {#each decisions as dec}
            <div class="dec-card" class:wk={dec.type === 'workaround'}>
              <div class="dec-chosen" class:dec-wk={dec.type === 'workaround'}>
                {dec.type === 'workaround' ? '\u26A0' : '\u2713'} {dec.chosen}
              </div>
              <div class="dec-alts">
                {dec.type === 'workaround' ? 'Originally' : 'Alternatives'}: {dec.alternatives.join(', ')}
              </div>
              <div class="dec-reason">"{dec.reason}"</div>
            </div>
          {/each}
        </div>
      {/if}
    {:else}
      <p class="empty">Select a node to view details</p>
    {/if}
  </div>
</div>

<style>
  .panel { display: flex; flex-direction: column; height: 100%; }
  .hdr { padding: 12px 14px; border-bottom: 1px solid var(--bdr); display: flex; align-items: center; justify-content: space-between; }
  .title { font-size: 14px; font-weight: 600; }
  .close { border: none; background: transparent; color: var(--tx-d); font-size: 14px; cursor: pointer; border-radius: 3px; width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; }
  .close:hover { background: var(--bg-e); color: var(--tx); }
  .body { flex: 1; padding: 14px; overflow-y: auto; }
  .breadcrumb { display: flex; flex-wrap: wrap; gap: 3px; margin-bottom: 10px; font-size: 11px; }
  .bc-item { color: var(--tx-d); cursor: pointer; padding: 2px 5px; border-radius: 3px; }
  .bc-item:hover { background: var(--bg-e); color: var(--tx); }
  .bc-sep { color: var(--tx-d); padding: 0 2px; }
  .bc-current { color: var(--ac); font-weight: 600; padding: 2px 5px; }
  .section { margin-bottom: 16px; }
  .sec-title { font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--tx-d); margin-bottom: 6px; display: flex; align-items: center; gap: 6px; }
  .badge { font-size: 9px; background: var(--ac); color: white; padding: 0 5px; border-radius: 7px; font-weight: 600; }
  .field { display: flex; justify-content: space-between; padding: 3px 0; font-size: 12px; }
  .fl { color: var(--tx-m); }
  .fv { color: var(--tx); }
  .desc { font-size: 12px; color: var(--tx-m); line-height: 1.4; }
  .empty-msg { font-size: 11px; color: var(--tx-d); font-style: italic; }
  .comment-row { display: flex; align-items: center; gap: 6px; padding: 4px 0; border-bottom: 1px solid var(--bdr); font-size: 12px; }
  .comment-row.faded { opacity: 0.35; }
  .actor-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--tx-d); flex-shrink: 0; }
  .actor-dot.user { background: var(--gr); }
  .actor-dot.claude { background: var(--pu); }
  .comment-text { color: var(--tx-m); flex: 1; }
  .act-btn { background: none; border: none; font-size: 13px; padding: 0 2px; cursor: pointer; flex-shrink: 0; }
  .act-btn.resolve { color: var(--gr); }
  .act-btn.del { color: var(--tx-d); }
  .act-btn.del:hover { color: var(--rd); }
  .resolved-label { font-size: 10px; color: var(--tx-d); text-transform: uppercase; letter-spacing: 0.06em; padding: 6px 0 3px; }
  .add-comment { font-size: 11px; color: var(--ac); cursor: pointer; padding: 6px 0; text-align: center; border: 1px dashed var(--bdr); border-radius: 4px; margin-top: 4px; transition: .15s; }
  .add-comment:hover { border-color: var(--ac); background: rgba(59,130,246,.05); }
  .dec-card { background: var(--bg); border: 1px solid var(--bdr); border-radius: 6px; padding: 10px; margin-bottom: 8px; }
  .dec-card.wk { border-color: var(--or); }
  .dec-chosen { font-size: 12px; font-weight: 600; color: var(--gr); margin-bottom: 3px; }
  .dec-chosen.dec-wk { color: var(--or); }
  .dec-alts { font-size: 11px; color: var(--tx-d); margin-bottom: 3px; }
  .dec-reason { font-size: 11px; color: var(--tx-m); font-style: italic; }
  .empty { font-size: 12px; color: var(--tx-d); text-align: center; padding: 20px 0; }
  .file-pattern { font-size: 11px; font-family: monospace; color: var(--tx-m); padding: 2px 6px; background: var(--bg); border: 1px solid var(--bdr); border-radius: 3px; margin-bottom: 3px; }
</style>
```

- [ ] **Step 4: Write CommentBar.svelte**

```svelte
<!-- client/src/components/CommentBar.svelte -->
<script>
  let { comments = [], onresolve, ondelete, onnavigate } = $props();
  let expanded = $state(true);
  const unresolved = $derived(comments.filter(c => !c.resolved));
</script>

<div class="cbar" class:collapsed={!expanded}>
  <div class="cbar-hdr" onclick={() => expanded = !expanded}>
    <h3>Comments</h3>
    <span class="badge">{unresolved.length}</span>
    <span class="tog">{expanded ? '\u25BC' : '\u25B2'}</span>
  </div>
  {#if expanded}
    <div class="cbar-body">
      {#each unresolved as comment}
        <div class="row">
          <span class="dot" class:user={comment.actor === 'user'} class:claude={comment.actor === 'claude'}></span>
          <span class="tgt" onclick={() => onnavigate?.(comment.target)}>{comment.targetLabel}</span>
          <span class="txt">{comment.text}</span>
          <button class="res" onclick={() => onresolve?.(comment.id)}>&#10003;</button>
          <button class="del" onclick={() => ondelete?.(comment.id)}>&times;</button>
        </div>
      {/each}
      {#if unresolved.length === 0}
        <span class="empty">No open comments</span>
      {/if}
    </div>
  {/if}
</div>

<style>
  .cbar { background: var(--gl); backdrop-filter: blur(16px); border-top: 1px solid var(--gl-b); max-height: 140px; overflow-y: auto; flex-shrink: 0; }
  .cbar.collapsed { max-height: 30px; overflow: hidden; }
  .cbar-hdr { display: flex; align-items: center; padding: 5px 14px; cursor: pointer; gap: 6px; }
  .cbar-hdr h3 { font-size: 10px; text-transform: uppercase; letter-spacing: .08em; color: var(--tx-d); margin: 0; }
  .badge { font-size: 10px; background: var(--ac); color: white; padding: 0 5px; border-radius: 7px; font-weight: 600; }
  .tog { margin-left: auto; font-size: 10px; color: var(--tx-d); }
  .cbar-body { padding: 0 14px 6px; }
  .row { display: flex; align-items: center; gap: 6px; padding: 3px 0; border-bottom: 1px solid var(--bdr); font-size: 12px; }
  .row:last-child { border-bottom: none; }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--tx-d); flex-shrink: 0; }
  .dot.user { background: var(--gr); }
  .dot.claude { background: var(--pu); }
  .tgt { color: var(--ac); font-weight: 600; white-space: nowrap; cursor: pointer; }
  .tgt:hover { text-decoration: underline; }
  .txt { color: var(--tx-m); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .res, .del { background: none; border: none; font-size: 13px; padding: 0 2px; cursor: pointer; }
  .res { color: var(--gr); }
  .del { color: var(--tx-d); }
  .del:hover { color: var(--rd); }
  .empty { font-size: 11px; color: var(--tx-d); }
</style>
```

- [ ] **Step 5: Write CommentModal.svelte**

```svelte
<!-- client/src/components/CommentModal.svelte -->
<script>
  let { visible = false, node = null, onsave, onclose } = $props();
  let text = $state('');

  function handleSave() {
    if (!text.trim() || !node) return;
    onsave?.(node.id, node.label, text.trim());
    text = '';
    onclose?.();
  }
</script>

{#if visible && node}
  <div class="overlay" onclick={onclose}>
    <div class="modal" onclick={(e) => e.stopPropagation()}>
      <h3>{node.label}</h3>
      <p class="sub">{node.subtitle}</p>
      <textarea bind:value={text} placeholder="What would you change about this component?" rows="3"></textarea>
      <div class="actions">
        <button class="cancel" onclick={onclose}>Cancel</button>
        <button class="save" onclick={handleSave}>Save Comment</button>
      </div>
    </div>
  </div>
{/if}

<svelte:window onkeydown={(e) => {
  if (e.key === 'Escape' && visible) onclose?.();
  if (e.key === 'Enter' && !e.shiftKey && visible) { e.preventDefault(); handleSave(); }
}} />

<style>
  .overlay { position: fixed; inset: 0; background: rgba(0,0,0,.6); display: flex; align-items: center; justify-content: center; z-index: 200; }
  .modal { background: var(--bg-e); border: 1px solid var(--bdr); border-radius: 10px; padding: 20px; width: 400px; box-shadow: 0 12px 40px var(--sh); }
  h3 { font-size: 14px; color: var(--tx); margin-bottom: 4px; }
  .sub { font-size: 12px; color: var(--tx-d); margin-bottom: 12px; }
  textarea { width: 100%; background: var(--bg); border: 1px solid var(--bdr); border-radius: 6px; color: var(--tx); padding: 8px; font-family: inherit; font-size: 13px; resize: vertical; }
  textarea:focus { outline: none; border-color: var(--ac); }
  .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
  .cancel { padding: 6px 16px; border-radius: 6px; border: none; background: var(--bdr); color: var(--tx-m); font-size: 13px; cursor: pointer; }
  .save { padding: 6px 16px; border-radius: 6px; border: none; background: var(--ac); color: white; font-size: 13px; cursor: pointer; }
  .save:hover { opacity: .9; }
</style>
```

- [ ] **Step 6: Commit**

```bash
git add client/src/components/
git commit -m "feat(v2): all UI components — tabs, detail panel, context menu, comments"
```

---

### Task 8: App.svelte — wire everything together

**Files:**
- Create: `client/src/App.svelte`

- [ ] **Step 1: Write App.svelte**

```svelte
<!-- client/src/App.svelte -->
<script>
  import './app.css';
  import { onMount } from 'svelte';
  import { getInitialTheme, setTheme, toggleTheme } from './lib/theme.js';
  import { appState, loadFromServer, emitEvent, subscribeToEvents } from './lib/store.svelte.js';
  import { genId } from './lib/store.js';
  import ViewTabs from './components/ViewTabs.svelte';
  import MaxGraphCanvas from './components/MaxGraphCanvas.svelte';
  import DetailPanel from './components/DetailPanel.svelte';
  import ContextMenu from './components/ContextMenu.svelte';
  import CommentBar from './components/CommentBar.svelte';
  import CommentModal from './components/CommentModal.svelte';

  let theme = $state('dark');
  let activeTabIdx = $state(0);
  let ctxMenu = $state({ visible: false, x: 0, y: 0, nodeId: null });
  let commentModal = $state({ visible: false, node: null });

  onMount(async () => {
    theme = getInitialTheme();
    setTheme(theme);
    await loadFromServer();
    subscribeToEvents();
  });

  function getGraphState() {
    const _v = appState.storeVersion;
    return appState.store.getState();
  }

  const graphState = $derived(getGraphState());
  const tabs = $derived(graphState.views);
  const activeTab = $derived(tabs[activeTabIdx] || tabs[0] || null);
  const selectedNode = $derived(
    appState.selectedIds.size === 1
      ? graphState.nodes.get([...appState.selectedIds][0]) || null
      : null
  );

  function selectNode(nodeId) { appState.selectedIds = new Set([nodeId]); }

  function handleContextMenu({ x, y, cellId }) {
    const node = graphState.nodes.get(cellId);
    if (node) {
      ctxMenu = { visible: true, x, y, nodeId: cellId };
    }
  }

  function handleContextAction(action) {
    const nodeId = ctxMenu.nodeId;
    if (!nodeId) return;
    if (action === 'details') {
      selectNode(nodeId);
    } else if (action === 'comment') {
      const node = graphState.nodes.get(nodeId);
      if (node) commentModal = { visible: true, node };
    } else if (action.startsWith('status-')) {
      const status = action.replace('status-', '');
      emitEvent({ id: genId(), type: 'node.status', actor: 'user', data: { nodeId, status } });
    }
  }

  function handleSaveComment(nodeId, label, text) {
    emitEvent({ id: genId(), type: 'comment.added', actor: 'user', data: { commentId: genId('c'), target: nodeId, targetLabel: label, text, actor: 'user' } });
  }

  function handleResolveComment(commentId) {
    emitEvent({ id: genId(), type: 'comment.resolved', actor: 'user', data: { commentId, actor: 'user' } });
  }

  function handleDeleteComment(commentId) {
    emitEvent({ id: genId(), type: 'comment.deleted', actor: 'user', data: { commentId } });
  }

  function handleToggleTheme() { theme = toggleTheme(); }
</script>

<div class="layout">
  <header class="topbar">
    <div class="tp"><span class="dot"></span> {activeTab?.name || 'Code Canvas'}</div>
    <div class="tp-story">{activeTab?.description || ''}</div>
    <div class="tr">
      <button class="tb" onclick={handleToggleTheme}>{theme === 'dark' ? '\u2606' : '\u263E'}</button>
    </div>
  </header>

  <div class="main">
    {#if selectedNode}
      <aside class="panel-left">
        <DetailPanel
          node={selectedNode}
          store={appState.store}
          comments={graphState.comments}
          onselect={selectNode}
          onclose={() => { appState.selectedIds = new Set(); }}
          onaddcomment={(node) => { commentModal = { visible: true, node }; }}
          onresolve={handleResolveComment}
          ondelete={handleDeleteComment}
        />
      </aside>
    {/if}

    <div class="canvas-col">
      <ViewTabs
        views={tabs}
        activeViewId={activeTab?.id || ''}
        oncreate={() => {
          const name = prompt('Tab name:');
          if (!name) return;
          const viewId = 'tab-' + Date.now();
          emitEvent({ id: genId(), type: 'view.created', actor: 'user', data: { viewId, name, drawioXml: '' } });
          setTimeout(() => { const i = graphState.views.findIndex(v => v.id === viewId); if (i >= 0) activeTabIdx = i; }, 100);
        }}
        onswitch={(id) => { activeTabIdx = tabs.findIndex(t => t.id === id); if (activeTabIdx < 0) activeTabIdx = 0; }}
        onrename={(viewId, name) => { emitEvent({ id: genId(), type: 'view.updated', actor: 'user', data: { viewId, changes: { name } } }); }}
        ondelete={(viewId) => { emitEvent({ id: genId(), type: 'view.deleted', actor: 'user', data: { viewId } }); if (activeTab?.id === viewId) activeTabIdx = 0; }}
      />
      <MaxGraphCanvas
        xml={activeTab?.drawioXml || ''}
        dark={theme === 'dark'}
        onchange={(xml) => { if (activeTab) emitEvent({ id: genId(), type: 'view.updated', actor: 'user', data: { viewId: activeTab.id, changes: { drawioXml: xml } } }); }}
        onselect={(ids) => {
          if (ids.length >= 1 && graphState.nodes.has(ids[0])) selectNode(ids[0]);
          else if (ids.length === 0) appState.selectedIds = new Set();
        }}
        oncontextmenu={handleContextMenu}
      />
    </div>
  </div>

  <CommentBar
    comments={graphState.comments}
    onresolve={handleResolveComment}
    ondelete={handleDeleteComment}
    onnavigate={(nodeId) => { selectNode(nodeId); }}
  />

  <ContextMenu
    visible={ctxMenu.visible}
    x={ctxMenu.x} y={ctxMenu.y}
    nodeId={ctxMenu.nodeId}
    nodeLabel={ctxMenu.nodeId ? graphState.nodes.get(ctxMenu.nodeId)?.label || '' : ''}
    onaction={handleContextAction}
    onclose={() => { ctxMenu.visible = false; }}
  />

  <CommentModal
    visible={commentModal.visible}
    node={commentModal.node}
    onsave={handleSaveComment}
    onclose={() => commentModal = { ...commentModal, visible: false }}
  />

  <footer class="sl">
    {#if appState.syncError}
      <span class="err">&#9888; Sync failed</span>
    {:else}
      <span class="ok">&#9679; Synced</span>
    {/if}
    <span class="inf">{graphState.nodes.size} nodes</span>
    <span class="inf">{tabs.length} tabs</span>
    <span class="inf">{graphState.eventCount} events</span>
  </footer>
</div>

<style>
  .layout { display: flex; flex-direction: column; height: 100vh; }
  .topbar { display: flex; align-items: center; height: 44px; background: var(--bg-s); border-bottom: 1px solid var(--bdr); padding: 0 16px; flex-shrink: 0; gap: 10px; }
  .tp { font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 6px; }
  .tp-story { font-size: 11px; color: var(--tx-d); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--yl); }
  .tr { margin-left: auto; display: flex; gap: 4px; align-items: center; }
  .tb { height: 32px; padding: 0 10px; border: 1px solid var(--bdr); border-radius: 4px; background: transparent; color: var(--tx-m); font-size: 12px; transition: .15s; cursor: pointer; }
  .tb:hover { border-color: var(--ac); color: var(--ac); }
  .main { flex: 1; display: flex; min-height: 0; overflow: hidden; }
  .panel-left { width: 280px; background: var(--bg-s); border-right: 1px solid var(--bdr); flex-shrink: 0; overflow-y: auto; z-index: 10; }
  .canvas-col { flex: 1; display: flex; flex-direction: column; min-height: 0; min-width: 0; }
  .sl { height: 22px; background: var(--bg-s); border-top: 1px solid var(--bdr); display: flex; align-items: center; padding: 0 14px; gap: 14px; font-size: 10px; flex-shrink: 0; }
  .ok { color: var(--gr); }
  .err { color: var(--or); }
  .inf { color: var(--tx-d); }
</style>
```

- [ ] **Step 2: Build and verify**

```bash
cd client && npm run build && cd ..
```

Expected: Build succeeds with no errors.

- [ ] **Step 3: Commit**

```bash
git add client/src/App.svelte
git commit -m "feat(v2): App shell — wires all components together"
```

---

### Task 9: Smoke test — boot server, open browser, verify end-to-end

- [ ] **Step 1: Build client**

```bash
cd client && npm run build && cd ..
```

- [ ] **Step 2: Start server**

```bash
nohup node server/index.js --project-dir . </dev/null &
```

- [ ] **Step 3: Open in browser and verify**

Navigate to the URL from `.code-canvas/.server-info`. Verify:
- Page loads with dark theme
- Tab bar shows existing views (if any events exist)
- Theme toggle works
- Status bar shows node/tab/event counts
- If views have drawioXml, maxGraph renders them

- [ ] **Step 4: Run full test suite**

```bash
npm test
```

Expected: All EventStore tests and server tests pass.

- [ ] **Step 5: Commit any fixes**

```bash
git add -A && git commit -m "fix(v2): smoke test fixes"
```

---

### Task 10: Delete stale v1 docs

**Files:**
- Delete: `docs/architecture-diagnosis.md`
- Delete: `docs/ux-gaps-v2.md`
- Delete: `docs/review-findings.md`
- Delete: `excalidraw.log`

- [ ] **Step 1: Remove stale files**

```bash
rm -f docs/architecture-diagnosis.md docs/ux-gaps-v2.md docs/review-findings.md excalidraw.log
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "chore: remove stale v1 analysis docs"
```
