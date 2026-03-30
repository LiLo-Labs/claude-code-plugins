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
