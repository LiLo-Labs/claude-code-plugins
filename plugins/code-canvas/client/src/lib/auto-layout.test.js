import { describe, it, expect } from 'vitest';
import { generateLayoutXml, generateViewXml } from './auto-layout.js';

const NODES = new Map([
  ['n_server', { id: 'n_server', label: 'Server', subtitle: 'HTTP API', status: 'done', depth: 'system' }],
  ['n_db', { id: 'n_db', label: 'Database', subtitle: 'PostgreSQL', status: 'in-progress', depth: 'domain' }],
  ['n_routes', { id: 'n_routes', label: 'Routes', subtitle: '', status: 'planned', depth: 'module' }],
  ['n_auth', { id: 'n_auth', label: 'Auth', subtitle: 'JWT tokens', status: 'blocked', depth: 'module' }],
]);

const EDGES = new Map([
  ['e1', { id: 'e1', from: 'n_server', to: 'n_routes', label: 'dispatches' }],
  ['e2', { id: 'e2', from: 'n_routes', to: 'n_db', label: 'queries' }],
  ['e3', { id: 'e3', from: 'n_server', to: 'n_auth', label: 'uses' }],
]);

describe('generateLayoutXml', () => {
  it('generates valid XML with all nodes and edges', () => {
    const xml = generateLayoutXml(NODES, EDGES);
    expect(xml).toContain('<mxGraphModel>');
    expect(xml).toContain('id="n_server"');
    expect(xml).toContain('id="n_db"');
    expect(xml).toContain('id="n_routes"');
    expect(xml).toContain('id="n_auth"');
    expect(xml).toContain('id="e1"');
    expect(xml).toContain('id="e2"');
    expect(xml).toContain('id="e3"');
    expect(xml).toContain('</mxGraphModel>');
  });

  it('applies status-based colors', () => {
    const xml = generateLayoutXml(NODES, EDGES);
    // n_server is done → green
    const serverSection = xml.slice(xml.indexOf('id="n_server"'), xml.indexOf('id="n_server"') + 300);
    expect(serverSection).toContain('fillColor=#1a3320');
    expect(serverSection).toContain('strokeColor=#3fb950');

    // n_auth is blocked → red
    const authSection = xml.slice(xml.indexOf('id="n_auth"'), xml.indexOf('id="n_auth"') + 300);
    expect(authSection).toContain('fillColor=#2a1010');
    expect(authSection).toContain('strokeColor=#f85149');
  });

  it('places nodes at different Y positions based on hierarchy', () => {
    const xml = generateLayoutXml(NODES, EDGES);
    // Server is rank 0 (no incoming edges), routes/auth are rank 1, db is rank 2
    // Extract Y positions
    const getY = (id) => {
      const idx = xml.indexOf(`id="${id}"`);
      const geoIdx = xml.indexOf('<mxGeometry', idx);
      const yMatch = xml.slice(geoIdx, geoIdx + 100).match(/y="(\d+)"/);
      return yMatch ? parseInt(yMatch[1]) : -1;
    };

    const serverY = getY('n_server');
    const routesY = getY('n_routes');
    const dbY = getY('n_db');

    // Server should be above routes, routes above db
    expect(serverY).toBeLessThan(routesY);
    expect(routesY).toBeLessThan(dbY);
  });

  it('includes subtitles in labels with line break', () => {
    const xml = generateLayoutXml(NODES, EDGES);
    expect(xml).toContain('Server&#xa;HTTP API');
    expect(xml).toContain('Database&#xa;PostgreSQL');
  });

  it('makes system/domain nodes bold and wider', () => {
    const xml = generateLayoutXml(NODES, EDGES);
    const serverSection = xml.slice(xml.indexOf('id="n_server"'), xml.indexOf('id="n_server"') + 400);
    expect(serverSection).toContain('fontStyle=1');
    expect(serverSection).toContain('width="220"');
  });

  it('includes edge labels', () => {
    const xml = generateLayoutXml(NODES, EDGES);
    expect(xml).toContain('value="dispatches"');
    expect(xml).toContain('value="queries"');
  });

  it('handles empty inputs', () => {
    expect(generateLayoutXml(new Map(), new Map())).toBe('');
  });

  it('handles nodes with no edges', () => {
    const xml = generateLayoutXml(NODES, new Map());
    expect(xml).toContain('id="n_server"');
    expect(xml).toContain('id="n_db"');
    // All nodes should be at the same rank (no hierarchy without edges)
  });

  it('handles cycles gracefully', () => {
    const cyclicEdges = new Map([
      ['e1', { id: 'e1', from: 'n_server', to: 'n_routes', label: '' }],
      ['e2', { id: 'e2', from: 'n_routes', to: 'n_server', label: '' }],
    ]);
    const xml = generateLayoutXml(NODES, cyclicEdges);
    // Should still produce valid XML without hanging
    expect(xml).toContain('<mxGraphModel>');
    expect(xml).toContain('id="n_server"');
  });

  it('skips edges with missing endpoints', () => {
    const badEdges = new Map([
      ['e1', { id: 'e1', from: 'n_server', to: 'n_missing', label: 'broken' }],
    ]);
    const xml = generateLayoutXml(NODES, badEdges);
    expect(xml).not.toContain('n_missing');
    expect(xml).not.toContain('broken');
  });

  it('escapes XML special characters in labels', () => {
    const specialNodes = new Map([
      ['n_test', { id: 'n_test', label: 'A & B <C>', subtitle: '"quoted"', status: 'planned', depth: 'module' }],
    ]);
    const xml = generateLayoutXml(specialNodes, new Map());
    expect(xml).toContain('A &amp; B &lt;C&gt;');
    expect(xml).toContain('&quot;quoted&quot;');
  });
});

describe('generateViewXml', () => {
  it('includes all nodes when view has no tabNodes filter', () => {
    const view = { id: 'v1', name: 'All', tabNodes: [] };
    const xml = generateViewXml(view, NODES, EDGES);
    expect(xml).toContain('id="n_server"');
    expect(xml).toContain('id="n_db"');
    expect(xml).toContain('id="n_routes"');
    expect(xml).toContain('id="n_auth"');
  });

  it('filters to specified tabNodes', () => {
    const view = { id: 'v1', name: 'API', tabNodes: ['n_server', 'n_routes'] };
    const xml = generateViewXml(view, NODES, EDGES);
    expect(xml).toContain('id="n_server"');
    expect(xml).toContain('id="n_routes"');
    expect(xml).not.toContain('id="n_db"');
    expect(xml).not.toContain('id="n_auth"');
  });

  it('only includes edges between view nodes', () => {
    const view = { id: 'v1', name: 'API', tabNodes: ['n_server', 'n_routes'] };
    const xml = generateViewXml(view, NODES, EDGES);
    // e1 connects server→routes (both in view) — should be included
    expect(xml).toContain('id="e1"');
    // e2 connects routes→db (db not in view) — should be excluded
    expect(xml).not.toContain('id="e2"');
  });

  it('handles tabNodes as objects with nodeId', () => {
    const view = { id: 'v1', name: 'API', tabNodes: [{ nodeId: 'n_server' }, { nodeId: 'n_db' }] };
    const xml = generateViewXml(view, NODES, EDGES);
    expect(xml).toContain('id="n_server"');
    expect(xml).toContain('id="n_db"');
  });
});
