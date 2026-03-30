# Code Canvas Plugin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code plugin that provides an interactive visual design knowledge graph served via a local Svelte app, backed by a JSONL event store, with lifecycle hooks for autonomous updates.

**Architecture:** Event-sourced JSONL log → in-memory graph engine → Svelte+SVG frontend served by Node.js. The plugin integrates via hooks (SessionStart, PostToolUse, etc.) and a `/canvas` skill. Each project gets its own server instance on an auto-discovered port.

**Tech Stack:** Svelte 5 + Vite (client), Node.js (server), JSONL (event store), SVG (canvas rendering)

**Spec:** `docs/design-spec.md`

---

## Phase 1: Foundation (Event Store + Server + Client Shell)

### Task 1: Project Scaffolding

**Files:**
- Create: `package.json` (root workspace)
- Create: `.claude-plugin/plugin.json`
- Create: `client/package.json`
- Create: `client/vite.config.js`
- Create: `client/src/main.js`
- Create: `client/index.html`
- Create: `server/package.json`
- Create: `.gitignore`

- [ ] **Step 1: Initialize root workspace**

```json
// package.json
{
  "name": "code-canvas-plugin",
  "private": true,
  "workspaces": ["client", "server"],
  "scripts": {
    "dev": "npm run dev --workspace=client",
    "build": "npm run build --workspace=client",
    "server": "node server/index.js",
    "start": "npm run build && npm run server"
  }
}
```

- [ ] **Step 2: Create plugin manifest**

```json
// .claude-plugin/plugin.json
{
  "name": "code-canvas",
  "description": "Interactive visual design knowledge graph for software architecture. Generates canvases from specs, tracks decisions, captures comments, and keeps Claude informed of architectural state.",
  "version": "0.1.0",
  "author": {
    "name": "lilolabs",
    "email": "mark@lilolabs.com"
  },
  "license": "MIT",
  "keywords": ["architecture", "canvas", "design", "knowledge-graph", "visual"]
}
```

- [ ] **Step 3: Scaffold Svelte client**

```json
// client/package.json
{
  "name": "code-canvas-client",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "devDependencies": {
    "@sveltejs/vite-plugin-svelte": "^4.0.0",
    "svelte": "^5.0.0",
    "vite": "^6.0.0"
  }
}
```

```javascript
// client/vite.config.js
import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:9100',
    },
  },
});
```

```html
<!-- client/index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Code Canvas</title>
</head>
<body>
  <div id="app"></div>
  <script type="module" src="/src/main.js"></script>
</body>
</html>
```

```javascript
// client/src/main.js
import App from './App.svelte';
import { mount } from 'svelte';

const app = mount(App, { target: document.getElementById('app') });
export default app;
```

- [ ] **Step 4: Create .gitignore**

```
node_modules/
client/dist/
.code-canvas/
*.log
.DS_Store
```

- [ ] **Step 5: Install dependencies and verify build**

