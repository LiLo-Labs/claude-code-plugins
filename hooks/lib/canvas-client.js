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
