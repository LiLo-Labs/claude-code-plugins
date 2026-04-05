# Plugin Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Claude aware of the design canvas — inject context at session start, track file changes, suggest canvas during planning, and provide `/canvas` commands.

**Architecture:** Node.js hook scripts share a `canvas-client.js` library that reads JSONL events, computes summaries, manages server lifecycle, and matches files to nodes. A single SKILL.md teaches Claude all `/canvas` commands. Server gets batch endpoint + state endpoint.

**Tech Stack:** Node.js (vanilla, zero npm deps), JSONL, HTTP

---

### Task 1: glob-match.js — Minimal Glob Matcher

**Files:**
- Create: `hooks/lib/glob-match.js`
- Create: `hooks/lib/glob-match.test.js`

- [ ] **Step 1: Write the failing tests**

Create `hooks/lib/glob-match.test.js`:

```js
import { describe, it, expect } from 'vitest';
import { globMatch } from './glob-match.js';

describe('globMatch', () => {
  it('matches exact paths', () => {
    expect(globMatch('src/lib/events.js', 'src/lib/events.js')).toBe(true);
  });

  it('rejects non-matching exact paths', () => {
    expect(globMatch('src/lib/events.js', 'src/lib/layout.js')).toBe(false);
  });

  it('matches * as single segment wildcard', () => {
    expect(globMatch('src/lib/*.js', 'src/lib/events.js')).toBe(true);
    expect(globMatch('src/lib/*.js', 'src/lib/deep/events.js')).toBe(false);
  });

  it('matches ** as multi-segment wildcard', () => {
    expect(globMatch('src/**/*.js', 'src/lib/events.js')).toBe(true);
    expect(globMatch('src/**/*.js', 'src/lib/deep/events.js')).toBe(true);
    expect(globMatch('src/**/*.js', 'other/file.js')).toBe(false);
  });

  it('matches ? as single character', () => {
    expect(globMatch('src/lib/events.?s', 'src/lib/events.js')).toBe(true);
    expect(globMatch('src/lib/events.?s', 'src/lib/events.ts')).toBe(true);
    expect(globMatch('src/lib/events.?s', 'src/lib/events.css')).toBe(false);
  });

  it('matches src/lib/events.* pattern', () => {
    expect(globMatch('src/lib/events.*', 'src/lib/events.js')).toBe(true);
    expect(globMatch('src/lib/events.*', 'src/lib/events.test.js')).toBe(false);
  });

  it('normalizes backslashes to forward slashes', () => {
    expect(globMatch('src/lib/*.js', 'src\\lib\\events.js')).toBe(true);
  });
});
```

- [ ] **Step 2: Create glob-match.js with exports only**

Create `hooks/lib/glob-match.js`:

```js
/**
 * Minimal glob matcher — zero dependencies.
 * Supports: * (single segment), ** (multi-segment), ? (single char)
 */
export function globMatch(pattern, filePath) {
  return false;
}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/mark/Developer/code-canvas-plugin && npx vitest run hooks/lib/glob-match.test.js`
Expected: All tests fail except "rejects non-matching exact paths"

- [ ] **Step 4: Implement globMatch**

Replace `hooks/lib/glob-match.js`:

```js
/**
 * Minimal glob matcher — zero dependencies.
 * Supports: * (single segment), ** (multi-segment), ? (single char)
 */
export function globMatch(pattern, filePath) {
  const p = pattern.replace(/\\/g, '/');
  const f = filePath.replace(/\\/g, '/');

  let regex = '';
  let i = 0;
  while (i < p.length) {
    if (p[i] === '*' && p[i + 1] === '*') {
      regex += '.*';
      i += 2;
      if (p[i] === '/') i++;
    } else if (p[i] === '*') {
      regex += '[^/]*';
      i++;
    } else if (p[i] === '?') {
      regex += '[^/]';
      i++;
    } else if ('.+^${}()|[]\\'.includes(p[i])) {
      regex += '\\' + p[i];
      i++;
    } else {
      regex += p[i];
      i++;
    }
  }

  return new RegExp('^' + regex + '$').test(f);
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/mark/Developer/code-canvas-plugin && npx vitest run hooks/lib/glob-match.test.js`
Expected: All 7 tests pass

- [ ] **Step 6: Commit**

```bash
git add hooks/lib/glob-match.js hooks/lib/glob-match.test.js
git commit -m "feat: add minimal glob matcher for file-to-node mapping"
```

---

### Task 2: canvas-client.js — Event Reading & Replay

**Files:**
- Create: `hooks/lib/canvas-client.js`
- Create: `hooks/lib/canvas-client.test.js`

- [ ] **Step 1: Write failing tests for readEvents and replayState**

Create `hooks/lib/canvas-client.test.js`:

