import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import os from 'node:os';
import { execSync } from 'node:child_process';
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
const drawioDir = path.join(__dirname, '..', 'vendor', 'drawio');

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
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
  '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf',
  '.xml': 'application/xml', '.txt': 'text/plain',
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

  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, PUT, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    });
    res.end(); return;
  }
  res.setHeader('Access-Control-Allow-Origin', '*');

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

  if (p === '/api/events' && req.method === 'GET') return sendJSON(res, readEvents());

  if (p === '/api/events' && req.method === 'POST') {
    const body = await readBody(req);
    if (!body || !body.type) return sendJSON(res, { error: 'Missing event type' }, 400);
    body.ts = body.ts || new Date().toISOString();
    appendEvent(body);
    broadcastEvent(body);
    return sendJSON(res, { saved: true });
  }

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

  // GET/PUT /api/shapes — project-specific custom shapes
  const shapesFile = path.join(canvasDir, 'shapes.json');
  if (p === '/api/shapes' && req.method === 'GET') {
    if (fs.existsSync(shapesFile)) {
      return sendJSON(res, JSON.parse(fs.readFileSync(shapesFile, 'utf-8')));
    }
    return sendJSON(res, {});
  }
  if (p === '/api/shapes' && req.method === 'PUT') {
    const body = await readBody(req);
    if (!body) return sendJSON(res, { error: 'Invalid JSON' }, 400);
    fs.writeFileSync(shapesFile, JSON.stringify(body, null, 2));
    return sendJSON(res, { saved: true });
  }

  // GET/PUT /api/shapes/user — user-level shapes (~/.claude/shapes.json)
  const userShapesFile = path.join(process.env.HOME || os.homedir(), '.claude', 'shapes.json');
  if (p === '/api/shapes/user' && req.method === 'GET') {
    if (fs.existsSync(userShapesFile)) {
      return sendJSON(res, JSON.parse(fs.readFileSync(userShapesFile, 'utf-8')));
    }
    return sendJSON(res, {});
  }
  if (p === '/api/shapes/user' && req.method === 'PUT') {
    const body = await readBody(req);
    if (!body) return sendJSON(res, { error: 'Invalid JSON' }, 400);
    const dir = path.dirname(userShapesFile);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(userShapesFile, JSON.stringify(body, null, 2));
    return sendJSON(res, { saved: true });
  }

  if (p === '/api/health' && req.method === 'GET') {
    return sendJSON(res, { status: 'ok', eventCount, project: path.basename(path.resolve(projectDir)) });
  }

  // Serve draw.io webapp at /drawio/
  if (req.method === 'GET' && p.startsWith('/drawio/')) {
    let subPath = p.slice('/drawio'.length);
    if (!subPath || subPath === '/') subPath = '/index.html';
    const resolved = path.resolve(drawioDir, '.' + subPath);
    if (!resolved.startsWith(path.resolve(drawioDir))) {
      res.writeHead(403); res.end('Forbidden'); return;
    }
    if (fs.existsSync(resolved) && fs.statSync(resolved).isFile()) {
      const ext = path.extname(resolved);
      res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' });
      fs.createReadStream(resolved).pipe(res);
      return;
    }
    res.writeHead(404); res.end('Not found'); return;
  }

  if (req.method === 'GET') {
    if (serveStatic(res, p)) return;
    if (serveStatic(res, '/')) return;
  }

  res.writeHead(404); res.end('Not found');
});

// ── Draw.io vendor check ──
function ensureDrawio() {
  const versionFile = path.join(drawioDir, '.version');
  if (fs.existsSync(versionFile)) return true;
  const script = path.join(__dirname, '..', 'scripts', 'vendor-drawio.sh');
  if (!fs.existsSync(script)) { console.error('vendor-drawio.sh not found'); return false; }
  try {
    console.error('draw.io not found, downloading...');
    execSync(`bash "${script}"`, { stdio: 'inherit' });
    return fs.existsSync(versionFile);
  } catch (e) {
    console.error('Failed to vendor draw.io:', e.message);
    return false;
  }
}

// ── Start ──
async function start() {
  ensureDrawio();
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