Run: `cd /Users/mark/Developer/code-canvas-plugin && npm install --workspaces`
Run: `cd /Users/mark/Developer/code-canvas-plugin/client && npx vite build`
Expected: Build succeeds (may warn about missing App.svelte — that's Task 2)

- [ ] **Step 6: Initialize git repo and commit**

```bash
cd /Users/mark/Developer/code-canvas-plugin
git init
git add package.json .claude-plugin/ client/package.json client/vite.config.js client/index.html client/src/main.js .gitignore
git commit -m "feat: scaffold project structure — root workspace, Svelte client, plugin manifest"
```

---

### Task 2: Event Store Library

**Files:**
- Create: `client/src/lib/events.js`
- Create: `client/src/lib/events.test.js`

This is the core data layer. All state derives from events. The client fetches events from the server API and computes state in-memory.

- [ ] **Step 1: Write tests for event store**

```javascript
// client/src/lib/events.test.js
import { describe, it, expect } from 'vitest';
import { EventStore } from './events.js';

describe('EventStore', () => {
  it('replays node.created events into nodes map', () => {
    const store = new EventStore();
    store.apply({
      id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'node.created', actor: 'claude',
      data: { nodeId: 'n1', label: 'Server', subtitle: 'API layer', parent: null, depth: 'system', category: 'arch', confidence: 3 }
    });
    const state = store.getState();
    expect(state.nodes.get('n1')).toEqual(expect.objectContaining({ id: 'n1', label: 'Server', status: 'planned' }));
  });

  it('applies node.status events', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n1', label: 'Server', subtitle: '', parent: null, depth: 'system', category: 'arch', confidence: 3 } });
    store.apply({ id: 'ev_2', ts: '2026-03-29T00:01:00Z', type: 'node.status', actor: 'user', data: { nodeId: 'n1', status: 'done', prev: 'planned' } });
    expect(store.getState().nodes.get('n1').status).toBe('done');
  });

  it('tracks edges', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'edge.created', actor: 'claude', data: { edgeId: 'e1', from: 'n1', to: 'n2', label: 'calls', edgeType: 'data-flow', color: '#3b82f6' } });
    expect(store.getState().edges.get('e1')).toEqual(expect.objectContaining({ from: 'n1', to: 'n2' }));
  });

  it('tracks decisions with workaround detection', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n1', label: 'Auth', subtitle: '', parent: null, depth: 'domain', category: 'arch', confidence: 2 } });
    store.apply({ id: 'ev_2', ts: '2026-03-29T00:01:00Z', type: 'decision.recorded', actor: 'claude', data: { nodeId: 'n1', type: 'workaround', chosen: 'Skip auth', alternatives: ['JWT'], reason: 'v1 only' } });
    const node = store.getState().nodes.get('n1');
    expect(node.hasWorkaround).toBe(true);
    expect(store.getState().decisions).toHaveLength(1);
  });

  it('tracks comments with resolution', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'comment.added', actor: 'user', data: { commentId: 'c1', target: 'n1', targetLabel: 'Auth', text: 'Need JWT', actor: 'user' } });
    expect(store.getState().comments).toHaveLength(1);
    expect(store.getState().comments[0].resolved).toBe(false);

    store.apply({ id: 'ev_2', ts: '2026-03-29T00:01:00Z', type: 'comment.resolved', actor: 'claude', data: { commentId: 'c1', actor: 'claude' } });
    expect(store.getState().comments[0].resolved).toBe(true);
  });

  it('computes completeness from children statuses', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'p', label: 'Parent', subtitle: '', parent: null, depth: 'system', category: 'arch', confidence: 2 } });
    store.apply({ id: 'ev_2', ts: '2026-03-29T00:00:01Z', type: 'node.created', actor: 'claude', data: { nodeId: 'c1', label: 'Child 1', subtitle: '', parent: 'p', depth: 'domain', category: 'arch', confidence: 3 } });
    store.apply({ id: 'ev_3', ts: '2026-03-29T00:00:02Z', type: 'node.created', actor: 'claude', data: { nodeId: 'c2', label: 'Child 2', subtitle: '', parent: 'p', depth: 'domain', category: 'arch', confidence: 3 } });
    store.apply({ id: 'ev_4', ts: '2026-03-29T00:00:03Z', type: 'node.status', actor: 'user', data: { nodeId: 'c1', status: 'done', prev: 'planned' } });
    expect(store.getState().nodes.get('p').completeness).toBe(0.5);
  });

  it('supports views', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'view.created', actor: 'user', data: { viewId: 'v1', name: 'Architecture', filter: { categories: ['arch'] }, description: '' } });
    expect(store.getState().views).toHaveLength(1);
    expect(store.getState().views[0].name).toBe('Architecture');
  });

  it('loads from array of events', () => {
    const events = [
      { id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n1', label: 'A', subtitle: '', parent: null, depth: 'system', category: 'arch', confidence: 2 } },
      { id: 'ev_2', ts: '2026-03-29T00:00:01Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n2', label: 'B', subtitle: '', parent: 'n1', depth: 'domain', category: 'arch', confidence: 1 } },
    ];
    const store = EventStore.fromEvents(events);
    expect(store.getState().nodes.size).toBe(2);
  });
});
```

- [ ] **Step 2: Add vitest to client and verify tests fail**

```json
// Add to client/package.json devDependencies:
"vitest": "^2.0.0"
// Add to scripts:
"test": "vitest run",
"test:watch": "vitest"
```

Run: `cd /Users/mark/Developer/code-canvas-plugin/client && npm install && npx vitest run`
Expected: FAIL — events.js doesn't exist yet

- [ ] **Step 3: Implement EventStore**

```javascript
// client/src/lib/events.js

/**
 * Event store — replays JSONL events into derived graph state.
 * All canvas state is computed from this. Never mutate state directly.
 */

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
    for (const event of events) {
      store.apply(event);
    }
    return store;
  }

  apply(event) {
    this.events.push(event);
    const d = event.data;

    switch (event.type) {
      case 'node.created':
        this._nodes.set(d.nodeId, {
          id: d.nodeId,
          label: d.label,
          subtitle: d.subtitle || '',
          parent: d.parent || null,
          status: 'planned',
          depth: d.depth || 'module',
          category: d.category || 'arch',
          confidence: d.confidence ?? 1,
          hasWorkaround: false,
          completeness: 0,
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
          id: d.edgeId,
          from: d.from,
          to: d.to,
          label: d.label || '',
          edgeType: d.edgeType || 'dependency',
          color: d.color || '#64748b',
        });
        break;

      case 'edge.updated':
        if (this._edges.has(d.edgeId)) {
          Object.assign(this._edges.get(d.edgeId), d.changes);
        }
        break;

      case 'edge.deleted':
        this._edges.delete(d.edgeId);
        break;

      case 'decision.recorded':
        this._decisions.push({
          nodeId: d.nodeId,
          type: d.type,
          chosen: d.chosen,
          alternatives: d.alternatives || [],
          reason: d.reason || '',
          ts: event.ts,
          actor: event.actor,
        });
        if (d.type === 'workaround' && this._nodes.has(d.nodeId)) {
          this._nodes.get(d.nodeId).hasWorkaround = true;
        }
        break;

      case 'comment.added':
        this._comments.push({
          id: d.commentId,
          target: d.target,
          targetLabel: d.targetLabel || '',
          text: d.text,
          actor: d.actor || event.actor,
          resolved: false,
          resolvedAt: null,
          resolvedBy: null,
          ts: event.ts,
        });
        break;

      case 'comment.resolved': {
        const comment = this._comments.find(c => c.id === d.commentId);
        if (comment) {
          comment.resolved = true;
          comment.resolvedAt = event.ts;
          comment.resolvedBy = d.actor || event.actor;
        }
        break;
      }

      case 'comment.reopened': {
        const comment = this._comments.find(c => c.id === d.commentId);
        if (comment) {
          comment.resolved = false;
          comment.resolvedAt = null;
          comment.resolvedBy = null;
        }
        break;
      }

      case 'comment.deleted':
        this._comments = this._comments.filter(c => c.id !== d.commentId);
        break;

      case 'view.created':
        this._views.push({
          id: d.viewId,
          name: d.name,
          description: d.description || '',
          filter: d.filter || {},
        });
        break;

      case 'view.updated':
        const view = this._views.find(v => v.id === d.viewId);
        if (view) Object.assign(view, d.changes);
        break;

      case 'layout.saved':
        // Layouts are persisted separately, not in derived state
        break;
    }
  }

  _recomputeCompleteness() {
    for (const [id, node] of this._nodes) {
      const children = [...this._nodes.values()].filter(n => n.parent === id);
      if (children.length === 0) {
        node.completeness = node.status === 'done' ? 1 : 0;
      } else {
        const done = children.filter(c => c.status === 'done').length;
        node.completeness = done / children.length;
      }
    }
  }

  getState() {
    return {
      nodes: new Map(this._nodes),
      edges: new Map(this._edges),
      comments: [...this._comments],
      decisions: [...this._decisions],
      views: [...this._views],
      eventCount: this.events.length,
    };
  }

  getNodeDecisions(nodeId) {
    return this._decisions.filter(d => d.nodeId === nodeId);
  }

  getNodeHistory(nodeId) {
    return this.events.filter(e => {
      const d = e.data;
      return d.nodeId === nodeId || d.target === nodeId || d.from === nodeId || d.to === nodeId;
    });
  }

  getUnresolvedComments() {
    return this._comments.filter(c => !c.resolved);
  }
}
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `cd /Users/mark/Developer/code-canvas-plugin/client && npx vitest run`
Expected: All 8 tests pass

- [ ] **Step 5: Commit**

```bash
git add client/src/lib/events.js client/src/lib/events.test.js client/package.json
git commit -m "feat: implement event store with replay, comments, decisions, views"
```

---

### Task 3: Server — Event API + Static Files

**Files:**
- Create: `server/package.json`
- Create: `server/index.js`

- [ ] **Step 1: Create server package.json**

```json
// server/package.json
{
  "name": "code-canvas-server",
  "private": true,
  "type": "module",
  "main": "index.js"
}
```

- [ ] **Step 2: Implement server**

```javascript
// server/index.js
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import { fileURLToPath } from 'node:url';

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
const stateFile = path.join(canvasDir, 'state.json');
const layoutsDir = path.join(canvasDir, 'layouts');
const serverInfoFile = path.join(canvasDir, '.server-info');
const clientDist = path.join(__dirname, '..', 'client', 'dist');

// Ensure directories
if (!fs.existsSync(canvasDir)) fs.mkdirSync(canvasDir, { recursive: true });
if (!fs.existsSync(layoutsDir)) fs.mkdirSync(layoutsDir, { recursive: true });
if (!fs.existsSync(eventsFile)) fs.writeFileSync(eventsFile, '');

// ── Port Discovery ──
async function findFreePort(start) {
  for (let p = start; p < start + 200; p++) {
    const available = await new Promise(resolve => {
      const s = net.createServer();
      s.once('error', () => resolve(false));
      s.once('listening', () => { s.close(); resolve(true); });
      s.listen(p, host);
    });
    if (available) return p;
  }
  return 0;
}

// ── Helpers ──
function readEvents() {
  const content = fs.readFileSync(eventsFile, 'utf-8').trim();
  if (!content) return [];
  return content.split('\n').map(line => JSON.parse(line));
}

function appendEvent(event) {
  fs.appendFileSync(eventsFile, JSON.stringify(event) + '\n');
}

function sendJSON(res, data, status = 200) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

function readBody(req) {
  return new Promise(resolve => {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      try { resolve(JSON.parse(body)); }
      catch { resolve(null); }
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

// ── Server ──
// Local-only (127.0.0.1), no TLS needed for localhost dev server
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${host}`);
  const p = url.pathname;

  // CORS
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    });
    res.end(); return;
  }
  res.setHeader('Access-Control-Allow-Origin', '*');

  // ── API Routes ──

  // GET /api/events — all events
  if (p === '/api/events' && req.method === 'GET') {
    return sendJSON(res, readEvents());
  }

  // POST /api/events — append event
  if (p === '/api/events' && req.method === 'POST') {
    const body = await readBody(req);
    if (!body || !body.type) return sendJSON(res, { error: 'Missing event type' }, 400);
    body.ts = body.ts || new Date().toISOString();
    appendEvent(body);
    return sendJSON(res, { saved: true });
  }

  // GET /api/layouts/:viewId
  const layoutGet = p.match(/^\/api\/layouts\/(.+)$/);
  if (layoutGet && req.method === 'GET') {
    const file = path.join(layoutsDir, layoutGet[1] + '.json');
    if (!file.startsWith(path.resolve(layoutsDir))) return sendJSON(res, { error: 'Invalid' }, 400);
    if (fs.existsSync(file)) {
      return sendJSON(res, JSON.parse(fs.readFileSync(file, 'utf-8')));
    }
    return sendJSON(res, {});
  }

  // PUT /api/layouts/:viewId
  if (layoutGet && req.method === 'PUT') {
    const file = path.join(layoutsDir, layoutGet[1] + '.json');
    if (!file.startsWith(path.resolve(layoutsDir))) return sendJSON(res, { error: 'Invalid' }, 400);
    const body = await readBody(req);
    fs.writeFileSync(file, JSON.stringify(body, null, 2));
    return sendJSON(res, { saved: true });
  }

  // GET /api/health
  if (p === '/api/health' && req.method === 'GET') {
    const events = readEvents();
    return sendJSON(res, {
      status: 'ok',
      eventCount: events.length,
      project: path.basename(path.resolve(projectDir)),
    });
  }

  // ── Static Files ──
  if (req.method === 'GET') {
    if (serveStatic(res, p)) return;
    // SPA fallback — serve index.html for client-side routing
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
      type: 'server-started',
      port: addr.port,
      host,
      url: `http://localhost:${addr.port}`,
      pid: process.pid,
      project: path.basename(path.resolve(projectDir)),
      startedAt: new Date().toISOString(),
    };
    fs.writeFileSync(serverInfoFile, JSON.stringify(info, null, 2));
    console.log(JSON.stringify(info));
  });
}
start();

