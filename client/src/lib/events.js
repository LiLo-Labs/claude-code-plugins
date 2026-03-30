/**
 * Event store — replays JSONL events into derived graph state.
 * All canvas state is computed from this. Never mutate state directly.
 */

let idCounter = 0;
export function genId(prefix = 'ev') {
  return `${prefix}_${Date.now()}_${++idCounter}`;
}

export class EventStore {
  constructor() {
    this.events = [];
    this._nodes = new Map();
    this._edges = new Map();
    this._comments = [];
    this._decisions = [];
    this._views = [];
  }

  static fromEvents(events) {
    const store = new EventStore();
    for (const event of events) {
      store.apply(event);
    }
    return store;
  }

  apply(event) {
    this.events.push(event);
    const d = event.data;

    switch (event.type) {
      case 'node.created':
        this._nodes.set(d.nodeId, {
          id: d.nodeId,
          label: d.label,
          subtitle: d.subtitle || '',
          parent: d.parent || null,
          status: 'planned',
          depth: d.depth || 'module',
          category: d.category || 'arch',
          confidence: d.confidence ?? 1,
          hasWorkaround: false,
          completeness: 0,
        });
        this._recomputeCompleteness();
        break;

      case 'node.updated':
        if (this._nodes.has(d.nodeId)) {
          Object.assign(this._nodes.get(d.nodeId), d.changes);
          this._recomputeCompleteness();
        }
        break;

      case 'node.deleted':
        this._nodes.delete(d.nodeId);
        this._recomputeCompleteness();
        break;

      case 'node.status':
        if (this._nodes.has(d.nodeId)) {
          this._nodes.get(d.nodeId).status = d.status;
          this._recomputeCompleteness();
        }
        break;

      case 'edge.created':
        this._edges.set(d.edgeId, {
          id: d.edgeId,
          from: d.from,
          to: d.to,
          label: d.label || '',
          edgeType: d.edgeType || 'dependency',
          color: d.color || '#64748b',
        });
        break;

      case 'edge.updated':
        if (this._edges.has(d.edgeId)) {
          Object.assign(this._edges.get(d.edgeId), d.changes);
        }
        break;

      case 'edge.deleted':
        this._edges.delete(d.edgeId);
        break;

      case 'decision.recorded':
        this._decisions.push({
          nodeId: d.nodeId,
          type: d.type,
          chosen: d.chosen,
          alternatives: d.alternatives || [],
          reason: d.reason || '',
          ts: event.ts,
          actor: event.actor,
        });
        if (d.type === 'workaround' && this._nodes.has(d.nodeId)) {
          this._nodes.get(d.nodeId).hasWorkaround = true;
        }
        break;

      case 'comment.added':
        this._comments.push({
          id: d.commentId,
          target: d.target,
          targetLabel: d.targetLabel || '',
          text: d.text,
          actor: d.actor || event.actor,
          resolved: false,
          resolvedAt: null,
          resolvedBy: null,
          ts: event.ts,
        });
        break;

      case 'comment.resolved': {
        const comment = this._comments.find(c => c.id === d.commentId);
        if (comment) {
          comment.resolved = true;
          comment.resolvedAt = event.ts;
          comment.resolvedBy = d.actor || event.actor;
        }
        break;
      }

      case 'comment.reopened': {
        const comment = this._comments.find(c => c.id === d.commentId);
        if (comment) {
          comment.resolved = false;
          comment.resolvedAt = null;
          comment.resolvedBy = null;
        }
        break;
      }

      case 'comment.deleted':
        this._comments = this._comments.filter(c => c.id !== d.commentId);
        break;

      case 'view.created':
        this._views.push({
          id: d.viewId,
          name: d.name,
          description: d.description || '',
          filter: d.filter || {},
        });
        break;

      case 'view.updated': {
        const view = this._views.find(v => v.id === d.viewId);
        if (view) Object.assign(view, d.changes);
        break;
      }

      case 'layout.saved':
        break;
    }
  }

  _recomputeCompleteness() {
    for (const [id, node] of this._nodes) {
      const children = [...this._nodes.values()].filter(n => n.parent === id);
      if (children.length === 0) {
        node.completeness = node.status === 'done' ? 1 : 0;
      } else {
        const done = children.filter(c => c.status === 'done').length;
        node.completeness = done / children.length;
      }
    }
  }

  getState() {
    return {
      nodes: new Map(this._nodes),
      edges: new Map(this._edges),
      comments: [...this._comments],
      decisions: [...this._decisions],
      views: [...this._views],
      eventCount: this.events.length,
    };
  }

  getNodeDecisions(nodeId) {
    return this._decisions.filter(d => d.nodeId === nodeId);
  }

  getNodeHistory(nodeId) {
    return this.events.filter(e => {
      const d = e.data;
      return d.nodeId === nodeId || d.target === nodeId || d.from === nodeId || d.to === nodeId;
    });
  }

  getUnresolvedComments() {
    return this._comments.filter(c => !c.resolved);
  }
}
