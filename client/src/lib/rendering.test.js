import { describe, test, expect } from 'vitest';
import { resolveHints, DEFAULTS } from './rendering.js';

describe('resolveHints', () => {
  test('returns all defaults when no hints provided', () => {
    const hints = resolveHints({});
    expect(hints.nodeShape).toBe('card');
    expect(hints.edgeStyle).toBe('curve');
    expect(hints.layout).toBe('grid');
    expect(hints.nodeSize).toBe('standard');
    expect(hints.edgeLabels).toBe('pill');
    expect(hints.nodeContent).toEqual(['label', 'subtitle']);
  });

  test('overrides specific hints', () => {
    const hints = resolveHints({ nodeShape: 'ellipse', layout: 'horizontal-lanes' });
    expect(hints.nodeShape).toBe('ellipse');
    expect(hints.layout).toBe('horizontal-lanes');
    expect(hints.edgeStyle).toBe('curve');
  });

  test('returns undefined hints as undefined (passthrough)', () => {
    const hints = resolveHints({ nodeShape: 'ellipse' });
    expect(hints.groupBy).toBeUndefined();
    expect(hints.ordering).toBeUndefined();
  });
});