// ── Cleanup ──
function cleanup() {
  try { fs.unlinkSync(serverInfoFile); } catch {}
  process.exit(0);
}
process.on('SIGTERM', cleanup);
process.on('SIGINT', cleanup);
```

- [ ] **Step 3: Test server manually**

Run: `cd /Users/mark/Developer/code-canvas-plugin && node server/index.js --project-dir /tmp/test-canvas`
Expected: JSON output with port, url, pid

In another terminal:
Run: `curl http://localhost:9100/api/health`
Expected: `{"status":"ok","eventCount":0,...}`

Run: `curl -X POST http://localhost:9100/api/events -H 'Content-Type: application/json' -d '{"id":"ev_1","type":"node.created","actor":"test","data":{"nodeId":"n1","label":"Test","subtitle":"","parent":null,"depth":"system","category":"arch","confidence":2}}'`
Expected: `{"saved":true}`

Run: `curl http://localhost:9100/api/events`
Expected: Array with 1 event

Kill the server (Ctrl+C). Verify `/tmp/test-canvas/.code-canvas/.server-info` is cleaned up.

- [ ] **Step 4: Commit**

```bash
git add server/
git commit -m "feat: implement server — event API, layout persistence, port discovery, static file serving"
```

---

### Task 4: App Shell + Theme

