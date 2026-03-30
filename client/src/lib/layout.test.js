import { describe, it, expect } from 'vitest';
import { computeLayout, computeSize, getAncestors, findVisibleEndpoint } from './layout.js';

function makeNodes(defs) {
  const map = new Map();
  for (const d of defs) {
    map.set(d.id, { id: d.id, label: d.label || d.id, subtitle: d.subtitle || '', parent: d.parent || null, status: 'planned', depth: 'module', category: 'arch', confidence: 2, completeness: 0, hasWorkaround: false });
  }
  return map;
}

describe('computeSize', () => {
  it('returns leaf node size based on content', () => {
    const nodes = makeNodes([{ id: 'a', label: 'Short' }]);
    const size = computeSize(nodes.get('a'), nodes, new Set());
    expect(size.w).toBeGreaterThanOrEqual(200); // min width
    expect(size.h).toBeGreaterThan(30);
    expect(size.isContainer).toBe(false);
  });

  it('returns wider size for longer labels', () => {
    const nodes = makeNodes([
      { id: 'short', label: 'Hi' },
      { id: 'long', label: 'This is a very long component name' },
    ]);
    const shortSize = computeSize(nodes.get('short'), nodes, new Set());
    const longSize = computeSize(nodes.get('long'), nodes, new Set());
    expect(longSize.w).toBeGreaterThan(shortSize.w);
  });

  it('returns container size wrapping children horizontally', () => {
    const nodes = makeNodes([
      { id: 'p', label: 'Parent' },
      { id: 'c1', label: 'Child 1', parent: 'p' },
      { id: 'c2', label: 'Child 2', parent: 'p' },
    ]);
    const expanded = new Set(['p']);
    const size = computeSize(nodes.get('p'), nodes, expanded);
    expect(size.isContainer).toBe(true);
    expect(size.w).toBeGreaterThan(400); // two children side by side + gaps
    expect(size.childSizes).toHaveLength(2);
  });

  it('collapsed parent returns leaf size', () => {
    const nodes = makeNodes([
      { id: 'p', label: 'Parent' },
      { id: 'c1', label: 'Child', parent: 'p' },
    ]);
    const size = computeSize(nodes.get('p'), nodes, new Set());
    expect(size.isContainer).toBe(false);
  });
});

describe('computeLayout', () => {
  it('positions roots horizontally', () => {
    const nodes = makeNodes([
      { id: 'a', label: 'Alpha' },
      { id: 'b', label: 'Beta' },
    ]);
    const positions = computeLayout(nodes, new Set());
    const pa = positions.get('a');
    const pb = positions.get('b');
    expect(pa.y).toBe(pb.y); // same row
    expect(pb.x).toBeGreaterThan(pa.x + pa.w); // b is to the right of a
  });

  it('positions children horizontally inside container', () => {
    const nodes = makeNodes([
      { id: 'p', label: 'Parent' },
      { id: 'c1', label: 'Child 1', parent: 'p' },
      { id: 'c2', label: 'Child 2', parent: 'p' },
      { id: 'c3', label: 'Child 3', parent: 'p' },
    ]);
    const positions = computeLayout(nodes, new Set(['p']));
    const pc1 = positions.get('c1');
    const pc2 = positions.get('c2');
    const pc3 = positions.get('c3');
    // All children at same y
    expect(pc1.y).toBe(pc2.y);
    expect(pc2.y).toBe(pc3.y);
    // Ordered left to right
    expect(pc2.x).toBeGreaterThan(pc1.x);
    expect(pc3.x).toBeGreaterThan(pc2.x);
  });

  it('container wraps children', () => {
    const nodes = makeNodes([
      { id: 'p', label: 'Parent' },
      { id: 'c1', label: 'Child 1', parent: 'p' },
      { id: 'c2', label: 'Child 2', parent: 'p' },
    ]);
    const positions = computeLayout(nodes, new Set(['p']));
    const pp = positions.get('p');
    const pc1 = positions.get('c1');
    const pc2 = positions.get('c2');
    // Children are inside the container bounds
    expect(pc1.x).toBeGreaterThan(pp.x);
    expect(pc2.x + pc2.w).toBeLessThanOrEqual(pp.x + pp.w + 1); // +1 for rounding
    expect(pc1.y).toBeGreaterThan(pp.y);
  });

  it('nested containers work', () => {
    const nodes = makeNodes([
      { id: 'root', label: 'Root' },
      { id: 'mid', label: 'Middle', parent: 'root' },
      { id: 'leaf', label: 'Leaf', parent: 'mid' },
    ]);
    const positions = computeLayout(nodes, new Set(['root', 'mid']));
    expect(positions.get('root').isContainer).toBe(true);
    expect(positions.get('mid').isContainer).toBe(true);
    expect(positions.get('leaf').isContainer).toBe(false);
    // Leaf is inside mid, mid is inside root
    const pr = positions.get('root');
    const pm = positions.get('mid');
    const pl = positions.get('leaf');
    expect(pm.x).toBeGreaterThan(pr.x);
    expect(pl.x).toBeGreaterThan(pm.x);
  });

  it('collapsed nodes have no children in positions', () => {
    const nodes = makeNodes([
      { id: 'p', label: 'Parent' },
      { id: 'c', label: 'Child', parent: 'p' },
    ]);
    const positions = computeLayout(nodes, new Set()); // nothing expanded
    expect(positions.has('p')).toBe(true);
    expect(positions.has('c')).toBe(false);
  });

  it('respects saved positions', () => {
    const nodes = makeNodes([{ id: 'a', label: 'Alpha' }]);
    const saved = { a: { x: 500, y: 300 } };
    const positions = computeLayout(nodes, new Set(), saved);
    expect(positions.get('a').x).toBe(500);
    expect(positions.get('a').y).toBe(300);
  });
});

describe('getAncestors', () => {
  it('returns empty for root', () => {
    const nodes = makeNodes([{ id: 'r', label: 'Root' }]);
    expect(getAncestors('r', nodes)).toEqual([]);
  });

  it('returns ancestors root to parent', () => {
    const nodes = makeNodes([
      { id: 'r', label: 'Root' },
      { id: 'm', label: 'Mid', parent: 'r' },
      { id: 'l', label: 'Leaf', parent: 'm' },
    ]);
    const anc = getAncestors('l', nodes);
    expect(anc).toHaveLength(2);
    expect(anc[0].id).toBe('r');
    expect(anc[1].id).toBe('m');
  });
});

describe('findVisibleEndpoint', () => {
  it('returns nodeId if it has a position', () => {
    const nodes = makeNodes([{ id: 'a' }]);
    const positions = new Map([['a', { x: 0, y: 0 }]]);
    expect(findVisibleEndpoint('a', nodes, positions)).toBe('a');
  });

  it('returns nearest visible ancestor', () => {
    const nodes = makeNodes([
      { id: 'p', label: 'Parent' },
      { id: 'c', label: 'Child', parent: 'p' },
    ]);
    const positions = new Map([['p', { x: 0, y: 0 }]]); // only parent visible
    expect(findVisibleEndpoint('c', nodes, positions)).toBe('p');
  });

  it('returns null if no ancestor visible', () => {
    const nodes = makeNodes([{ id: 'a' }]);
    expect(findVisibleEndpoint('a', nodes, new Map())).toBeNull();
  });
});
