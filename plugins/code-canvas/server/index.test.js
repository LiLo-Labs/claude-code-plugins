import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';

let serverProcess;
let baseUrl;
let tmpDir;

function request(urlPath, options = {}) {
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
    baseUrl = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Server startup timed out')), 10000);
      serverProcess.stdout.on('data', (data) => {
        try {
          const info = JSON.parse(data.toString());
          if (info.url) { clearTimeout(timeout); resolve(info.url); }
        } catch {}
      });
      serverProcess.stderr.on('data', (data) => {
        console.error('Server stderr:', data.toString());
      });
    });
  }, 15000);

  afterAll(() => {
    serverProcess?.kill('SIGINT');
    try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch {}
  });

  it('GET /api/health returns ok', async () => {
    const res = await request('/api/health');
    expect(res.status).toBe(200);
    expect(res.json().status).toBe('ok');
  });

  it('GET /api/events returns empty array initially', async () => {
    const res = await request('/api/events');
    expect(res.json()).toEqual([]);
  });

  it('POST /api/events appends an event', async () => {
    const res = await request('/api/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'node.created', data: { nodeId: 'n1', label: 'Test' } }),
    });
    expect(res.json().saved).toBe(true);
    const events = (await request('/api/events')).json();
    expect(events).toHaveLength(1);
    expect(events[0].data.nodeId).toBe('n1');
  });

  it('POST /api/events/batch appends multiple', async () => {
    const res = await request('/api/events/batch', {
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
    const res = await request('/api/state');
    const body = res.json();
    expect(body.nodes.n1).toBeDefined();
    expect(body.nodes.n1.label).toBe('Test');
  });

  it('GET /api/state?level=L0 returns summary', async () => {
    const res = await request('/api/state?level=L0');
    expect(res.json().summary).toContain('Nodes:');
  });

  it('PUT/GET /api/layouts/:viewId round-trips', async () => {
    await request('/api/layouts/test-view', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ positions: { n1: { x: 10, y: 20 } } }),
    });
    const res = await request('/api/layouts/test-view');
    expect(res.json().positions.n1.x).toBe(10);
  });
});