**Files:**
- Create: `client/src/App.svelte`
- Create: `client/src/lib/theme.js`
- Create: `client/src/lib/state.svelte.js`
- Create: `client/src/app.css`

- [ ] **Step 1: Create theme module**

```javascript
// client/src/lib/theme.js

const STORAGE_KEY = 'code-canvas-theme';

export function getInitialTheme() {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === 'light' || stored === 'dark') return stored;
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

export function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem(STORAGE_KEY, theme);
}

export function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme');
  const next = current === 'dark' ? 'light' : 'dark';
  setTheme(next);
  return next;
}
```

- [ ] **Step 2: Create reactive state module**

```javascript
// client/src/lib/state.svelte.js
import { EventStore } from './events.js';

// Reactive state using Svelte 5 runes
export const appState = $state({
  store: new EventStore(),
  selectedIds: new Set(),
  activeView: 'all',
  activePanel: 'details',
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
```

- [ ] **Step 3: Create app CSS with theme variables**

```css
/* client/src/app.css */
[data-theme="dark"] {
  --bg: #0f1117;
  --bg-s: #161822;
  --bg-e: #1e2235;
  --bg-n: #1a1d2e;
  --bdr: #2d3148;
  --bdr-h: #3b4560;
  --tx: #e2e8f0;
  --tx-m: #94a3b8;
  --tx-d: #64748b;
  --gl: rgba(22, 24, 34, 0.88);
  --gl-b: rgba(45, 49, 72, 0.6);
  --gd: rgba(45, 49, 72, 0.25);
  --sh: rgba(0, 0, 0, 0.5);
}

[data-theme="light"] {
  --bg: #f8fafc;
  --bg-s: #ffffff;
  --bg-e: #f1f5f9;
  --bg-n: #ffffff;
  --bdr: #e2e8f0;
  --bdr-h: #cbd5e1;
  --tx: #1e293b;
  --tx-m: #475569;
  --tx-d: #94a3b8;
  --gl: rgba(255, 255, 255, 0.88);
  --gl-b: rgba(226, 232, 240, 0.6);
  --gd: rgba(148, 163, 184, 0.15);
  --sh: rgba(0, 0, 0, 0.1);
}

:root {
  --ac: #3b82f6;
  --ac2: #60a5fa;
  --gr: #10b981;
  --yl: #eab308;
  --rd: #ef4444;
  --pu: #a855f7;
  --tl: #14b8a6;
  --or: #f97316;

  /* Depth colors */
  --depth-system: #3b82f6;
  --depth-domain: #a855f7;
  --depth-module: #14b8a6;
  --depth-interface: #f97316;
}

* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--tx);
  height: 100vh;
  overflow: hidden;
  transition: background 0.3s, color 0.3s;
}
button { font-family: inherit; cursor: pointer; }
```

