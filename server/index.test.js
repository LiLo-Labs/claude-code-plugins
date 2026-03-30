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
