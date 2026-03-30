import { describe, it, expect } from 'vitest';
import { computeLayout, computeEdgePath, clipAtBorder, getAncestors, GRID } from './layout.js';

function makeNodes(defs) {
  const map = new Map();
  for (const d of defs) {
    map.set(d.id, {
      id: d.id, label: d.label || d.id, subtitle: d.subtitle || '',
      parent: d.parent || null, status: 'planned', depth: 'module',
      category: 'arch', confidence: 2, completeness: 0, hasWorkaround: false,
      row: d.row ?? 0, col: d.col ?? 0, cols: d.cols ?? 3,
    });
  }
  return map;
}

describe('computeLayout', () => {
  it('positions nodes by row/col grid', () => {
    const nodes = makeNodes([
      { id: 'a', row: 0, col: 0, cols: 2 },
      { id: 'b', row: 0, col: 1, cols: 2 },
    ]);
    const pos = computeLayout(nodes);
    expect(pos.get('a').y).toBe(pos.get('b').y); // same row
    expect(pos.get('b').x).toBeGreaterThan(pos.get('a').x); // b is right of a
  });

  it('positions nodes in different rows vertically', () => {
    const nodes = makeNodes([
      { id: 'top', row: 0, col: 0 },
      { id: 'bottom', row: 1, col: 0 },
    ]);
    const pos = computeLayout(nodes);
    expect(pos.get('bottom').y).toBeGreaterThan(pos.get('top').y);
  });

  it('all nodes get width and height from grid', () => {
    const nodes = makeNodes([{ id: 'a' }]);
    const pos = computeLayout(nodes);
    expect(pos.get('a').w).toBe(GRID.nodeW);
    expect(pos.get('a').h).toBe(GRID.nodeH);
  });

  it('respects saved positions', () => {
    const nodes = makeNodes([{ id: 'a' }]);
    const pos = computeLayout(nodes, { a: { x: 500, y: 300 } });
    expect(pos.get('a').x).toBe(500);
    expect(pos.get('a').y).toBe(300);
  });

  it('handles grid with varying cols', () => {
    const nodes = makeNodes([
      { id: 'wide', row: 0, col: 0, cols: 4 },
      { id: 'a', row: 1, col: 0, cols: 4 },
      { id: 'b', row: 1, col: 1, cols: 4 },
      { id: 'c', row: 1, col: 2, cols: 4 },
      { id: 'd', row: 1, col: 3, cols: 4 },
    ]);
    const pos = computeLayout(nodes);
    // All row-1 nodes at same y
    expect(pos.get('a').y).toBe(pos.get('b').y);
    expect(pos.get('c').y).toBe(pos.get('d').y);
    // Ordered left to right
    expect(pos.get('b').x).toBeGreaterThan(pos.get('a').x);
    expect(pos.get('c').x).toBeGreaterThan(pos.get('b').x);
    expect(pos.get('d').x).toBeGreaterThan(pos.get('c').x);
  });
});

describe('clipAtBorder', () => {
  it('clips line at rectangle border', () => {
    const p = clipAtBorder(100, 100, 200, 100, 50, 30);
    expect(p.x).toBeCloseTo(150); // right edge
    expect(p.y).toBeCloseTo(100); // same y (horizontal line)
  });

  it('handles vertical line', () => {
    const p = clipAtBorder(100, 100, 100, 200, 50, 30);
    expect(p.x).toBeCloseTo(100);
    expect(p.y).toBeCloseTo(130); // bottom edge
  });
});

describe('computeEdgePath', () => {
  it('returns a path string', () => {
    const from = { x: 0, y: 0, w: 100, h: 50 };
    const to = { x: 200, y: 0, w: 100, h: 50 };
    const result = computeEdgePath(from, to);
    expect(result.path).toContain('M');
    expect(result.path).toContain('Q');
    expect(typeof result.labelX).toBe('number');
    expect(typeof result.labelY).toBe('number');
  });

  it('handles vertical connection', () => {
    const from = { x: 0, y: 0, w: 100, h: 50 };
    const to = { x: 0, y: 200, w: 100, h: 50 };
    const result = computeEdgePath(from, to);
    expect(result.path).toContain('M');
    expect(result.path).toContain('Q');
  });
});

describe('getAncestors', () => {
  it('returns empty for root', () => {
    const nodes = makeNodes([{ id: 'r' }]);
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
