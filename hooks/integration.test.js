/**
 * Integration test for the full code-canvas hook lifecycle.
 *
 * Simulates a real Claude Code session:
 * 1. Create a test project with source files
 * 2. Boot the canvas server
 * 3. Generate canvas (nodes + views)
 * 4. Fire hooks as Claude Code would and verify outputs
 *
 * Tests cover:
 * - session-start: context injection with/without canvas
 * - post-tool-use: tracked file edit, untracked file creation, non-source skip
 * - pre-tool-use: detecting user-made changes (comments, status)
 * - stop: in-progress nodes, untracked files, unresolved comments
 * - auto status transitions: planned → in-progress on file edit
 * - full lifecycle: create project → generate canvas → add feature → verify updates
 */
import { describe, it, beforeAll, afterAll, beforeEach } from 'vitest';
import { expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { execFileSync, spawn } from 'node:child_process';
import http from 'node:http';

const PLUGIN_ROOT = path.resolve(import.meta.dirname, '..');
const HOOKS_DIR = path.join(PLUGIN_ROOT, 'hooks');

let tmpDir;
let serverUrl;
let serverProcess;

// Helper: run a hook script with stdin input and return stdout
function runHook(hookName, stdinData = '', env = {}) {
  const script = path.join(HOOKS_DIR, `${hookName}.js`);
  try {
    const result = execFileSync('node', [script], {
      input: stdinData,
      cwd: tmpDir,
      env: {
        ...process.env,
        CLAUDE_PLUGIN_ROOT: PLUGIN_ROOT,
        HOME: os.homedir(),
        PATH: process.env.PATH,
        ...env,
      },
      timeout: 10000,
      encoding: 'utf-8',
    });
    if (!result.trim()) return null;
    return JSON.parse(result);
  } catch (e) {
    // Hook may exit 0 with no output, or throw
    if (e.stdout && e.stdout.trim()) {
      try { return JSON.parse(e.stdout); } catch { return null; }
    }
    return null;
  }
}

// Helper: post events to canvas server
function postEvents(events) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(events);
    const url = new URL('/api/events/batch', serverUrl);
    const req = http.request(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => resolve(JSON.parse(data)));
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

function postEvent(event) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(event);
    const url = new URL('/api/events', serverUrl);
    const req = http.request(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) },
    }, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => resolve(JSON.parse(data)));
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

function getState() {
  return new Promise((resolve, reject) => {
    http.get(`${serverUrl}/api/state`, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => resolve(JSON.parse(data)));
    }).on('error', reject);
  });
}