- [ ] **Step 4: Create App shell**

```svelte
<!-- client/src/App.svelte -->
<script>
  import './app.css';
  import { onMount } from 'svelte';
  import { getInitialTheme, setTheme, toggleTheme } from './lib/theme.js';
  import { appState, loadFromServer } from './lib/state.svelte.js';

  let theme = $state('dark');

  onMount(async () => {
    theme = getInitialTheme();
    setTheme(theme);
    await loadFromServer();
  });

  function handleToggleTheme() {
    theme = toggleTheme();
  }

  const graphState = $derived(appState.store.getState());
</script>

<div class="layout">
  <!-- Top Bar -->
  <header class="topbar">
    <div class="topbar-project">
      <span class="status-dot"></span>
      Code Canvas
    </div>

    <div class="view-tabs">
      <button class="active">Canvas</button>
      <button>Timeline</button>
      <button>Diff</button>
      <button>Story</button>
    </div>

    <div class="topbar-sep"></div>

    <div class="topbar-right">
      <button class="tbtn" onclick={() => { appState.zoom = Math.max(0.15, appState.zoom - 0.15) }}>-</button>
      <span class="zoom-display">{Math.round(appState.zoom * 100)}%</span>
      <button class="tbtn" onclick={() => { appState.zoom = Math.min(3, appState.zoom + 0.15) }}>+</button>
      <button class="tbtn" onclick={() => { appState.zoom = 1; appState.panX = 0; appState.panY = 0 }}>&#8962;</button>
      <div class="topbar-sep"></div>
      <button class="tbtn" onclick={handleToggleTheme}>
        {theme === 'dark' ? '☀' : '☾'}
      </button>
    </div>
  </header>

  <!-- Main content area -->
  <div class="main">
    <!-- Left sidebar placeholder -->
    {#if appState.sidebarOpen}
      <aside class="sidebar-left">
        <div class="sidebar-placeholder">
          <p>Tree View</p>
          <p class="meta">{graphState.nodes.size} nodes</p>
        </div>
      </aside>
    {/if}

    <!-- Canvas placeholder -->
    <main class="canvas-container">
      <div class="canvas-bg"></div>
      <div class="canvas-placeholder">
        <p>Canvas — {graphState.nodes.size} nodes, {graphState.edges.size} edges</p>
        <p class="meta">{graphState.eventCount} events loaded</p>
      </div>
    </main>

    <!-- Right panel placeholder -->
    {#if appState.panelOpen}
      <aside class="sidebar-right">
        <div class="sidebar-placeholder">
          <p>Details Panel</p>
        </div>
      </aside>
    {/if}
  </div>

  <!-- Comment bar placeholder -->
  <div class="comment-bar">
    <span class="comment-label">Comments</span>
    <span class="comment-badge">{graphState.comments.filter(c => !c.resolved).length}</span>
  </div>

  <!-- Status line -->
  <footer class="status-line">
    <span class="status-ok">● Synced</span>
    <span class="status-info">{graphState.nodes.size} nodes</span>
    <span class="status-info">{graphState.eventCount} events</span>
  </footer>
</div>

<style>
  .layout { display: flex; flex-direction: column; height: 100vh; }

  .topbar {
    display: flex; align-items: center; height: 44px;
    background: var(--bg-s); border-bottom: 1px solid var(--bdr);
    padding: 0 16px; flex-shrink: 0; gap: 10px;
  }
  .topbar-project {
    font-size: 14px; font-weight: 600;
    display: flex; align-items: center; gap: 6px; margin-right: 16px;
  }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--yl); }
  .view-tabs { display: flex; gap: 1px; background: var(--bdr); border-radius: 6px; overflow: hidden; }
  .view-tabs button {
    padding: 7px 16px; border: none; background: var(--bg-s);
    color: var(--tx-d); font-size: 12px; font-weight: 500;
  }
  .view-tabs button.active { background: var(--bg-e); color: var(--ac); }
  .topbar-sep { width: 1px; height: 18px; background: var(--bdr); margin: 0 6px; }
  .topbar-right { margin-left: auto; display: flex; gap: 4px; align-items: center; }
  .tbtn {
    height: 32px; padding: 0 10px;
    border: 1px solid var(--bdr); border-radius: 4px;
    background: transparent; color: var(--tx-m); font-size: 12px;
  }
  .tbtn:hover { border-color: var(--ac); color: var(--ac); }
  .zoom-display { font-size: 11px; color: var(--tx-d); min-width: 36px; text-align: center; }

  .main { flex: 1; display: flex; min-height: 0; }

  .sidebar-left {
    width: 260px; background: var(--gl); backdrop-filter: blur(16px);
    border-right: 1px solid var(--gl-b); flex-shrink: 0;
  }
  .sidebar-right {
    width: 300px; background: var(--gl); backdrop-filter: blur(16px);
    border-left: 1px solid var(--gl-b); flex-shrink: 0;
  }
  .sidebar-placeholder {
    padding: 20px; text-align: center; color: var(--tx-d); font-size: 12px;
  }
  .sidebar-placeholder .meta { font-size: 11px; color: var(--tx-d); margin-top: 4px; }

  .canvas-container {
    flex: 1; position: relative; overflow: hidden;
  }
  .canvas-bg {
    position: absolute; inset: 0;
    background: radial-gradient(circle at 1px 1px, var(--gd) 1px, transparent 0);
    background-size: 28px 28px;
  }
  .canvas-placeholder {
    position: absolute; inset: 0;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    color: var(--tx-d); font-size: 14px;
  }
  .canvas-placeholder .meta { font-size: 12px; margin-top: 4px; }

  .comment-bar {
    height: 28px; background: var(--gl); backdrop-filter: blur(16px);
    border-top: 1px solid var(--gl-b);
    display: flex; align-items: center; padding: 0 14px; gap: 6px; flex-shrink: 0;
  }
  .comment-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--tx-d); }
  .comment-badge {
    font-size: 9px; background: var(--ac); color: white;
    padding: 0 5px; border-radius: 7px; font-weight: 600;
  }

  .status-line {
    height: 22px; background: var(--bg-s); border-top: 1px solid var(--bdr);
    display: flex; align-items: center; padding: 0 14px; gap: 14px;
    font-size: 10px; flex-shrink: 0;
  }
  .status-ok { color: var(--gr); display: flex; align-items: center; gap: 3px; }
  .status-info { color: var(--tx-d); }
</style>
```

