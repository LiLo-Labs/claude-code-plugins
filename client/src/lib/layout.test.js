import { describe, it, test, expect } from 'vitest';
import { computeLayout, computeEdgePath, clipAtBorder, clipAtEllipse, getAncestors, GRID } from './layout.js';

describe('computeLayout', () => {
  it('positions tab nodes by row/col grid', () => {
    const tabNodes = [
      { nodeId: 'a', row: 0, col: 0, cols: 2 },
      { nodeId: 'b', row: 0, col: 1, cols: 2 },
    ];
    const pos = computeLayout(tabNodes);
    expect(pos.get('a').y).toBe(pos.get('b').y);
    expect(pos.get('b').x).toBeGreaterThan(pos.get('a').x);
  });

  it('positions nodes in different rows vertically', () => {
    const tabNodes = [
      { nodeId: 'top', row: 0, col: 0, cols: 1 },
      { nodeId: 'bottom', row: 1, col: 0, cols: 1 },
    ];
    const pos = computeLayout(tabNodes);
    expect(pos.get('bottom').y).toBeGreaterThan(pos.get('top').y);
  });

  it('all nodes get width and height from grid', () => {
    const pos = computeLayout([{ nodeId: 'a', row: 0, col: 0 }]);
    expect(pos.get('a').w).toBe(GRID.nodeW);
    expect(pos.get('a').h).toBe(GRID.nodeH);
  });

  it('respects saved positions', () => {
    const pos = computeLayout([{ nodeId: 'a', row: 0, col: 0 }], { a: { x: 500, y: 300 } });
    expect(pos.get('a').x).toBe(500);
    expect(pos.get('a').y).toBe(300);
  });

  it('handles 4-column grid', () => {
    const tabNodes = [
      { nodeId: 'a', row: 0, col: 0, cols: 4 },
      { nodeId: 'b', row: 0, col: 1, cols: 4 },
      { nodeId: 'c', row: 0, col: 2, cols: 4 },
      { nodeId: 'd', row: 0, col: 3, cols: 4 },
    ];
    const pos = computeLayout(tabNodes);
    expect(pos.get('b').x).toBeGreaterThan(pos.get('a').x);
    expect(pos.get('c').x).toBeGreaterThan(pos.get('b').x);
    expect(pos.get('d').x).toBeGreaterThan(pos.get('c').x);
  });

  it('handles empty tab', () => {
    const pos = computeLayout([]);
    expect(pos.size).toBe(0);
  });

  it('supports id field as fallback for nodeId', () => {
    const pos = computeLayout([{ id: 'x', row: 0, col: 0 }]);
    expect(pos.has('x')).toBe(true);
  });
});

describe('clipAtBorder', () => {
  it('clips horizontal line at right edge', () => {
    const p = clipAtBorder(100, 100, 200, 100, 50, 30);
    expect(p.x).toBeCloseTo(150);
    expect(p.y).toBeCloseTo(100);
  });

  it('clips vertical line at bottom edge', () => {
    const p = clipAtBorder(100, 100, 100, 200, 50, 30);
    expect(p.x).toBeCloseTo(100);
    expect(p.y).toBeCloseTo(130);
  });
});

describe('clipAtEllipse', () => {
  test('clips horizontal ray to ellipse edge', () => {
    const p = clipAtEllipse(100, 100, 200, 100, 50, 30);
    expect(p.x).toBeCloseTo(150);
    expect(p.y).toBeCloseTo(100);
  });

  test('clips vertical ray to ellipse edge', () => {
    const p = clipAtEllipse(100, 100, 100, 200, 50, 30);
    expect(p.x).toBeCloseTo(100);
    expect(p.y).toBeCloseTo(130);
  });

  test('clips diagonal ray to ellipse edge', () => {
    const p = clipAtEllipse(100, 100, 200, 200, 50, 30);
    const dx = (p.x - 100) / 50;
    const dy = (p.y - 100) / 30;
    expect(dx * dx + dy * dy).toBeCloseTo(1, 1);
  });
});

describe('computeEdgePath', () => {
  it('returns path with Q (quadratic bezier)', () => {
    const from = { x: 0, y: 0, w: 100, h: 50 };
    const to = { x: 300, y: 0, w: 100, h: 50 };
    const result = computeEdgePath(from, to);
    expect(result.path).toContain('M');
    expect(result.path).toContain('Q');
  });

  it('returns label position', () => {
    const from = { x: 0, y: 0, w: 100, h: 50 };
    const to = { x: 0, y: 300, w: 100, h: 50 };
    const result = computeEdgePath(from, to);
    expect(typeof result.labelX).toBe('number');
    expect(typeof result.labelY).toBe('number');
  });
});

describe('getAncestors', () => {
  it('returns empty for root', () => {
    const nodes = new Map([['r', { id: 'r', parent: null }]]);
    expect(getAncestors('r', nodes)).toEqual([]);
  });

  it('returns ancestors root → parent', () => {
    const nodes = new Map([
      ['r', { id: 'r', label: 'Root', parent: null }],
      ['m', { id: 'm', label: 'Mid', parent: 'r' }],
      ['l', { id: 'l', label: 'Leaf', parent: 'm' }],
    ]);
    const anc = getAncestors('l', nodes);
    expect(anc).toHaveLength(2);
    expect(anc[0].id).toBe('r');
    expect(anc[1].id).toBe('m');
  });
});