```js
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {
  readEvents, replayState, generateL0, generateL1,
  findNodesForFile, getServerUrl, findProjectDir,
} from './canvas-client.js';

let tmpDir;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'canvas-test-'));
  fs.mkdirSync(path.join(tmpDir, '.code-canvas'));
});

afterEach(() => {
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

function writeEvents(events) {
  const file = path.join(tmpDir, '.code-canvas', 'events.jsonl');
  fs.writeFileSync(file, events.map(e => JSON.stringify(e)).join('\n') + '\n');
}

describe('readEvents', () => {
  it('reads JSONL file into event array', () => {
    writeEvents([
      { id: 'ev_1', ts: '2026-03-30T00:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n1', label: 'Auth' } },
      { id: 'ev_2', ts: '2026-03-30T00:01:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n2', label: 'DB' } },
    ]);
    const events = readEvents(tmpDir);
    expect(events).toHaveLength(2);
    expect(events[0].data.nodeId).toBe('n1');
  });

  it('returns empty array when events.jsonl is missing', () => {
    const noEventsDir = fs.mkdtempSync(path.join(os.tmpdir(), 'canvas-no-events-'));
    fs.mkdirSync(path.join(noEventsDir, '.code-canvas'));
    const events = readEvents(noEventsDir);
    expect(events).toEqual([]);
    fs.rmSync(noEventsDir, { recursive: true, force: true });
  });

  it('skips malformed lines', () => {
    const file = path.join(tmpDir, '.code-canvas', 'events.jsonl');
    fs.writeFileSync(file, '{"id":"ev_1","type":"node.created","actor":"claude","data":{"nodeId":"n1","label":"A"}}\nNOT_JSON\n{"id":"ev_2","type":"node.created","actor":"claude","data":{"nodeId":"n2","label":"B"}}\n');
    const events = readEvents(tmpDir);
    expect(events).toHaveLength(2);
  });
});

describe('replayState', () => {
  it('replays nodes, edges, comments, decisions, views', () => {
    const events = [
      { id: 'ev_1', ts: '2026-03-30T00:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n1', label: 'Auth', subtitle: 'Login', depth: 'domain', category: 'arch', confidence: 2, files: ['src/auth/**'] } },
      { id: 'ev_2', ts: '2026-03-30T00:00:01Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n2', label: 'DB', subtitle: 'Store', depth: 'system', category: 'arch', confidence: 3 } },
      { id: 'ev_3', ts: '2026-03-30T00:00:02Z', type: 'edge.created', actor: 'claude', data: { edgeId: 'e1', from: 'n1', to: 'n2', label: 'reads' } },
      { id: 'ev_4', ts: '2026-03-30T00:00:03Z', type: 'node.status', actor: 'claude', data: { nodeId: 'n1', status: 'in-progress', prev: 'planned' } },
      { id: 'ev_5', ts: '2026-03-30T00:00:04Z', type: 'decision.recorded', actor: 'claude', data: { nodeId: 'n1', type: 'decision', chosen: 'JWT', alternatives: ['Session'], reason: 'Stateless' } },
      { id: 'ev_6', ts: '2026-03-30T00:00:05Z', type: 'comment.added', actor: 'user', data: { commentId: 'c1', target: 'n1', targetLabel: 'Auth', text: 'Add rate limiting', actor: 'user' } },
      { id: 'ev_7', ts: '2026-03-30T00:00:06Z', type: 'view.created', actor: 'claude', data: { viewId: 'v1', name: 'Overview', tabNodes: [{ nodeId: 'n1', row: 0, col: 0 }], tabConnections: [] } },
    ];
    const state = replayState(events);
    expect(state.nodes.size).toBe(2);
    expect(state.nodes.get('n1').status).toBe('in-progress');
    expect(state.nodes.get('n1').files).toEqual(['src/auth/**']);
    expect(state.nodes.get('n2').files).toEqual([]);
    expect(state.edges.size).toBe(1);
    expect(state.comments).toHaveLength(1);
    expect(state.decisions).toHaveLength(1);
    expect(state.views).toHaveLength(1);
  });

  it('handles comment lifecycle (add, resolve, reopen, delete)', () => {
    const events = [
      { id: 'ev_1', ts: '2026-03-30T00:00:00Z', type: 'comment.added', actor: 'user', data: { commentId: 'c1', target: 'n1', targetLabel: 'A', text: 'Fix', actor: 'user' } },
      { id: 'ev_2', ts: '2026-03-30T00:01:00Z', type: 'comment.resolved', actor: 'claude', data: { commentId: 'c1' } },
      { id: 'ev_3', ts: '2026-03-30T00:02:00Z', type: 'comment.reopened', actor: 'user', data: { commentId: 'c1' } },
      { id: 'ev_4', ts: '2026-03-30T00:03:00Z', type: 'comment.added', actor: 'user', data: { commentId: 'c2', target: 'n1', targetLabel: 'A', text: 'Delete me', actor: 'user' } },
      { id: 'ev_5', ts: '2026-03-30T00:04:00Z', type: 'comment.deleted', actor: 'user', data: { commentId: 'c2' } },
    ];
    const state = replayState(events);
    expect(state.comments).toHaveLength(1);
    expect(state.comments[0].resolved).toBe(false);
  });

  it('handles node.updated with changes object', () => {
    const events = [
      { id: 'ev_1', ts: '2026-03-30T00:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n1', label: 'Old', depth: 'module' } },
      { id: 'ev_2', ts: '2026-03-30T00:01:00Z', type: 'node.updated', actor: 'claude', data: { nodeId: 'n1', changes: { label: 'New', files: ['src/new/**'] } } },
    ];
    const state = replayState(events);
    expect(state.nodes.get('n1').label).toBe('New');
    expect(state.nodes.get('n1').files).toEqual(['src/new/**']);
  });
});
```

- [ ] **Step 2: Create canvas-client.js**

Create `hooks/lib/canvas-client.js`:

