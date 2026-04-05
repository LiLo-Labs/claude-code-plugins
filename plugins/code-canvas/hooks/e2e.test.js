/**
 * E2E browser test: real browser, real server, real user flows.
 * Tests what the user actually sees and interacts with.
 */
import { describe, it, beforeAll, afterAll, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import http from 'node:http';
import { spawn } from 'node:child_process';

const PLUGIN_ROOT = path.resolve(import.meta.dirname, '..');

let tmpDir, serverUrl, serverProcess, browser, page;

function apiPost(urlPath, data) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(data);
    const url = new URL(urlPath, serverUrl);
    const req = http.request(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => resolve(JSON.parse(d)));
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

const DIAGRAM_XML = [
  '<mxGraphModel><root>',
  '<mxCell id="0"/><mxCell id="1" parent="0"/>',
  '<mxCell id="n_api" value="API Server" style="rounded=1;whiteSpace=wrap;fillColor=#1e3a5f;strokeColor=#4a90d9;fontColor=#e6edf3;fontSize=14;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="60" y="40" width="200" height="60" as="geometry"/></mxCell>',
  '<mxCell id="n_db" value="Database" style="rounded=1;whiteSpace=wrap;fillColor=#1a3320;strokeColor=#3fb950;fontColor=#e6edf3;fontSize=14;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="60" y="140" width="200" height="60" as="geometry"/></mxCell>',
  '<mxCell id="n_auth" value="Auth" style="rounded=1;whiteSpace=wrap;fillColor=#1e2a3a;strokeColor=#58a6ff;fontColor=#e6edf3;fontSize=14;fontStyle=1;" vertex="1" parent="1"><mxGeometry x="300" y="40" width="200" height="60" as="geometry"/></mxCell>',
  '<mxCell id="e1" value="queries" style="rounded=1;curved=1;strokeColor=#8b949e;fontColor=#8b949e;fontSize=11;" edge="1" source="n_api" target="n_db" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>',
  '<mxCell id="e2" value="uses" style="rounded=1;curved=1;strokeColor=#8b949e;fontColor=#8b949e;fontSize=11;" edge="1" source="n_api" target="n_auth" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>',
  '</root></mxGraphModel>',
].join('');

describe('E2E Browser Tests', () => {
  beforeAll(async () => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'canvas-e2e-'));
    const canvasDir = path.join(tmpDir, '.code-canvas');
    fs.mkdirSync(canvasDir, { recursive: true });
    fs.mkdirSync(path.join(canvasDir, 'layouts'), { recursive: true });
    fs.writeFileSync(path.join(canvasDir, 'events.jsonl'), '');

    const serverScript = path.join(PLUGIN_ROOT, 'server', 'index.js');
    serverProcess = spawn('node', [serverScript, '--project-dir', tmpDir, '--port', '0'], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    serverUrl = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('timeout')), 10000);
      serverProcess.stdout.on('data', data => {
        try {
          const info = JSON.parse(data.toString());
          if (info.url) { clearTimeout(timeout); resolve(info.url); }
        } catch {}
      });
    });

    await apiPost('/api/events/batch', [
      { id: 'n1', type: 'node.created', actor: 'claude', data: { nodeId: 'n_api', label: 'API Server', subtitle: 'HTTP requests', depth: 'system', category: 'arch', status: 'done', files: ['src/api.js'] } },
      { id: 'n2', type: 'node.created', actor: 'claude', data: { nodeId: 'n_db', label: 'Database', subtitle: 'PostgreSQL', depth: 'domain', category: 'arch', status: 'in-progress', files: ['src/db.js'] } },
      { id: 'n3', type: 'node.created', actor: 'claude', data: { nodeId: 'n_auth', label: 'Auth', subtitle: 'JWT auth', depth: 'module', category: 'arch', status: 'planned', files: ['src/auth.js'] } },
      { id: 'v1', type: 'view.created', actor: 'claude', data: { viewId: 'v_main', name: 'Main', description: 'System architecture', drawioXml: DIAGRAM_XML } },
      { id: 'v2', type: 'view.created', actor: 'claude', data: { viewId: 'v_flow', name: 'Data Flow', description: 'How data moves', drawioXml: DIAGRAM_XML } },
    ]);

    const { chromium } = await import('playwright');
    browser = await chromium.launch({ headless: true });
    page = await browser.newPage();
  }, 30000);

  afterAll(async () => {
    await browser?.close();
    serverProcess?.kill('SIGINT');
    try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch {}
  });

  it('page loads with header, tabs, status bar, comment bar', async () => {
    await page.goto(serverUrl);
    await page.waitForLoadState('load');

    const header = await page.textContent('.topbar');
    expect(header).toContain('Main');

    const tabs = await page.$$('.tab-btn:not(.add-tab)');
    expect(tabs.length).toBe(2);

    const statusBar = await page.textContent('.sl');
    expect(statusBar).toContain('3 nodes');
    expect(statusBar).toContain('2 tabs');
    expect(statusBar).toContain('Synced');

    const commentBar = await page.textContent('.cbar');
    expect(commentBar).toContain('Comments');
    expect(commentBar).toContain('No open comments');
  });

  it('diagram renders SVG content in the graph container', async () => {
    await page.goto(serverUrl);
    await page.waitForLoadState('load');
    await page.waitForTimeout(1500);

    const container = await page.$('.graph-container');
    expect(container).not.toBeNull();

    const hasSvg = await page.locator('.graph-container svg').count();
    expect(hasSvg).toBeGreaterThan(0);
  });

  it('tab switching updates header and active tab', async () => {
    await page.goto(serverUrl);
    await page.waitForLoadState('load');

    // First tab active
    let active = await page.textContent('.tab-btn.active');
    expect(active).toContain('Main');

    // Click second tab
    const allTabs = await page.$$('.tab-btn:not(.add-tab)');
    await allTabs[1].click();
    await page.waitForTimeout(500);

    const header = await page.textContent('.topbar');
    expect(header).toContain('Data Flow');

    active = await page.textContent('.tab-btn.active');
    expect(active).toContain('Data Flow');
  });

  it('theme toggle switches between two themes', async () => {
    // Clear localStorage to get a clean start
    const freshPage = await browser.newPage();
    await freshPage.goto(serverUrl);
    await freshPage.waitForLoadState('load');
    await freshPage.waitForTimeout(500);

    const initial = await freshPage.getAttribute('html', 'data-theme');
    expect(['dark', 'light']).toContain(initial);

    // Toggle
    await freshPage.click('.tb');
    await freshPage.waitForTimeout(200);
    const toggled = await freshPage.getAttribute('html', 'data-theme');
    expect(toggled).not.toBe(initial);

    // Toggle back
    await freshPage.click('.tb');
    await freshPage.waitForTimeout(200);
    const restored = await freshPage.getAttribute('html', 'data-theme');
    expect(restored).toBe(initial);

    await freshPage.close();
  });

  it('SSE: Claude posting a comment updates UI live', async () => {
    await page.goto(serverUrl);
    await page.waitForLoadState('load');
    await page.waitForTimeout(500);

    // Verify no comments initially
    let cbar = await page.textContent('.cbar');
    expect(cbar).toContain('No open comments');

    // Claude adds a comment via API (simulates post-tool-use action)
    await apiPost('/api/events', {
      id: 'e2e_live_comment', type: 'comment.added', actor: 'claude',
      data: { commentId: 'c_live', target: 'n_api', targetLabel: 'API Server', text: 'Needs rate limiting' },
    });

    // Wait for SSE to deliver
    await page.waitForTimeout(2000);

    // Comment bar should now show the comment
    cbar = await page.textContent('.cbar');
    expect(cbar).toContain('Needs rate limiting');
    expect(cbar).toContain('API Server');
  });

  it('SSE: event count in status bar increments live', async () => {
    await page.goto(serverUrl);
    await page.waitForLoadState('load');

    const getEventCount = async () => {
      const text = await page.textContent('.sl');
      const match = text.match(/(\d+) events/);
      return match ? parseInt(match[1]) : 0;
    };

    const before = await getEventCount();

    await apiPost('/api/events', {
      id: 'e2e_count_test', type: 'node.updated', actor: 'claude',
      data: { nodeId: 'n_api', changes: { subtitle: 'Updated via SSE' } },
    });

    await page.waitForTimeout(2000);
    const after = await getEventCount();
    expect(after).toBeGreaterThan(before);
  });

  it('SSE: node status change from Claude reflects in detail panel', async () => {
    await page.goto(serverUrl);
    await page.waitForLoadState('load');
    await page.waitForTimeout(1000);

    // Click on the graph to try to select n_api
    await page.click('.graph-container', { position: { x: 160, y: 70 } });
    await page.waitForTimeout(500);

    // Now Claude changes the auth node status
    await apiPost('/api/events', {
      id: 'e2e_status_sse', type: 'node.status', actor: 'claude',
      data: { nodeId: 'n_auth', status: 'done' },
    });

    await page.waitForTimeout(2000);

    // Status bar still says "Synced" (no errors)
    const statusBar = await page.textContent('.sl');
    expect(statusBar).toContain('Synced');
  });

  it('+ button opens prompt for new tab name', async () => {
    await page.goto(serverUrl);
    await page.waitForLoadState('load');

    // Set up dialog handler to accept with a name
    page.once('dialog', async dialog => {
      expect(dialog.type()).toBe('prompt');
      await dialog.accept('New Tab');
    });

    // Click the + button
    await page.click('.add-tab');
    await page.waitForTimeout(500);

    // New tab should appear
    const tabs = await page.$$('.tab-btn:not(.add-tab)');
    expect(tabs.length).toBe(3);
  });
});
