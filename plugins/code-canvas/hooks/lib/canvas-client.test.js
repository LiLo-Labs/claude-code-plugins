import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {
  readEvents, replayState, generateL0, generateL1,
  findNodesForFile, getServerUrl, findProjectDir,
  findGitRoot, initCanvasDir,
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

describe('initCanvasDir', () => {
  it('creates .code-canvas/ and events.jsonl when missing', () => {
    const bare = fs.mkdtempSync(path.join(os.tmpdir(), 'canvas-bare-'));
    initCanvasDir(bare);
    expect(fs.existsSync(path.join(bare, '.code-canvas'))).toBe(true);
    expect(fs.existsSync(path.join(bare, '.code-canvas', 'events.jsonl'))).toBe(true);
    expect(fs.readFileSync(path.join(bare, '.code-canvas', 'events.jsonl'), 'utf-8')).toBe('');
    fs.rmSync(bare, { recursive: true, force: true });
  });

  it('does not overwrite existing events.jsonl', () => {
    const existing = path.join(tmpDir, '.code-canvas', 'events.jsonl');
    fs.writeFileSync(existing, '{"type":"node.created"}\n');
    initCanvasDir(tmpDir);
    expect(fs.readFileSync(existing, 'utf-8')).toBe('{"type":"node.created"}\n');
  });
});

describe('findGitRoot', () => {
  it('finds .git in parent dir', () => {
    // We're running from code-canvas-plugin which is a git repo
    const root = findGitRoot(path.join(process.cwd(), 'hooks', 'lib'));
    expect(root).toBeTruthy();
    expect(fs.existsSync(path.join(root, '.git'))).toBe(true);
  });

  it('returns null when no .git found', () => {
    const noGit = fs.mkdtempSync(path.join(os.tmpdir(), 'no-git-'));
    expect(findGitRoot(noGit)).toBeNull();
    fs.rmSync(noGit, { recursive: true, force: true });
  });
});