```js
/**
 * Shared library for Code Canvas hooks.
 * Reads JSONL events, computes state, generates context summaries.
 * Zero npm dependencies.
 */
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import http from 'node:http';
import { globMatch } from './glob-match.js';

// ── Project Discovery ──

export function findProjectDir(startDir = process.cwd()) {
  let dir = path.resolve(startDir);
  while (true) {
    if (fs.existsSync(path.join(dir, '.code-canvas'))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

// ── Event Reading (file-based, no server needed) ──

export function readEvents(projectDir) {
  const file = path.join(projectDir, '.code-canvas', 'events.jsonl');
  if (!fs.existsSync(file)) return [];
  const content = fs.readFileSync(file, 'utf-8').trim();
  if (!content) return [];
  const events = [];
  for (const line of content.split('\n')) {
    if (!line.trim()) continue;
    try { events.push(JSON.parse(line)); }
    catch { /* skip malformed */ }
  }
  return events;
}

export function replayState(events) {
  const nodes = new Map();
  const edges = new Map();
  let comments = [];
  const decisions = [];
  const views = [];

  for (const event of events) {
    const d = event.data;
    switch (event.type) {
      case 'node.created':
        nodes.set(d.nodeId, {
          id: d.nodeId, label: d.label || '', subtitle: d.subtitle || '',
          parent: d.parent || null, status: d.status || 'planned',
          depth: d.depth || 'module', category: d.category || 'arch',
          confidence: d.confidence ?? 1, files: d.files || [],
        });
        break;
      case 'node.updated':
        if (nodes.has(d.nodeId)) Object.assign(nodes.get(d.nodeId), d.changes || {});
        break;
      case 'node.deleted':
        nodes.delete(d.nodeId);
        break;
      case 'node.status':
        if (nodes.has(d.nodeId)) nodes.get(d.nodeId).status = d.status;
        break;
      case 'edge.created':
        edges.set(d.edgeId, {
          id: d.edgeId, from: d.from, to: d.to,
          label: d.label || '', edgeType: d.edgeType || 'dependency',
          color: d.color || '#64748b',
        });
        break;
      case 'edge.updated':
        if (edges.has(d.edgeId)) Object.assign(edges.get(d.edgeId), d.changes || {});
        break;
      case 'edge.deleted':
        edges.delete(d.edgeId);
        break;
      case 'decision.recorded':
        decisions.push({
          nodeId: d.nodeId, type: d.type || 'decision',
          chosen: d.chosen, alternatives: d.alternatives || [],
          reason: d.reason || '', ts: event.ts, actor: event.actor,
        });
        break;
      case 'comment.added':
        comments.push({
          id: d.commentId, target: d.target,
          targetLabel: d.targetLabel || '', text: d.text,
          actor: d.actor || event.actor, resolved: false, ts: event.ts,
        });
        break;
      case 'comment.resolved': {
        const c = comments.find(c => c.id === d.commentId);
        if (c) c.resolved = true;
        break;
      }
      case 'comment.reopened': {
        const c = comments.find(c => c.id === d.commentId);
        if (c) c.resolved = false;
        break;
      }
      case 'comment.deleted':
        comments = comments.filter(c => c.id !== d.commentId);
        break;
      case 'view.created':
        views.push({
          id: d.viewId, name: d.name, description: d.description || '',
          tabNodes: d.tabNodes || [], tabConnections: d.tabConnections || [],
        });
        break;
      case 'view.updated': {
        const v = views.find(v => v.id === d.viewId);
        if (v) Object.assign(v, d.changes || {});
        break;
      }
    }
  }

  return { nodes, edges, comments, decisions, views, lastEvent: events[events.length - 1] || null };
}

// ── Context Generation ──

export function generateL0(state) {
  const { nodes, edges, comments, decisions, views, lastEvent } = state;
  const nodeArr = [...nodes.values()];
  const statusCounts = {};
  for (const n of nodeArr) statusCounts[n.status] = (statusCounts[n.status] || 0) + 1;
  const statusParts = Object.entries(statusCounts).map(([s, c]) => `${c} ${s}`).join(', ');
  const unresolvedCount = comments.filter(c => !c.resolved).length;
  const viewNames = views.map(v => v.name).join(', ') || 'none';
  const lastActivity = lastEvent ? lastEvent.ts : 'none';

  return [
    `Nodes: ${nodeArr.length}${statusParts ? ` (${statusParts})` : ''}`,
    `Edges: ${edges.size} connections`,
    `Views: ${viewNames}`,
    `Comments: ${unresolvedCount} unresolved`,
    `Decisions: ${decisions.length} recorded`,
    `Last activity: ${lastActivity}`,
  ].join('\n');
}

export function generateL1(state) {
  const { nodes, edges, comments, views } = state;
  const lines = ['Nodes:'];
  for (const [id, n] of nodes) {
    const filesPart = n.files.length > 0 ? ` files: ${n.files.join(', ')}` : '';
    lines.push(`- ${id}: ${n.label} [${n.status}] (${n.depth})${filesPart}`);
  }
  if (edges.size > 0) {
    lines.push('', 'Edges:');
    for (const [, e] of edges) lines.push(`- ${e.from} \u2192 ${e.to}: ${e.label}`);
  }
  if (views.length > 0) {
    lines.push('', 'Views:');
    for (const v of views) lines.push(`- ${v.name}: ${v.tabNodes.length} nodes, ${v.tabConnections.length} connections`);
  }
  const unresolved = comments.filter(c => !c.resolved);
  if (unresolved.length > 0) {
    lines.push('', 'Unresolved comments:');
    for (const c of unresolved) lines.push(`- ${c.targetLabel || c.target}: "${c.text}" (${c.actor})`);
  }
  return lines.join('\n');
}

// ── File-to-Node Matching ──

export function findNodesForFile(filePath, nodes) {
  const normalized = filePath.replace(/\\/g, '/');
  const matches = [];
  for (const [id, node] of nodes) {
    const files = node.files || [];
    for (const pattern of files) {
      if (globMatch(pattern, normalized)) {
        matches.push(id);
        break;
      }
    }
  }
  return matches;
}

// ── Server Lifecycle ──

export function getServerUrl(projectDir) {
  const infoFile = path.join(projectDir, '.code-canvas', '.server-info');
  if (!fs.existsSync(infoFile)) return null;
  try {
    const info = JSON.parse(fs.readFileSync(infoFile, 'utf-8'));
    return info.url || null;
  } catch { return null; }
}

function healthCheck(url) {
  return new Promise(resolve => {
    const req = http.get(`${url}/api/health`, { timeout: 2000 }, res => {
      let body = '';
      res.on('data', chunk => { body += chunk; });
      res.on('end', () => resolve(res.statusCode === 200));
    });
    req.on('error', () => resolve(false));
    req.on('timeout', () => { req.destroy(); resolve(false); });
  });
}

export async function ensureServer(projectDir, pluginRoot) {
  const url = getServerUrl(projectDir);
  if (url && await healthCheck(url)) return url;

  const serverScript = path.join(pluginRoot, 'server', 'index.js');
  const child = spawn('node', [serverScript, '--project-dir', projectDir], {
    cwd: projectDir,
    stdio: 'ignore',
    detached: true,
  });
  child.unref();

  for (let i = 0; i < 20; i++) {
    await new Promise(r => setTimeout(r, 500));
    const newUrl = getServerUrl(projectDir);
    if (newUrl && await healthCheck(newUrl)) return newUrl;
  }
  return null;
}

export function stopServer(projectDir) {
  const infoFile = path.join(projectDir, '.code-canvas', '.server-info');
  if (!fs.existsSync(infoFile)) return;
  try {
    const info = JSON.parse(fs.readFileSync(infoFile, 'utf-8'));
    if (info.pid) process.kill(info.pid, 'SIGTERM');
  } catch { /* process already dead */ }
}

// ── API Helpers ──

function httpPost(url, data) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(data);
    const parsed = new URL(url);
    const req = http.request({
      hostname: parsed.hostname, port: parsed.port,
      path: parsed.pathname, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
      timeout: 5000,
    }, res => {
      let result = '';
      res.on('data', chunk => { result += chunk; });
      res.on('end', () => {
        try { resolve(JSON.parse(result)); }
        catch { resolve({ raw: result }); }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('timeout')); });
    req.write(body);
    req.end();
  });
}

export async function postEvent(serverUrl, event) {
  return httpPost(`${serverUrl}/api/events`, event);
}

export async function postEvents(serverUrl, events) {
  return httpPost(`${serverUrl}/api/events/batch`, events);
}
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd /Users/mark/Developer/code-canvas-plugin && npx vitest run hooks/lib/canvas-client.test.js`
Expected: All 6 tests pass (readEvents 3 + replayState 3)

- [ ] **Step 4: Commit**

```bash
git add hooks/lib/canvas-client.js hooks/lib/canvas-client.test.js
git commit -m "feat: canvas-client shared library — event reading, replay, context gen, server lifecycle"
```

---