describe('Hook Integration Tests', () => {
  beforeAll(async () => {
    // Create a test project
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'canvas-integration-'));

    // Create source files for a small app
    fs.mkdirSync(path.join(tmpDir, 'src'), { recursive: true });
    fs.writeFileSync(path.join(tmpDir, 'src', 'app.js'), 'export function start() { console.log("app"); }\n');
    fs.writeFileSync(path.join(tmpDir, 'src', 'db.js'), 'export class Database { connect() {} }\n');
    fs.writeFileSync(path.join(tmpDir, 'src', 'routes.js'), 'export function setup(app) {}\n');
    fs.writeFileSync(path.join(tmpDir, 'package.json'), '{"name":"test-app","type":"module"}\n');

    // Initialize .code-canvas
    const canvasDir = path.join(tmpDir, '.code-canvas');
    fs.mkdirSync(canvasDir, { recursive: true });
    fs.mkdirSync(path.join(canvasDir, 'layouts'), { recursive: true });
    fs.writeFileSync(path.join(canvasDir, 'events.jsonl'), '');

    // Start the canvas server
    const serverScript = path.join(PLUGIN_ROOT, 'server', 'index.js');
    serverProcess = spawn('node', [serverScript, '--project-dir', tmpDir, '--port', '0'], {
      stdio: ['pipe', 'pipe', 'pipe'],
    });

    serverUrl = await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Server startup timed out')), 10000);
      serverProcess.stdout.on('data', data => {
        try {
          const info = JSON.parse(data.toString());
          if (info.url) { clearTimeout(timeout); resolve(info.url); }
        } catch {}
      });
    });
  }, 15000);

  afterAll(() => {
    serverProcess?.kill('SIGINT');
    try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch {}
  });

  // ── Session Start Tests ──

  describe('session-start hook', () => {
    it('shows "Canvas Available" when no canvas data exists', () => {
      // Canvas dir exists but is empty
      const result = runHook('session-start');
      expect(result).not.toBeNull();
      const ctx = result.hookSpecificOutput.additionalContext;
      // Empty canvas → should suggest /canvas generate
      expect(ctx).toContain('/canvas generate');
    });

    it('shows full context after canvas is populated', async () => {
      // Seed some data
      await postEvents([
        { id: 'ev_1', type: 'node.created', actor: 'claude', data: { nodeId: 'n_app', label: 'App', status: 'done', files: ['src/app.js'], depth: 'system', category: 'arch' } },
        { id: 'ev_2', type: 'node.created', actor: 'claude', data: { nodeId: 'n_db', label: 'Database', status: 'planned', files: ['src/db.js'], depth: 'module', category: 'arch' } },
        { id: 'ev_3', type: 'node.created', actor: 'claude', data: { nodeId: 'n_routes', label: 'Routes', status: 'planned', files: ['src/routes.js'], depth: 'module', category: 'arch' } },
        { id: 'ev_v1', type: 'view.created', actor: 'claude', data: { viewId: 'v_arch', name: 'Architecture', description: 'System overview' } },
      ]);

      const result = runHook('session-start');
      expect(result).not.toBeNull();
      const ctx = result.hookSpecificOutput.additionalContext;
      expect(ctx).toContain('Code Canvas Active');
      expect(ctx).toContain('Nodes: 3');
      expect(ctx).toContain('Architecture');
      expect(ctx).toContain('untracked file');  // The IMPORTANT instruction
    });
  });

  // ── Post Tool Use Tests ──

  describe('post-tool-use hook', () => {
    it('reports matched nodes when editing a tracked file', () => {
      const result = runHook('post-tool-use', JSON.stringify({
        tool_input: { file_path: path.join(tmpDir, 'src', 'app.js') },
      }));
      expect(result).not.toBeNull();
      const ctx = result.hookSpecificOutput.additionalContext;
      expect(ctx).toContain('App');
      expect(ctx).toContain('n_app');
    });

    it('auto-transitions planned → in-progress on tracked file edit', async () => {
      // Edit a file tracked by a planned node
      const result = runHook('post-tool-use', JSON.stringify({
        tool_input: { file_path: path.join(tmpDir, 'src', 'db.js') },
      }));
      expect(result).not.toBeNull();
      const ctx = result.hookSpecificOutput.additionalContext;
      expect(ctx).toContain('in-progress');

      // Verify the server state was updated
      const state = await getState();
      expect(state.nodes.n_db.status).toBe('in-progress');
    });

    it('detects untracked files and instructs Claude to create a node', () => {
      // Create a new file that no node tracks
      fs.writeFileSync(path.join(tmpDir, 'src', 'auth.js'), 'export function login() {}\n');

      const result = runHook('post-tool-use', JSON.stringify({
        tool_input: { file_path: path.join(tmpDir, 'src', 'auth.js') },
      }));
      expect(result).not.toBeNull();
      const ctx = result.hookSpecificOutput.additionalContext;
      expect(ctx).toContain('untracked file');
      expect(ctx).toContain('src/auth.js');
      expect(ctx).toContain('ACTION REQUIRED');
      expect(ctx).toContain('node.created');
    });

    it('skips .code-canvas/ files silently', () => {
      const result = runHook('post-tool-use', JSON.stringify({
        tool_input: { file_path: path.join(tmpDir, '.code-canvas', 'events.jsonl') },
      }));
      expect(result).toBeNull();
    });

    it('skips node_modules/ files silently', () => {
      const result = runHook('post-tool-use', JSON.stringify({
        tool_input: { file_path: path.join(tmpDir, 'node_modules', 'foo', 'index.js') },
      }));
      expect(result).toBeNull();
    });

    it('surfaces unresolved user comments', async () => {
      await postEvent({
        id: 'ev_c1', type: 'comment.added', actor: 'user',
        data: { commentId: 'c_1', target: 'n_app', targetLabel: 'App', text: 'Add error handling' },
      });

      const result = runHook('post-tool-use', JSON.stringify({
        tool_input: { file_path: path.join(tmpDir, 'src', 'app.js') },
      }));
      expect(result).not.toBeNull();
      const ctx = result.hookSpecificOutput.additionalContext;
      expect(ctx).toContain('Add error handling');
      expect(ctx).toContain('App');
    });
  });

  // ── Pre Tool Use Tests ──

  describe('pre-tool-use hook', () => {
    it('reports no changes when nothing happened since last seen', () => {
      // First call sets the marker
      runHook('pre-tool-use', '{}');
      // Second call should see no new events
      const result = runHook('pre-tool-use', '{}');
      // No new user events → empty output or empty object
      const hasContext = result?.hookSpecificOutput?.additionalContext;
      expect(hasContext).toBeFalsy();
    });

    it('detects user comments added via the canvas UI', async () => {
      // Reset marker
      const markerFile = path.join(tmpDir, '.code-canvas', '.claude-last-seen');
      const events = JSON.parse(fs.readFileSync(path.join(tmpDir, '.code-canvas', 'events.jsonl'), 'utf-8').trim().split('\n').map(l => l).join(',').replace(/^/, '[').replace(/$/, ']'));
      fs.writeFileSync(markerFile, String(events.length));

      // User adds a comment
      await postEvent({
        id: 'ev_c2', type: 'comment.added', actor: 'user',
        data: { commentId: 'c_2', target: 'n_routes', targetLabel: 'Routes', text: 'Need auth middleware' },
      });

      const result = runHook('pre-tool-use', '{}');
      expect(result).not.toBeNull();
      const ctx = result.hookSpecificOutput.additionalContext;
      expect(ctx).toContain('Canvas Changes');
      expect(ctx).toContain('Need auth middleware');
      expect(ctx).toContain('Routes');
    });

    it('detects user status changes from the canvas UI', async () => {
      // Reset marker
      const eventsContent = fs.readFileSync(path.join(tmpDir, '.code-canvas', 'events.jsonl'), 'utf-8').trim();
      const count = eventsContent.split('\n').filter(l => l.trim()).length;
      fs.writeFileSync(path.join(tmpDir, '.code-canvas', '.claude-last-seen'), String(count));

      // User changes status via context menu
      await postEvent({
        id: 'ev_s1', type: 'node.status', actor: 'user',
        data: { nodeId: 'n_routes', status: 'done', prev: 'planned' },
      });

      const result = runHook('pre-tool-use', '{}');
      expect(result).not.toBeNull();
      const ctx = result.hookSpecificOutput.additionalContext;
      expect(ctx).toContain('Status changes');
      expect(ctx).toContain('n_routes');
    });
  });

  // ── Stop Hook Tests ──

  describe('stop hook', () => {
    it('reports in-progress nodes', async () => {
      // Ensure at least one node is in-progress
      await postEvent({
        id: 'ev_ip1', type: 'node.status', actor: 'system',
        data: { nodeId: 'n_db', status: 'in-progress', prev: 'planned' },
      });

      const result = runHook('stop');
      expect(result).not.toBeNull();
      const ctx = result.hookSpecificOutput.additionalContext;
      expect(ctx).toContain('in-progress');
      expect(ctx).toContain('Database');
    });

    it('reports untracked source files', () => {
      const result = runHook('stop');
      expect(result).not.toBeNull();
      const ctx = result.hookSpecificOutput.additionalContext;
      expect(ctx).toContain('not tracked');
      expect(ctx).toContain('src/auth.js');
    });

    it('reports unresolved comments', () => {
      const result = runHook('stop');
      expect(result).not.toBeNull();
      const ctx = result.hookSpecificOutput.additionalContext;
      expect(ctx).toContain('unresolved comment');
    });
  });

  // ── Full Lifecycle Test ──

  describe('full lifecycle', () => {
    it('tracks a complete feature addition workflow', async () => {
      // 1. Verify initial state
      const state1 = await getState();
      expect(Object.keys(state1.nodes)).toHaveLength(3);

      // 2. Simulate Claude creating a new file (auth.js already exists from earlier test)
      // The post-tool-use hook should flag it as untracked
      const hookResult = runHook('post-tool-use', JSON.stringify({
        tool_input: { file_path: path.join(tmpDir, 'src', 'auth.js') },
      }));
      expect(hookResult.hookSpecificOutput.additionalContext).toContain('ACTION REQUIRED');

      // 3. Claude follows the instruction and creates a node
      await postEvent({
        id: 'ev_n4', type: 'node.created', actor: 'claude',
        data: { nodeId: 'n_auth', label: 'Auth', subtitle: 'Authentication module', status: 'in-progress', files: ['src/auth.js'], depth: 'module', category: 'arch' },
      });

      // 4. Verify the file is now tracked
      const hookResult2 = runHook('post-tool-use', JSON.stringify({
        tool_input: { file_path: path.join(tmpDir, 'src', 'auth.js') },
      }));
      const ctx2 = hookResult2.hookSpecificOutput.additionalContext;
      expect(ctx2).toContain('Auth');
      expect(ctx2).not.toContain('untracked');

      // 5. Verify state updated
      const state2 = await getState();
      expect(Object.keys(state2.nodes)).toHaveLength(4);
      expect(state2.nodes.n_auth.label).toBe('Auth');

      // 6. Stop hook should still report auth as in-progress
      const stopResult = runHook('stop');
      const stopCtx = stopResult.hookSpecificOutput.additionalContext;
      expect(stopCtx).toContain('Auth');
      expect(stopCtx).toContain('in-progress');
      // auth.js should no longer be untracked
      expect(stopCtx).not.toContain('src/auth.js');
    });
  });
});
