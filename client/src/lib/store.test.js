import { describe, it, expect } from 'vitest';
import { EventStore, genId } from './store.js';

describe('genId', () => {
  it('generates unique prefixed IDs', () => {
    const a = genId('ev');
    const b = genId('ev');
    expect(a).not.toBe(b);
    expect(a).toMatch(/^ev_/);
  });
});

describe('EventStore', () => {
  it('starts empty', () => {
    const store = new EventStore();
    const state = store.getState();
    expect(state.nodes.size).toBe(0);
    expect(state.edges.size).toBe(0);
    expect(state.comments).toEqual([]);
    expect(state.decisions).toEqual([]);
    expect(state.views).toEqual([]);
  });

  it('creates and updates nodes', () => {
    const store = new EventStore();
    store.apply({ type: 'node.created', data: { nodeId: 'n1', label: 'Auth', status: 'planned' } });
    expect(store.getState().nodes.get('n1').label).toBe('Auth');
    store.apply({ type: 'node.updated', data: { nodeId: 'n1', changes: { label: 'Auth v2' } } });
    expect(store.getState().nodes.get('n1').label).toBe('Auth v2');
  });

  it('deletes nodes and cleans orphaned edges', () => {
    const store = new EventStore();
    store.apply({ type: 'node.created', data: { nodeId: 'n1', label: 'A' } });
    store.apply({ type: 'node.created', data: { nodeId: 'n2', label: 'B' } });
    store.apply({ type: 'edge.created', data: { edgeId: 'e1', from: 'n1', to: 'n2' } });
    expect(store.getState().edges.size).toBe(1);
    store.apply({ type: 'node.deleted', data: { nodeId: 'n1' } });
    expect(store.getState().nodes.size).toBe(1);
    expect(store.getState().edges.size).toBe(0);
  });

  it('handles node.status events', () => {
    const store = new EventStore();
    store.apply({ type: 'node.created', data: { nodeId: 'n1', label: 'X', status: 'planned' } });
    store.apply({ type: 'node.status', data: { nodeId: 'n1', status: 'done' } });
    expect(store.getState().nodes.get('n1').status).toBe('done');
  });

  it('manages edges', () => {
    const store = new EventStore();
    store.apply({ type: 'node.created', data: { nodeId: 'n1', label: 'A' } });
    store.apply({ type: 'node.created', data: { nodeId: 'n2', label: 'B' } });
    store.apply({ type: 'edge.created', data: { edgeId: 'e1', from: 'n1', to: 'n2', label: 'uses' } });
    expect(store.getState().edges.get('e1').label).toBe('uses');
    store.apply({ type: 'edge.updated', data: { edgeId: 'e1', changes: { label: 'depends on' } } });
    expect(store.getState().edges.get('e1').label).toBe('depends on');
    store.apply({ type: 'edge.deleted', data: { edgeId: 'e1' } });
    expect(store.getState().edges.size).toBe(0);
  });

  it('manages comments lifecycle', () => {
    const store = new EventStore();
    store.apply({ type: 'comment.added', actor: 'user', data: { commentId: 'c1', target: 'n1', text: 'Fix this' } });
    expect(store.getUnresolvedComments()).toHaveLength(1);
    store.apply({ type: 'comment.resolved', actor: 'user', data: { commentId: 'c1' } });
    expect(store.getUnresolvedComments()).toHaveLength(0);
    expect(store.getState().comments[0].resolved).toBe(true);
    store.apply({ type: 'comment.reopened', data: { commentId: 'c1' } });
    expect(store.getUnresolvedComments()).toHaveLength(1);
    store.apply({ type: 'comment.deleted', data: { commentId: 'c1' } });
    expect(store.getState().comments).toHaveLength(0);
  });

  it('records decisions', () => {
    const store = new EventStore();
    store.apply({ type: 'node.created', data: { nodeId: 'n1', label: 'DB' } });
    store.apply({ type: 'decision.recorded', actor: 'claude', ts: '2026-01-01', data: { nodeId: 'n1', type: 'decision', chosen: 'Postgres', alternatives: ['MySQL', 'SQLite'], reason: 'Better JSON support' } });
    expect(store.getNodeDecisions('n1')).toHaveLength(1);
    expect(store.getNodeDecisions('n1')[0].chosen).toBe('Postgres');
  });

  it('manages views', () => {
    const store = new EventStore();
    store.apply({ type: 'view.created', data: { viewId: 'v1', name: 'Architecture', drawioXml: '<xml/>' } });
    expect(store.getState().views).toHaveLength(1);
    store.apply({ type: 'view.updated', data: { viewId: 'v1', changes: { name: 'Arch v2' } } });
    expect(store.getState().views[0].name).toBe('Arch v2');
    store.apply({ type: 'view.deleted', data: { viewId: 'v1' } });
    expect(store.getState().views).toHaveLength(0);
  });

  it('computes completeness from children', () => {
    const store = new EventStore();
    store.apply({ type: 'node.created', data: { nodeId: 'parent', label: 'System' } });
    store.apply({ type: 'node.created', data: { nodeId: 'c1', label: 'A', parent: 'parent', status: 'done' } });
    store.apply({ type: 'node.created', data: { nodeId: 'c2', label: 'B', parent: 'parent', status: 'planned' } });
    expect(store.getState().nodes.get('parent').completeness).toBe(0.5);
  });

  it('replays from event array', () => {
    const events = [
      { type: 'node.created', data: { nodeId: 'n1', label: 'Hello' } },
      { type: 'node.created', data: { nodeId: 'n2', label: 'World' } },
    ];
    const store = EventStore.fromEvents(events);
    expect(store.getState().nodes.size).toBe(2);
  });
});