### Task 3: canvas-client.js — Context Generation Tests

**Files:**
- Modify: `hooks/lib/canvas-client.test.js`

- [ ] **Step 1: Add tests for generateL0, generateL1, findNodesForFile, getServerUrl, findProjectDir**

Append to `hooks/lib/canvas-client.test.js`:

```js
describe('generateL0', () => {
  it('produces summary with counts', () => {
    const events = [
      { id: 'ev_1', ts: '2026-03-30T10:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n1', label: 'Auth', depth: 'domain' } },
      { id: 'ev_2', ts: '2026-03-30T10:01:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n2', label: 'DB', depth: 'system' } },
      { id: 'ev_3', ts: '2026-03-30T10:02:00Z', type: 'node.status', actor: 'claude', data: { nodeId: 'n1', status: 'done', prev: 'planned' } },
      { id: 'ev_4', ts: '2026-03-30T10:03:00Z', type: 'edge.created', actor: 'claude', data: { edgeId: 'e1', from: 'n1', to: 'n2', label: 'reads' } },
      { id: 'ev_5', ts: '2026-03-30T10:04:00Z', type: 'comment.added', actor: 'user', data: { commentId: 'c1', target: 'n1', targetLabel: 'Auth', text: 'Rate limit', actor: 'user' } },
      { id: 'ev_6', ts: '2026-03-30T10:05:00Z', type: 'decision.recorded', actor: 'claude', data: { nodeId: 'n1', type: 'decision', chosen: 'JWT', alternatives: ['Session'], reason: 'Stateless' } },
      { id: 'ev_7', ts: '2026-03-30T10:06:00Z', type: 'view.created', actor: 'claude', data: { viewId: 'v1', name: 'Overview', tabNodes: [], tabConnections: [] } },
    ];
    const state = replayState(events);
    const l0 = generateL0(state);
    expect(l0).toContain('Nodes: 2');
    expect(l0).toContain('1 done');
    expect(l0).toContain('1 planned');
    expect(l0).toContain('Edges: 1');
    expect(l0).toContain('Comments: 1 unresolved');
    expect(l0).toContain('Decisions: 1');
    expect(l0).toContain('Overview');
  });

  it('handles empty state', () => {
    const state = replayState([]);
    const l0 = generateL0(state);
    expect(l0).toContain('Nodes: 0');
  });
});

describe('generateL1', () => {
  it('lists all nodes with details', () => {
    const events = [
      { id: 'ev_1', ts: '2026-03-30T10:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n1', label: 'Auth', depth: 'domain', files: ['src/auth/**'] } },
      { id: 'ev_2', ts: '2026-03-30T10:01:00Z', type: 'edge.created', actor: 'claude', data: { edgeId: 'e1', from: 'n1', to: 'n2', label: 'reads' } },
      { id: 'ev_3', ts: '2026-03-30T10:02:00Z', type: 'view.created', actor: 'claude', data: { viewId: 'v1', name: 'Arch', tabNodes: [{ nodeId: 'n1' }], tabConnections: [] } },
      { id: 'ev_4', ts: '2026-03-30T10:03:00Z', type: 'comment.added', actor: 'user', data: { commentId: 'c1', target: 'n1', targetLabel: 'Auth', text: 'Fix this', actor: 'user' } },
    ];
    const state = replayState(events);
    const l1 = generateL1(state);
    expect(l1).toContain('n1: Auth [planned] (domain)');
    expect(l1).toContain('src/auth/**');
    expect(l1).toContain('n1 \u2192 n2: reads');
    expect(l1).toContain('Arch: 1 nodes');
    expect(l1).toContain('Auth: "Fix this"');
  });
});

describe('findNodesForFile', () => {
  it('matches file against node glob patterns', () => {
    const nodes = new Map([
      ['n1', { id: 'n1', files: ['src/auth/**/*.js'] }],
      ['n2', { id: 'n2', files: ['src/db/**'] }],
      ['n3', { id: 'n3', files: [] }],
    ]);
    expect(findNodesForFile('src/auth/login.js', nodes)).toEqual(['n1']);
    expect(findNodesForFile('src/db/schema.sql', nodes)).toEqual(['n2']);
    expect(findNodesForFile('src/other/file.js', nodes)).toEqual([]);
  });

  it('returns multiple matches', () => {
    const nodes = new Map([
      ['n1', { id: 'n1', files: ['src/**/*.js'] }],
      ['n2', { id: 'n2', files: ['src/auth/**'] }],
    ]);
    expect(findNodesForFile('src/auth/login.js', nodes).sort()).toEqual(['n1', 'n2']);
  });

  it('handles nodes with no files field', () => {
    const nodes = new Map([['n1', { id: 'n1' }]]);
    expect(findNodesForFile('src/file.js', nodes)).toEqual([]);
  });
});

describe('getServerUrl', () => {
  it('returns URL from .server-info', () => {
    const infoFile = path.join(tmpDir, '.code-canvas', '.server-info');
    fs.writeFileSync(infoFile, JSON.stringify({ port: 9100, url: 'http://localhost:9100', pid: 12345 }));
    expect(getServerUrl(tmpDir)).toBe('http://localhost:9100');
  });

  it('returns null when .server-info is missing', () => {
    expect(getServerUrl(tmpDir)).toBeNull();
  });
});

describe('findProjectDir', () => {
  it('finds .code-canvas in current dir', () => {
    expect(findProjectDir(tmpDir)).toBe(tmpDir);
  });

  it('finds .code-canvas in parent dir', () => {
    const child = path.join(tmpDir, 'src', 'lib');
    fs.mkdirSync(child, { recursive: true });
    expect(findProjectDir(child)).toBe(tmpDir);
  });

  it('returns null when no .code-canvas found', () => {
    const noCanvas = fs.mkdtempSync(path.join(os.tmpdir(), 'no-canvas-'));
    expect(findProjectDir(noCanvas)).toBeNull();
    fs.rmSync(noCanvas, { recursive: true, force: true });
  });
});
```

- [ ] **Step 2: Run all tests**

Run: `cd /Users/mark/Developer/code-canvas-plugin && npx vitest run hooks/lib/canvas-client.test.js`
Expected: All tests pass (readEvents 3 + replayState 3 + generateL0 2 + generateL1 1 + findNodesForFile 3 + getServerUrl 2 + findProjectDir 3 = 17 tests)

- [ ] **Step 3: Commit**

```bash
git add hooks/lib/canvas-client.test.js
git commit -m "test: comprehensive tests for canvas-client context gen, file matching, server lifecycle"
```

---