- [ ] **Step 5: Build and test**

Run: `cd /Users/mark/Developer/code-canvas-plugin/client && npm run build`
Expected: Build succeeds, `dist/` directory created

Run: `cd /Users/mark/Developer/code-canvas-plugin && node server/index.js --project-dir /tmp/test-canvas`
Open: `http://localhost:9100` in browser
Expected: Dark themed shell with topbar, sidebars, canvas area, comment bar, status line. Placeholder text showing "0 nodes, 0 edges".

- [ ] **Step 6: Commit**

```bash
git add client/src/
git commit -m "feat: app shell — layout, theme toggle, state management, event loading"
```

---

## Phase 2: Canvas View (Nodes, Edges, Containers)

> **Phase 2 builds the core canvas rendering.** After this phase, users can see nodes, edges, drag nodes, pan/zoom, expand/collapse containers, and interact via right-click menus. This is where most of the visual spec lands.
>
> **Tasks 5-10** cover: SVG canvas with pan/zoom, node rendering, container rendering, edge rendering, drag interaction, and context menus.
>
> Each task builds one Svelte component. Each component is independently testable by building the client and loading the canvas with sample data.

### Task 5: SVG Canvas with Pan/Zoom

**Files:**
- Create: `client/src/components/Canvas.svelte`
- Modify: `client/src/App.svelte` — replace canvas placeholder

