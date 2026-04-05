import { describe, it, expect } from 'vitest';
import { getShapeByName, getShapeForNode, getStyledShape, listShapes, findShapesByTag } from './registry.js';

describe('getShapeByName', () => {
  it('returns shape by exact name', () => {
    const s = getShapeByName('database');
    expect(s).not.toBeNull();
    expect(s.style).toContain('cylinder3');
  });
  it('returns null for unknown name', () => {
    expect(getShapeByName('nonexistent')).toBeNull();
  });
});

describe('getShapeForNode', () => {
  it('auto-selects database for node with "PostgreSQL" label', () => {
    const s = getShapeForNode({ label: 'PostgreSQL', depth: 'system', status: 'done' });
    expect(s.name).toBe('database');
  });
  it('auto-selects queue for "RabbitMQ" label', () => {
    const s = getShapeForNode({ label: 'RabbitMQ', depth: 'system', status: 'planned' });
    expect(s.name).toBe('queue');
  });
  it('auto-selects cache for "Redis" label', () => {
    const s = getShapeForNode({ label: 'Redis Cache', depth: 'system', status: 'done' });
    expect(s.name).toBe('cache');
  });
  it('auto-selects actor for category=actor', () => {
    const s = getShapeForNode({ label: 'User', category: 'actor', depth: 'module', status: 'done' });
    expect(s.name).toBe('actor');
  });
  it('uses explicit shape override', () => {
    const s = getShapeForNode({ label: 'Whatever', shape: 'decision', depth: 'module', status: 'planned' });
    expect(s.name).toBe('decision');
  });
  it('falls back to depth-based shape', () => {
    const s = getShapeForNode({ label: 'My Module', depth: 'module', status: 'planned' });
    expect(s.name).toBe('module');
  });
  it('falls back to system for depth=system', () => {
    const s = getShapeForNode({ label: 'API Gateway', depth: 'system', status: 'done' });
    expect(s.name).toBe('server');
  });
});

describe('getStyledShape', () => {
  it('applies done colors', () => {
    const s = getStyledShape({ label: 'Test', depth: 'module', status: 'done' });
    expect(s.style).toContain('fillColor=#1a3320');
    expect(s.style).toContain('strokeColor=#3fb950');
  });
  it('applies blocked colors', () => {
    const s = getStyledShape({ label: 'Test', depth: 'module', status: 'blocked' });
    expect(s.style).toContain('fillColor=#2a1010');
    expect(s.style).toContain('strokeColor=#f85149');
  });
  it('returns correct dimensions', () => {
    const s = getStyledShape({ label: 'PostgreSQL', depth: 'system', status: 'done' });
    expect(s.width).toBe(80);
    expect(s.height).toBe(80);
  });
});

describe('listShapes', () => {
  it('returns all registered shapes', () => {
    const all = listShapes();
    expect(all.length).toBeGreaterThan(15);
    expect(all.find(s => s.name === 'actor')).toBeDefined();
    expect(all.find(s => s.name === 'database')).toBeDefined();
    expect(all.find(s => s.name === 'swimlane')).toBeDefined();
  });
});

describe('findShapesByTag', () => {
  it('finds UML shapes', () => {
    const uml = findShapesByTag('uml');
    expect(uml.length).toBeGreaterThan(2);
    expect(uml.find(s => s.name === 'actor')).toBeDefined();
    expect(uml.find(s => s.name === 'usecase')).toBeDefined();
  });
  it('finds infra shapes', () => {
    const infra = findShapesByTag('infra');
    expect(infra.find(s => s.name === 'database')).toBeDefined();
    expect(infra.find(s => s.name === 'cache')).toBeDefined();
  });
});