### Task 4: Server Extensions — Batch Endpoint, State Endpoint

**Files:**
- Modify: `server/index.js`
- Create: `server/index.test.js`

- [ ] **Step 1: Write failing tests for new endpoints**

Create `server/index.test.js`. Note: uses `node:child_process` `spawn` for test server lifecycle (controlled test infrastructure, not user input):

```js
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';

let serverProcess;
let port;
let tmpDir;

function httpGet(urlPath) {
  return new Promise((resolve, reject) => {
    http.get(`http://127.0.0.1:${port}${urlPath}`, res => {
      let body = '';
      res.on('data', chunk => { body += chunk; });
      res.on('end', () => resolve({ status: res.statusCode, body: JSON.parse(body) }));
    }).on('error', reject);
  });
}

function httpPost(urlPath, data) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(data);
    const req = http.request({
      hostname: '127.0.0.1', port, path: urlPath, method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, res => {
      let result = '';
      res.on('data', chunk => { result += chunk; });
      res.on('end', () => resolve({ status: res.statusCode, body: JSON.parse(result) }));
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

beforeAll(async () => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'canvas-server-test-'));
  const serverScript = path.resolve('server/index.js');
  port = 9190 + Math.floor(Math.random() * 10);
  serverProcess = spawn('node', [serverScript, '--project-dir', tmpDir, '--port', String(port)], { stdio: 'pipe' });

  await new Promise((resolve) => {
    serverProcess.stdout.on('data', (data) => {
      if (data.toString().includes('server-started')) resolve();
    });
    setTimeout(resolve, 3000);
  });
});

afterAll(() => {
  if (serverProcess) serverProcess.kill('SIGTERM');
  if (tmpDir) fs.rmSync(tmpDir, { recursive: true, force: true });
});

describe('POST /api/events/batch', () => {
  it('appends multiple events', async () => {
    const events = [
      { type: 'node.created', actor: 'claude', data: { nodeId: 'n1', label: 'Auth' } },
      { type: 'node.created', actor: 'claude', data: { nodeId: 'n2', label: 'DB' } },
    ];
    const res = await httpPost('/api/events/batch', events);
    expect(res.status).toBe(200);
    expect(res.body.appended).toBe(2);
  });

  it('rejects non-array body', async () => {
    const res = await httpPost('/api/events/batch', { type: 'node.created' });
    expect(res.status).toBe(400);
  });

  it('rejects events missing type', async () => {
    const res = await httpPost('/api/events/batch', [{ actor: 'claude', data: {} }]);
    expect(res.status).toBe(400);
  });
});

