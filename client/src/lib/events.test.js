import { describe, it, expect } from 'vitest';
import { EventStore } from './events.js';

describe('EventStore', () => {
  it('replays node.created events into nodes map', () => {
    const store = new EventStore();
    store.apply({
      id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'node.created', actor: 'claude',
      data: { nodeId: 'n1', label: 'Server', subtitle: 'API layer', parent: null, depth: 'system', category: 'arch', confidence: 3 },
    });
    const state = store.getState();
    expect(state.nodes.get('n1')).toEqual(expect.objectContaining({ id: 'n1', label: 'Server', status: 'planned' }));
  });

  it('applies node.status events', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n1', label: 'Server', subtitle: '', parent: null, depth: 'system', category: 'arch', confidence: 3 } });
    store.apply({ id: 'ev_2', ts: '2026-03-29T00:01:00Z', type: 'node.status', actor: 'user', data: { nodeId: 'n1', status: 'done', prev: 'planned' } });
    expect(store.getState().nodes.get('n1').status).toBe('done');
  });

  it('tracks edges', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'edge.created', actor: 'claude', data: { edgeId: 'e1', from: 'n1', to: 'n2', label: 'calls', edgeType: 'data-flow', color: '#3b82f6' } });
    expect(store.getState().edges.get('e1')).toEqual(expect.objectContaining({ from: 'n1', to: 'n2' }));
  });

  it('tracks decisions with workaround detection', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n1', label: 'Auth', subtitle: '', parent: null, depth: 'domain', category: 'arch', confidence: 2 } });
    store.apply({ id: 'ev_2', ts: '2026-03-29T00:01:00Z', type: 'decision.recorded', actor: 'claude', data: { nodeId: 'n1', type: 'workaround', chosen: 'Skip auth', alternatives: ['JWT'], reason: 'v1 only' } });
    const node = store.getState().nodes.get('n1');
    expect(node.hasWorkaround).toBe(true);
    expect(store.getState().decisions).toHaveLength(1);
  });

  it('tracks comments with resolution', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'comment.added', actor: 'user', data: { commentId: 'c1', target: 'n1', targetLabel: 'Auth', text: 'Need JWT', actor: 'user' } });
    expect(store.getState().comments).toHaveLength(1);
    expect(store.getState().comments[0].resolved).toBe(false);

    store.apply({ id: 'ev_2', ts: '2026-03-29T00:01:00Z', type: 'comment.resolved', actor: 'claude', data: { commentId: 'c1', actor: 'claude' } });
    expect(store.getState().comments[0].resolved).toBe(true);
  });

  it('computes completeness from children statuses', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'p', label: 'Parent', subtitle: '', parent: null, depth: 'system', category: 'arch', confidence: 2 } });
    store.apply({ id: 'ev_2', ts: '2026-03-29T00:00:01Z', type: 'node.created', actor: 'claude', data: { nodeId: 'c1', label: 'Child 1', subtitle: '', parent: 'p', depth: 'domain', category: 'arch', confidence: 3 } });
    store.apply({ id: 'ev_3', ts: '2026-03-29T00:00:02Z', type: 'node.created', actor: 'claude', data: { nodeId: 'c2', label: 'Child 2', subtitle: '', parent: 'p', depth: 'domain', category: 'arch', confidence: 3 } });
    store.apply({ id: 'ev_4', ts: '2026-03-29T00:00:03Z', type: 'node.status', actor: 'user', data: { nodeId: 'c1', status: 'done', prev: 'planned' } });
    expect(store.getState().nodes.get('p').completeness).toBe(0.5);
  });

  it('supports views', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'view.created', actor: 'user', data: { viewId: 'v1', name: 'Architecture', filter: { categories: ['arch'] }, description: '' } });
    expect(store.getState().views).toHaveLength(1);
    expect(store.getState().views[0].name).toBe('Architecture');
  });

  it('loads from array of events', () => {
    const events = [
      { id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n1', label: 'A', subtitle: '', parent: null, depth: 'system', category: 'arch', confidence: 2 } },
      { id: 'ev_2', ts: '2026-03-29T00:00:01Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n2', label: 'B', subtitle: '', parent: 'n1', depth: 'domain', category: 'arch', confidence: 1 } },
    ];
    const store = EventStore.fromEvents(events);
    expect(store.getState().nodes.size).toBe(2);
  });

  it('handles node.updated', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n1', label: 'Old', subtitle: '', parent: null, depth: 'system', category: 'arch', confidence: 1 } });
    store.apply({ id: 'ev_2', ts: '2026-03-29T00:01:00Z', type: 'node.updated', actor: 'user', data: { nodeId: 'n1', changes: { label: 'New', confidence: 3 } } });
    const node = store.getState().nodes.get('n1');
    expect(node.label).toBe('New');
    expect(node.confidence).toBe(3);
  });

  it('handles node.deleted', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'node.created', actor: 'claude', data: { nodeId: 'n1', label: 'A', subtitle: '', parent: null, depth: 'system', category: 'arch', confidence: 2 } });
    store.apply({ id: 'ev_2', ts: '2026-03-29T00:01:00Z', type: 'node.deleted', actor: 'user', data: { nodeId: 'n1' } });
    expect(store.getState().nodes.size).toBe(0);
  });

  it('handles comment.reopened', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'comment.added', actor: 'user', data: { commentId: 'c1', target: 'n1', targetLabel: 'A', text: 'Fix', actor: 'user' } });
    store.apply({ id: 'ev_2', ts: '2026-03-29T00:01:00Z', type: 'comment.resolved', actor: 'claude', data: { commentId: 'c1', actor: 'claude' } });
    store.apply({ id: 'ev_3', ts: '2026-03-29T00:02:00Z', type: 'comment.reopened', actor: 'user', data: { commentId: 'c1', actor: 'user' } });
    expect(store.getState().comments[0].resolved).toBe(false);
  });

  it('stores files field on node.created', () => {
    const store = new EventStore();
    store.apply({
      id: 'ev_1', ts: '2026-03-30T00:00:00Z', type: 'node.created', actor: 'claude',
      data: { nodeId: 'n1', label: 'Auth', subtitle: '', parent: null, depth: 'domain', category: 'arch', confidence: 2, files: ['src/auth/**'] },
    });
    expect(store.getState().nodes.get('n1').files).toEqual(['src/auth/**']);
  });

  it('defaults files to empty array', () => {
    const store = new EventStore();
    store.apply({
      id: 'ev_1', ts: '2026-03-30T00:00:00Z', type: 'node.created', actor: 'claude',
      data: { nodeId: 'n1', label: 'Auth', subtitle: '', parent: null, depth: 'domain', category: 'arch', confidence: 2 },
    });
    expect(store.getState().nodes.get('n1').files).toEqual([]);
  });

  it('getUnresolvedComments filters resolved', () => {
    const store = new EventStore();
    store.apply({ id: 'ev_1', ts: '2026-03-29T00:00:00Z', type: 'comment.added', actor: 'user', data: { commentId: 'c1', target: 'n1', targetLabel: 'A', text: 'Open', actor: 'user' } });
    store.apply({ id: 'ev_2', ts: '2026-03-29T00:00:01Z', type: 'comment.added', actor: 'user', data: { commentId: 'c2', target: 'n1', targetLabel: 'A', text: 'Resolved', actor: 'user' } });
    store.apply({ id: 'ev_3', ts: '2026-03-29T00:01:00Z', type: 'comment.resolved', actor: 'claude', data: { commentId: 'c2', actor: 'claude' } });
    expect(store.getUnresolvedComments()).toHaveLength(1);
    expect(store.getUnresolvedComments()[0].text).toBe('Open');
  });
});