This is the SVG viewport that holds everything. Handles pan (drag background), zoom (scroll wheel), and viewBox management.

- [ ] **Step 1: Create Canvas component**

```svelte
<!-- client/src/components/Canvas.svelte -->
<script>
  import { appState } from '../lib/state.svelte.js';

  let svgEl = $state(null);
  let isPanning = $state(false);
  let panStart = $state({ x: 0, y: 0, ox: 0, oy: 0 });

  function handleWheel(e) {
    e.preventDefault();
    appState.zoom = Math.max(0.15, Math.min(3, appState.zoom + (e.deltaY > 0 ? -0.06 : 0.06)));
  }

  function handleMouseDown(e) {
    // Only pan when clicking on background (not on nodes)
    if (e.target !== svgEl && e.target.tagName !== 'svg') return;
    isPanning = true;
    panStart = { x: e.clientX, y: e.clientY, ox: appState.panX, oy: appState.panY };
    appState.selectedIds = new Set();
  }

  function handleMouseMove(e) {
    if (!isPanning) return;
    appState.panX = panStart.ox + (e.clientX - panStart.x);
    appState.panY = panStart.oy + (e.clientY - panStart.y);
  }

  function handleMouseUp() {
    isPanning = false;
  }

  const viewBox = $derived(() => {
    if (!svgEl) return '0 0 1000 600';
    const rect = svgEl.parentElement?.getBoundingClientRect();
    if (!rect) return '0 0 1000 600';
    const vbX = -appState.panX / appState.zoom;
    const vbY = -appState.panY / appState.zoom;
    const vbW = rect.width / appState.zoom;
    const vbH = rect.height / appState.zoom;
    return `${vbX} ${vbY} ${vbW} ${vbH}`;
  });
</script>

<svelte:window onmousemove={handleMouseMove} onmouseup={handleMouseUp} />

<div class="canvas-wrap">
  <div class="canvas-bg"></div>
  <svg
    bind:this={svgEl}
    class="canvas-svg"
    class:panning={isPanning}
    viewBox={viewBox()}
    xmlns="http://www.w3.org/2000/svg"
    onwheel={handleWheel}
    onmousedown={handleMouseDown}
  >
    <slot />
  </svg>
</div>

<style>
  .canvas-wrap { flex: 1; position: relative; overflow: hidden; }
  .canvas-bg {
    position: absolute; inset: 0;
    background: radial-gradient(circle at 1px 1px, var(--gd) 1px, transparent 0);
    background-size: 28px 28px;
  }
  .canvas-svg {
    width: 100%; height: 100%; position: relative; z-index: 1;
    cursor: grab;
  }
  .canvas-svg.panning { cursor: grabbing; }
</style>
```