describe('GET /api/state', () => {
  it('returns replayed state', async () => {
    const res = await httpGet('/api/state');
    expect(res.status).toBe(200);
    expect(res.body).toHaveProperty('nodes');
    expect(res.body).toHaveProperty('edges');
    expect(res.body).toHaveProperty('comments');
    expect(res.body).toHaveProperty('decisions');
    expect(res.body).toHaveProperty('views');
  });

  it('returns L0 summary with ?level=L0', async () => {
    const res = await httpGet('/api/state?level=L0');
    expect(res.status).toBe(200);
    expect(res.body.summary).toContain('Nodes:');
  });

  it('returns L1 structure with ?level=L1', async () => {
    const res = await httpGet('/api/state?level=L1');
    expect(res.status).toBe(200);
    expect(res.body.summary).toContain('Nodes:');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mark/Developer/code-canvas-plugin && npx vitest run server/index.test.js`
Expected: batch and state endpoint tests fail (404)

- [ ] **Step 3: Add batch endpoint, state endpoint, and replay functions to server**

In `server/index.js`, add replay functions after the existing `readEvents` function (around line 57):

```js
function replayEventsToState(events) {
  const nodes = new Map();
  const edges = new Map();
  let comments = [];
  const decisions = [];
  const views = [];
  for (const event of events) {
    const d = event.data;
    switch (event.type) {
      case 'node.created':
        nodes.set(d.nodeId, { id: d.nodeId, label: d.label || '', subtitle: d.subtitle || '', parent: d.parent || null, status: d.status || 'planned', depth: d.depth || 'module', category: d.category || 'arch', confidence: d.confidence ?? 1, files: d.files || [] });
        break;
      case 'node.updated': if (nodes.has(d.nodeId)) Object.assign(nodes.get(d.nodeId), d.changes || {}); break;
      case 'node.deleted': nodes.delete(d.nodeId); break;
      case 'node.status': if (nodes.has(d.nodeId)) nodes.get(d.nodeId).status = d.status; break;
      case 'edge.created': edges.set(d.edgeId, { id: d.edgeId, from: d.from, to: d.to, label: d.label || '', edgeType: d.edgeType || 'dependency', color: d.color || '#64748b' }); break;
      case 'edge.updated': if (edges.has(d.edgeId)) Object.assign(edges.get(d.edgeId), d.changes || {}); break;
      case 'edge.deleted': edges.delete(d.edgeId); break;
      case 'decision.recorded': decisions.push({ nodeId: d.nodeId, type: d.type || 'decision', chosen: d.chosen, alternatives: d.alternatives || [], reason: d.reason || '', ts: event.ts, actor: event.actor }); break;
      case 'comment.added': comments.push({ id: d.commentId, target: d.target, targetLabel: d.targetLabel || '', text: d.text, actor: d.actor || event.actor, resolved: false, ts: event.ts }); break;
      case 'comment.resolved': { const c = comments.find(c => c.id === d.commentId); if (c) c.resolved = true; break; }
      case 'comment.reopened': { const c = comments.find(c => c.id === d.commentId); if (c) c.resolved = false; break; }
      case 'comment.deleted': comments = comments.filter(c => c.id !== d.commentId); break;
      case 'view.created': views.push({ id: d.viewId, name: d.name, description: d.description || '', tabNodes: d.tabNodes || [], tabConnections: d.tabConnections || [] }); break;
      case 'view.updated': { const v = views.find(v => v.id === d.viewId); if (v) Object.assign(v, d.changes || {}); break; }
    }
  }
  return { nodes, edges, comments, decisions, views, lastEvent: events[events.length - 1] || null };
}

function formatL0(state) {
  const nodeArr = [...state.nodes.values()];
  const sc = {}; for (const n of nodeArr) sc[n.status] = (sc[n.status] || 0) + 1;
  const sp = Object.entries(sc).map(([s, c]) => `${c} ${s}`).join(', ');
  const uc = state.comments.filter(c => !c.resolved).length;
  return [`Nodes: ${nodeArr.length}${sp ? ` (${sp})` : ''}`, `Edges: ${state.edges.size} connections`, `Views: ${state.views.map(v => v.name).join(', ') || 'none'}`, `Comments: ${uc} unresolved`, `Decisions: ${state.decisions.length} recorded`, `Last activity: ${state.lastEvent ? state.lastEvent.ts : 'none'}`].join('\n');
}

function formatL1(state) {
  const lines = ['Nodes:'];
  for (const [id, n] of state.nodes) { const fp = n.files.length > 0 ? ` files: ${n.files.join(', ')}` : ''; lines.push(`- ${id}: ${n.label} [${n.status}] (${n.depth})${fp}`); }
  if (state.edges.size > 0) { lines.push('', 'Edges:'); for (const [, e] of state.edges) lines.push(`- ${e.from} \u2192 ${e.to}: ${e.label}`); }
  if (state.views.length > 0) { lines.push('', 'Views:'); for (const v of state.views) lines.push(`- ${v.name}: ${v.tabNodes.length} nodes, ${v.tabConnections.length} connections`); }
  const ur = state.comments.filter(c => !c.resolved); if (ur.length > 0) { lines.push('', 'Unresolved comments:'); for (const c of ur) lines.push(`- ${c.targetLabel || c.target}: "${c.text}" (${c.actor})`); }
  return lines.join('\n');
}
```

Add the new endpoints in the request handler, after the existing `POST /api/events` block:

```js
  // POST /api/events/batch
  if (p === '/api/events/batch' && req.method === 'POST') {
    const body = await readBody(req);
    if (!Array.isArray(body)) return sendJSON(res, { error: 'Expected JSON array' }, 400);
    for (const event of body) {
      if (!event || !event.type) return sendJSON(res, { error: 'Each event must have a type' }, 400);
    }
    const lines = body.map(e => { e.ts = e.ts || new Date().toISOString(); return JSON.stringify(e); }).join('\n') + '\n';
    fs.appendFileSync(eventsFile, lines);
    eventCount += body.length;
    return sendJSON(res, { appended: body.length });
  }

  // GET /api/state
  if (p === '/api/state' && req.method === 'GET') {
    const events = readEvents();
    const state = replayEventsToState(events);
    const level = url.searchParams.get('level');
    if (level === 'L0' || level === 'L1') {
      return sendJSON(res, { summary: level === 'L0' ? formatL0(state) : formatL1(state) });
    }
    return sendJSON(res, {
      nodes: Object.fromEntries(state.nodes),
      edges: Object.fromEntries(state.edges),
      comments: state.comments,
      decisions: state.decisions,
      views: state.views,
    });
  }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/mark/Developer/code-canvas-plugin && npx vitest run server/index.test.js`
Expected: All 6 tests pass

- [ ] **Step 5: Commit**

```bash
git add server/index.js server/index.test.js
git commit -m "feat: batch events endpoint, state endpoint with L0/L1 summaries"
```

---

### Task 5: Node Model — files Field in Client EventStore

**Files:**
- Modify: `client/src/lib/events.js`
- Modify: `client/src/lib/events.test.js`

- [ ] **Step 1: Write failing tests for files field**

Add to `client/src/lib/events.test.js` inside the `describe('EventStore')` block:

```js
  it('stores files field on node.created', () => {
    const store = new EventStore();
    store.apply({
      id: 'ev_1', ts: '2026-03-30T00:00:00Z', type: 'node.created', actor: 'claude',
      data: { nodeId: 'n1', label: 'Auth', subtitle: '', parent: null, depth: 'domain', category: 'arch', confidence: 2, files: ['src/auth/**'] },
    });
    expect(store.getState().nodes.get('n1').files).toEqual(['src/auth/**']);
  });

  it('defaults files to empty array', () => {
    const store = new EventStore();
    store.apply({
      id: 'ev_1', ts: '2026-03-30T00:00:00Z', type: 'node.created', actor: 'claude',
      data: { nodeId: 'n1', label: 'Auth', subtitle: '', parent: null, depth: 'domain', category: 'arch', confidence: 2 },
    });
    expect(store.getState().nodes.get('n1').files).toEqual([]);
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/mark/Developer/code-canvas-plugin && npx vitest run client/src/lib/events.test.js`
Expected: New files field tests fail

- [ ] **Step 3: Add files field to node.created in EventStore**

In `client/src/lib/events.js`, in the `node.created` case, add `files: d.files || [],` after the `confidence` line:

```js
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
          files: d.files || [],
          row: d.row ?? 0,
          col: d.col ?? 0,
          cols: d.cols ?? 3,
          color: d.color || null,
          textColor: d.textColor || null,
          hasWorkaround: false,
          completeness: 0,
        });
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/mark/Developer/code-canvas-plugin && npx vitest run client/src/lib/events.test.js`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add client/src/lib/events.js client/src/lib/events.test.js
git commit -m "feat: add files field to node model in client EventStore"
```

---

### Task 6: DetailPanel — Display File Patterns

**Files:**
- Modify: `client/src/components/DetailPanel.svelte`

- [ ] **Step 1: Add files section after Description section**

In `client/src/components/DetailPanel.svelte`, after the Description `</div>` (line 61), add:

```svelte
      <!-- File Patterns -->
      {#if node.files && node.files.length > 0}
        <div class="section">
          <div class="sec-title">Files</div>
          {#each node.files as pattern}
            <div class="file-pattern">{pattern}</div>
          {/each}
        </div>
      {/if}
```

Add CSS at end of `<style>` block:

```css
  .file-pattern { font-size: 11px; font-family: monospace; color: var(--tx-m); padding: 2px 6px; background: var(--bg); border: 1px solid var(--bdr); border-radius: 3px; margin-bottom: 3px; }
```

- [ ] **Step 2: Build client**

Run: `cd /Users/mark/Developer/code-canvas-plugin && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Commit**

```bash
git add client/src/components/DetailPanel.svelte
git commit -m "feat: display file patterns in detail panel"
```

---

### Task 7: hooks.json + Hook Scripts

**Files:**
- Create: `hooks/hooks.json`
- Create: `hooks/session-start.js`
- Create: `hooks/pre-tool-use.js`
- Create: `hooks/post-tool-use.js`
- Create: `hooks/stop.js`

- [ ] **Step 1: Create hooks.json**

Create `hooks/hooks.json`:

```json
{
  "description": "Code Canvas plugin hooks — context injection, file tracking, server lifecycle",
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|clear|compact",
        "hooks": [{
          "type": "command",
          "command": "node \"${CLAUDE_PLUGIN_ROOT}/hooks/session-start.js\"",
          "async": false,
          "timeout": 15
        }]
      }
    ],
    "PostCompact": [
      {
        "matcher": "",
        "hooks": [{
          "type": "command",
          "command": "node \"${CLAUDE_PLUGIN_ROOT}/hooks/session-start.js\"",
          "async": false,
          "timeout": 15
        }]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "EnterPlanMode",
        "hooks": [{
          "type": "command",
          "command": "node \"${CLAUDE_PLUGIN_ROOT}/hooks/pre-tool-use.js\"",
          "async": false,
          "timeout": 5
        }]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [{
          "type": "command",
          "command": "node \"${CLAUDE_PLUGIN_ROOT}/hooks/post-tool-use.js\"",
          "async": true,
          "timeout": 10
        }]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [{
          "type": "command",
          "command": "node \"${CLAUDE_PLUGIN_ROOT}/hooks/stop.js\"",
          "async": true,
          "timeout": 5
        }]
      }
    ]
  }
}
```

- [ ] **Step 2: Create session-start.js**

Create `hooks/session-start.js`:

```js
#!/usr/bin/env node
import { findProjectDir, readEvents, replayState, generateL0, ensureServer } from './lib/canvas-client.js';

const pluginRoot = process.env.CLAUDE_PLUGIN_ROOT || new URL('..', import.meta.url).pathname;

async function main() {
  const projectDir = findProjectDir();
  if (!projectDir) { process.stdout.write('{}'); return; }

  const events = readEvents(projectDir);
  const state = replayState(events);
  const l0 = generateL0(state);

  let serverUrl = '';
  try {
    const url = await ensureServer(projectDir, pluginRoot);
    serverUrl = url || '(server failed to start \u2014 run `npm start` in plugin dir to diagnose)';
  } catch {
    serverUrl = '(server failed to start)';
  }

  const context = `## Code Canvas Active\n\n${l0}\n\n### Commands\n- \`/canvas\` \u2014 Open canvas in browser\n- \`/canvas generate\` \u2014 Generate canvas from spec/codebase\n- \`/canvas update\` \u2014 Sync canvas with implementation progress\n- \`/canvas diff [since]\` \u2014 Show changes since timestamp\n- \`/canvas comments\` \u2014 List unresolved comments\n- \`/canvas story\` \u2014 Decision history narrative\n- \`/canvas export md\` \u2014 Export as markdown\n\n### API\nServer: ${serverUrl}\nPOST /api/events \u2014 append event (JSON body with {type, actor, data})\nPOST /api/events/batch \u2014 append multiple events (JSON array)\nGET /api/events \u2014 fetch all events\nGET /api/state \u2014 current state (?level=L0|L1)\n\n### Proactive Canvas Maintenance\nAfter completing significant work, update the canvas:\n- Change node statuses to reflect progress\n- Record decisions with alternatives and reasoning (decision.recorded events)\n- Update file patterns when creating/restructuring files\n- Add comments noting deviations from the plan`;

  process.stdout.write(JSON.stringify({
    hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: context },
  }));
}

