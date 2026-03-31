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
  const events = [];
  for (const line of content.split('\n')) {
    if (!line.trim()) continue;
    try { events.push(JSON.parse(line)); }
    catch { /* skip malformed lines */ }
  }
  return events;
}

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
      case 'view.created': views.push({ id: d.viewId, name: d.name, description: d.description || '', rendering: d.rendering || {}, tabNodes: d.tabNodes || [], tabConnections: d.tabConnections || [], drawioXml: d.drawioXml || '', excalidrawElements: d.excalidrawElements || [] }); break;
      case 'view.updated': { const v = views.find(v => v.id === d.viewId); if (v) Object.assign(v, d.changes || {}); break; }
      case 'view.deleted': { const idx = views.findIndex(v => v.id === d.viewId); if (idx !== -1) views.splice(idx, 1); break; }
    }
  }
  // Clean up orphaned edges (endpoints referencing deleted nodes)
  for (const [edgeId, edge] of edges) {
    if (!nodes.has(edge.from) || !nodes.has(edge.to)) edges.delete(edgeId);
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

let eventCount = readEvents().length; // initialize from file
function appendEvent(event) {
  fs.appendFileSync(eventsFile, JSON.stringify(event) + '\n');
  eventCount++;
}

function sendJSON(res, data, status = 200) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

const MAX_BODY = 1024 * 1024; // 1 MB limit
function readBody(req) {
  return new Promise(resolve => {
    let body = '';
    req.on('data', chunk => {
      body += chunk;
      if (body.length > MAX_BODY) { req.destroy(); resolve(null); }
    });
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

// ── Server (local-only, 127.0.0.1 — no TLS needed) ──
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${host}`);
  const p = url.pathname;

  // CORS — same-origin only (localhost). Static files served from same origin so CORS
  // headers are only needed for dev mode (Vite proxy on different port).
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': 'http://localhost:5173',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    });
    res.end(); return;
  }
  res.setHeader('Access-Control-Allow-Origin', 'http://localhost:5173');

  // GET /api/events
  if (p === '/api/events' && req.method === 'GET') {
    return sendJSON(res, readEvents());
  }

  // POST /api/events
  if (p === '/api/events' && req.method === 'POST') {
    const body = await readBody(req);
    if (!body || !body.type) return sendJSON(res, { error: 'Missing event type' }, 400);
    body.ts = body.ts || new Date().toISOString();
    appendEvent(body);
    return sendJSON(res, { saved: true });
  }

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

  // GET /api/layouts/:viewId
  const layoutMatch = p.match(/^\/api\/layouts\/([a-zA-Z0-9_-]+)$/);
  if (layoutMatch && req.method === 'GET') {
    const file = path.resolve(layoutsDir, layoutMatch[1] + '.json');
    if (!file.startsWith(path.resolve(layoutsDir))) return sendJSON(res, { error: 'Invalid' }, 400);
    if (fs.existsSync(file)) {
      return sendJSON(res, JSON.parse(fs.readFileSync(file, 'utf-8')));
    }
    return sendJSON(res, {});
  }

  // PUT /api/layouts/:viewId
  if (layoutMatch && req.method === 'PUT') {
    const file = path.resolve(layoutsDir, layoutMatch[1] + '.json');
    if (!file.startsWith(path.resolve(layoutsDir))) return sendJSON(res, { error: 'Invalid' }, 400);
    const body = await readBody(req);
    fs.writeFileSync(file, JSON.stringify(body, null, 2));
    return sendJSON(res, { saved: true });
  }

  // GET /api/health — lightweight, no file read
  if (p === '/api/health' && req.method === 'GET') {
    return sendJSON(res, {
      status: 'ok',
      eventCount,
      project: path.basename(path.resolve(projectDir)),
    });
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