- [ ] **Step 2: Wire into App.svelte**

Replace the canvas placeholder section in App.svelte:

```svelte
<!-- In the <script> section, add: -->
import Canvas from './components/Canvas.svelte';

<!-- Replace <main class="canvas-container">...</main> with: -->
<Canvas>
  <!-- Nodes and edges will be rendered here -->
  <text x="50" y="50" fill="var(--tx-d)" font-size="14">
    Canvas ready — {graphState.nodes.size} nodes, {graphState.edges.size} edges
  </text>
</Canvas>
```

- [ ] **Step 3: Build and verify pan/zoom works**

Run: `cd /Users/mark/Developer/code-canvas-plugin/client && npm run build`
Run: `cd /Users/mark/Developer/code-canvas-plugin && node server/index.js --project-dir /tmp/test-canvas`
Open: browser, scroll to zoom, drag to pan.
Expected: Smooth pan/zoom on the SVG canvas.

- [ ] **Step 4: Commit**

```bash
git add client/src/components/Canvas.svelte client/src/App.svelte
git commit -m "feat: SVG canvas component with pan/zoom"
```

---

> **Tasks 6-12 continue building components in this pattern:**
> - Task 6: Node.svelte — leaf node rendering with all visual spec elements (280x90, color band, status badge, confidence dots, hover tooltip)
> - Task 7: Container.svelte — expanded parent rendering with auto-resize, header, elastic bounds
> - Task 8: Edge.svelte — bezier paths with label pills, arrow markers
> - Task 9: Drag system — node dragging with multi-select, container auto-resize on drag
> - Task 10: TreeView.svelte — left sidebar with tree connectors, search, view tabs
> - Task 11: Panel.svelte — right detail panel with details/decisions/history tabs, breadcrumbs
> - Task 12: ContextMenu.svelte + Comments.svelte — right-click everywhere, comment bar with resolution
>
> **Each follows the same pattern:** write test → verify fail → implement component → verify in browser → commit.

---

## Phase 3: Plugin Integration

> Tasks 13-15 cover hooks, the canvas skill, and context level generation.

### Task 13: Hooks

**Files:**
- Create: `hooks/hooks.json`
- Create: `hooks/canvas-session-start.sh`
- Create: `hooks/canvas-post-compact.sh`
- Create: `hooks/canvas-file-changed.sh`
- Create: `hooks/canvas-task-completed.sh`

### Task 14: Canvas Skill

**Files:**
- Create: `skills/canvas/SKILL.md`

### Task 15: Context Level Generator

**Files:**
- Create: `server/context.js` — generates L0-L3 context summaries from event store

---

## Phase 4: Advanced Views

> Tasks 16-18 build Timeline, Diff, and Story views.

### Task 16: TimelineView.svelte
### Task 17: DiffView.svelte
### Task 18: StoryView.svelte

---

## Phase 5: Polish & Distribution

### Task 19: Marketplace Setup

**Files:**
- Create GitHub repo `lilo-labs/code-canvas-plugin`
- Create marketplace manifest
- Configure in settings.json

### Task 20: Export Functionality

**Files:**
- Create: `server/export.js` — markdown, PNG, prompt export

---

**Total: ~20 tasks across 5 phases.** Phase 1-2 (Tasks 1-12) produce a working canvas. Phase 3 (13-15) integrates with Claude Code. Phase 4-5 (16-20) add advanced views and distribution.