main().catch(() => { process.stdout.write('{}'); });
```

- [ ] **Step 3: Create pre-tool-use.js**

Create `hooks/pre-tool-use.js`:

```js
#!/usr/bin/env node
import { findProjectDir, readEvents, replayState, generateL1 } from './lib/canvas-client.js';

function main() {
  const projectDir = findProjectDir();
  if (!projectDir) { process.stdout.write('{}'); return; }

  const events = readEvents(projectDir);
  const state = replayState(events);

  let context;
  if (state.nodes.size > 0) {
    const l1 = generateL1(state);
    context = `## Design Canvas \u2014 Current Structure\n\n${l1}\n\nReview this structure before planning. Use \`/canvas\` to open in browser.`;
  } else {
    context = 'This project has a design canvas but it\'s empty. Use `/canvas generate` to populate it from a spec or codebase analysis.';
  }

  process.stdout.write(JSON.stringify({
    hookSpecificOutput: { hookEventName: 'PreToolUse', additionalContext: context },
  }));
}

try { main(); } catch { process.stdout.write('{}'); }
```

- [ ] **Step 4: Create post-tool-use.js**

Create `hooks/post-tool-use.js`:

```js
#!/usr/bin/env node
import { findProjectDir, readEvents, replayState, findNodesForFile, ensureServer, postEvent } from './lib/canvas-client.js';

const pluginRoot = process.env.CLAUDE_PLUGIN_ROOT || new URL('..', import.meta.url).pathname;

async function main() {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;

  let toolResult;
  try { toolResult = JSON.parse(input); } catch { return; }

  const filePath = toolResult?.tool_input?.file_path
    || toolResult?.tool_input?.path
    || toolResult?.file_path
    || null;
  if (!filePath) return;

  const projectDir = findProjectDir();
  if (!projectDir) return;

  const events = readEvents(projectDir);
  const state = replayState(events);

  const relative = filePath.startsWith(projectDir)
    ? filePath.slice(projectDir.length + 1)
    : filePath;

  const matchingNodes = findNodesForFile(relative, state.nodes);
  if (matchingNodes.length === 0) return;

  const toUpdate = matchingNodes.filter(id => {
    const node = state.nodes.get(id);
    return node && node.status === 'planned';
  });
  if (toUpdate.length === 0) return;

  const serverUrl = await ensureServer(projectDir, pluginRoot);
  if (!serverUrl) return;

  for (const nodeId of toUpdate) {
    await postEvent(serverUrl, {
      type: 'node.status',
      actor: 'system',
      data: { nodeId, status: 'in-progress', prev: 'planned' },
    });
  }
}

main().catch(() => {});
```

- [ ] **Step 5: Create stop.js**

Create `hooks/stop.js`:

```js
#!/usr/bin/env node
import { findProjectDir, stopServer } from './lib/canvas-client.js';

function main() {
  const projectDir = findProjectDir();
  if (!projectDir) return;
  stopServer(projectDir);
}

