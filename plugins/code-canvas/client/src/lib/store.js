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
    for (const event of events) store.apply(event);
    return store;
  }

  apply(event) {
    this.events.push(event);
    const d = event.data;
    switch (event.type) {
      case 'node.created':
        this._nodes.set(d.nodeId, {
          id: d.nodeId, label: d.label || '', subtitle: d.subtitle || '',
          parent: d.parent || null, status: d.status || 'planned',
          depth: d.depth || 'module', category: d.category || 'arch',
          confidence: d.confidence ?? 1, files: d.files || [],
          row: d.row ?? 0, col: d.col ?? 0, cols: d.cols ?? 3,
          color: d.color || null, textColor: d.textColor || null,
          hasWorkaround: false, completeness: 0,
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
        this._cleanOrphanedEdges();
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
          id: d.edgeId, from: d.from, to: d.to,
          label: d.label || '', edgeType: d.edgeType || 'dependency',
          color: d.color || '#64748b',
        });
        break;
      case 'edge.updated':
        if (this._edges.has(d.edgeId)) Object.assign(this._edges.get(d.edgeId), d.changes);
        break;
      case 'edge.deleted':
        this._edges.delete(d.edgeId);
        break;
      case 'decision.recorded':
        this._decisions.push({
          nodeId: d.nodeId, type: d.type || 'decision', chosen: d.chosen,
          alternatives: d.alternatives || [], reason: d.reason || '',
          ts: event.ts, actor: event.actor,
        });
        if (d.type === 'workaround' && this._nodes.has(d.nodeId)) {
          this._nodes.get(d.nodeId).hasWorkaround = true;
        }
        break;
      case 'comment.added':
        this._comments.push({
          id: d.commentId, target: d.target, targetLabel: d.targetLabel || '',
          text: d.text, actor: d.actor || event.actor,
          resolved: false, resolvedAt: null, resolvedBy: null, ts: event.ts,
        });
        break;
      case 'comment.resolved': {
        const c = this._comments.find(c => c.id === d.commentId);
        if (c) { c.resolved = true; c.resolvedAt = event.ts; c.resolvedBy = d.actor || event.actor; }
        break;
      }
      case 'comment.reopened': {
        const c = this._comments.find(c => c.id === d.commentId);
        if (c) { c.resolved = false; c.resolvedAt = null; c.resolvedBy = null; }
        break;
      }
      case 'comment.deleted':
        this._comments = this._comments.filter(c => c.id !== d.commentId);
        break;
      case 'view.created':
        this._views.push({
          id: d.viewId, name: d.name, story: d.story || '',
          description: d.description || '', rendering: d.rendering || {},
          tabNodes: d.tabNodes || [], tabConnections: d.tabConnections || [],
          drawioXml: d.drawioXml || '', filter: d.filter || null,
        });
        break;
      case 'view.updated': {
        const v = this._views.find(v => v.id === d.viewId);
        if (v) Object.assign(v, d.changes);
        break;
      }
      case 'view.deleted':
        this._views = this._views.filter(v => v.id !== d.viewId);
        break;
    }
  }

  _cleanOrphanedEdges() {
    for (const [edgeId, edge] of this._edges) {
      if (!this._nodes.has(edge.from) || !this._nodes.has(edge.to)) this._edges.delete(edgeId);
    }
  }

  _recomputeCompleteness() {
    for (const [id, node] of this._nodes) {
      const children = [...this._nodes.values()].filter(n => n.parent === id);
      if (children.length === 0) {
        node.completeness = node.status === 'done' ? 1 : 0;
      } else {
        node.completeness = children.filter(c => c.status === 'done').length / children.length;
      }
    }
  }

  getAncestors(nodeId) {
    const result = [];
    let current = this._nodes.get(nodeId);
    while (current && current.parent) {
      const parent = this._nodes.get(current.parent);
      if (parent) result.unshift(parent);
      current = parent;
    }
    return result;
  }

  getState() {
    return {
      nodes: new Map(this._nodes), edges: new Map(this._edges),
      comments: [...this._comments], decisions: [...this._decisions],
      views: [...this._views], eventCount: this.events.length,
    };
  }

  getNodeDecisions(nodeId) { return this._decisions.filter(d => d.nodeId === nodeId); }

  getNodeHistory(nodeId) {
    return this.events.filter(e => {
      const d = e.data;
      return d.nodeId === nodeId || d.target === nodeId || d.from === nodeId || d.to === nodeId;
    });
  }

  getUnresolvedComments() { return this._comments.filter(c => !c.resolved); }
}