try { main(); } catch {}
```

- [ ] **Step 6: Test session-start.js manually**

Run: `cd /Users/mark/Developer/code-canvas-plugin && CLAUDE_PLUGIN_ROOT=$(pwd) node hooks/session-start.js`
Expected: JSON output with `hookSpecificOutput.additionalContext` containing L0 summary

- [ ] **Step 7: Test pre-tool-use.js manually**

Run: `cd /Users/mark/Developer/code-canvas-plugin && node hooks/pre-tool-use.js`
Expected: JSON output with L1 structure

- [ ] **Step 8: Commit**

```bash
git add hooks/hooks.json hooks/session-start.js hooks/pre-tool-use.js hooks/post-tool-use.js hooks/stop.js
git commit -m "feat: all hook scripts — session-start, pre-tool-use, post-tool-use, stop"
```

---

### Task 8: SKILL.md + plugin.json Update

**Files:**
- Create: `skills/canvas/SKILL.md`
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1: Create skills directory and SKILL.md**

```bash
mkdir -p skills/canvas
```

Create `skills/canvas/SKILL.md`:

```markdown
---
name: canvas
description: Use when the user asks to create, view, update, or interact with a design canvas, or when working on architecture/design tasks in a project with .code-canvas/
user-invocable: true
---

# Code Canvas

Visual design knowledge graph. Maps architecture, flows, pipelines, and decisions as an interactive node-and-edge diagram in the browser. Event-sourced — every change is an immutable event in `.code-canvas/events.jsonl`.

## Commands

| Command | Behavior |
|---------|----------|
| `/canvas` | Open canvas in browser (auto-start server if needed) |
| `/canvas generate` | Read spec/codebase, POST node/edge/view events to build canvas |
| `/canvas update` | Compare canvas state to codebase, update node statuses |
| `/canvas diff [since]` | Read events after ISO timestamp, summarize what changed |
| `/canvas comments` | List unresolved comments with targets |
| `/canvas story` | Narrate decision history from `decision.recorded` events |
| `/canvas export md` | Generate markdown summary of current state |

## Event Schema

All events use envelope: `{ id, ts, type, actor, data }`

| Type | Data fields |
|------|-------------|
| `node.created` | `nodeId, label, subtitle, parent, depth, category, confidence, status, files[]` |
| `node.updated` | `nodeId, changes: { ...changed fields }` |
| `node.deleted` | `nodeId` |
| `node.status` | `nodeId, status, prev` |
| `edge.created` | `edgeId, from, to, label, edgeType, color` |
| `edge.updated` | `edgeId, changes: { ...changed fields }` |
| `edge.deleted` | `edgeId` |
| `decision.recorded` | `nodeId, type (decision\|workaround), chosen, alternatives[], reason` |
| `comment.added` | `commentId, target, targetLabel, text, actor` |
| `comment.resolved` | `commentId` |
| `comment.reopened` | `commentId` |
| `comment.deleted` | `commentId` |
| `view.created` | `viewId, name, description, tabNodes[], tabConnections[]` |
| `view.updated` | `viewId, changes: { ...changed fields }` |

## Node Model

- **depth:** `system | domain | module | interface`
- **status:** `done | in-progress | planned | placeholder`
- **confidence:** `0-3`
- **files:** Glob patterns for file-to-node tracking (e.g., `["src/lib/events.*", "server/index.js"]`)
- **category:** User-defined grouping (e.g., `"arch"`, `"flow"`, `"data"`)

## API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/events` | GET | Fetch all events |
| `/api/events` | POST | Append single event |
| `/api/events/batch` | POST | Append multiple events (JSON array) |
| `/api/state` | GET | Current replayed state (?level=L0\|L1) |
| `/api/layouts/:viewId` | GET/PUT | Node positions per view |
| `/api/health` | GET | Server health |

## Guidelines

- Use `actor: "claude"` when posting events
- Generate meaningful IDs: `n_<slug>`, `e_<from>_<to>`, `v_<slug>`
- When generating from a spec, create at least one view/tab with positioned `tabNodes` (row/col grid) and `tabConnections`
- Populate `files` patterns on nodes when the file mapping is clear
- Prefer updating existing nodes over creating duplicates
- After completing significant work, proactively update the canvas: change node statuses, record decisions with `decision.recorded`, update file patterns, add comments noting deviations
- When making or recommending a design/architecture decision, record it on the canvas with alternatives and reasoning
```

- [ ] **Step 2: Update plugin.json**

Replace `.claude-plugin/plugin.json`:

```json
{
  "name": "code-canvas",
  "description": "Interactive visual design knowledge graph for software architecture. Generates canvases from specs, tracks decisions, captures comments, and keeps Claude informed of architectural state.",
  "version": "0.2.0",
  "author": {
    "name": "lilolabs",
    "email": "mark@lilolabs.com"
  },
  "license": "MIT",
  "keywords": ["architecture", "canvas", "design", "knowledge-graph", "visual"],
  "skills": "./skills/canvas"
}
```

- [ ] **Step 3: Commit**

```bash
git add skills/canvas/SKILL.md .claude-plugin/plugin.json
git commit -m "feat: SKILL.md for /canvas commands + plugin.json version bump"
```

---

### Task 9: Vitest Workspace Config

**Files:**
- Create: `vitest.workspace.js`
- Modify: `package.json` (root)

- [ ] **Step 1: Create vitest workspace**

Create `vitest.workspace.js`:

```js
import { defineWorkspace } from 'vitest/config';

export default defineWorkspace([
  'client',
  {
    test: {
      include: ['hooks/lib/**/*.test.js'],
      name: 'hooks',
    },
  },
  {
    test: {
      include: ['server/**/*.test.js'],
      name: 'server',
    },
  },
]);
```

- [ ] **Step 2: Install vitest at root and add test scripts**

Run: `cd /Users/mark/Developer/code-canvas-plugin && npm install -D vitest`

Add to root `package.json` scripts:
```json
"test": "vitest run",
"test:watch": "vitest"
```

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/mark/Developer/code-canvas-plugin && npx vitest run`
Expected: All tests pass across hooks, client, and server workspaces

- [ ] **Step 4: Commit**

```bash
git add vitest.workspace.js package.json package-lock.json
git commit -m "feat: vitest workspace for hooks + server + client test suites"
```

---

### Task 10: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/mark/Developer/code-canvas-plugin && npx vitest run`
Expected: All tests pass

- [ ] **Step 2: Build client**

Run: `cd /Users/mark/Developer/code-canvas-plugin && npm run build`
Expected: Build succeeds

- [ ] **Step 3: Verify file structure**

Run:
```bash
ls hooks/ hooks/lib/ skills/canvas/
cat .claude-plugin/plugin.json
```

Expected output shows all new files exist and plugin.json has version 0.2.0 with skills pointer.

- [ ] **Step 4: Smoke test session-start hook**

Run: `cd /Users/mark/Developer/code-canvas-plugin && CLAUDE_PLUGIN_ROOT=$(pwd) node hooks/session-start.js | python3 -m json.tool`
Expected: Pretty-printed JSON with L0 context, commands, and API reference
