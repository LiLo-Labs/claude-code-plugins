import { describe, test, expect } from 'vitest';
import { parseStyle, styleToString, parseDrawioXml, serializeToXml } from './svg-renderer.js';

describe('parseStyle', () => {
  test('parses semicolon-delimited style string', () => {
    const result = parseStyle('rounded=1;fillColor=#1a3320;strokeColor=#3fb950;fontSize=13;');
    expect(result.rounded).toBe('1');
    expect(result.fillColor).toBe('#1a3320');
    expect(result.strokeColor).toBe('#3fb950');
    expect(result.fontSize).toBe('13');
  });

  test('handles shape prefix', () => {
    const result = parseStyle('shape=hexagon;whiteSpace=wrap;fillColor=#1a3320;');
    expect(result.shape).toBe('hexagon');
    expect(result.fillColor).toBe('#1a3320');
  });

  test('returns empty object for empty string', () => {
    expect(parseStyle('')).toEqual({});
    expect(parseStyle(undefined)).toEqual({});
  });
});

describe('styleToString', () => {
  test('converts object back to semicolon-delimited string', () => {
    const str = styleToString({ rounded: '1', fillColor: '#1a3320' });
    expect(str).toContain('rounded=1');
    expect(str).toContain('fillColor=#1a3320');
    expect(str.endsWith(';')).toBe(true);
  });
});

describe('parseDrawioXml', () => {
  const xml = '<mxGraphModel><root>' +
    '<mxCell id="0"/><mxCell id="1" parent="0"/>' +
    '<mxCell id="n_server" value="Server&#xa;HTTP API" style="rounded=1;fillColor=#1a3320;strokeColor=#3fb950;" vertex="1" parent="1">' +
    '<mxGeometry x="100" y="200" width="160" height="60" as="geometry"/>' +
    '</mxCell>' +
    '<mxCell id="e_1" value="calls" style="curved=1;strokeColor=#8b949e;" edge="1" source="n_server" target="n_db" parent="1">' +
    '<mxGeometry relative="1" as="geometry"/>' +
    '</mxCell>' +
    '</root></mxGraphModel>';

  test('parses vertex cells into cells Map', () => {
    const { cells } = parseDrawioXml(xml);
    expect(cells.size).toBe(1);
    const server = cells.get('n_server');
    expect(server.value).toBe('Server\nHTTP API');
    expect(server.x).toBe(100);
    expect(server.y).toBe(200);
    expect(server.width).toBe(160);
    expect(server.height).toBe(60);
    expect(server.style.fillColor).toBe('#1a3320');
  });

  test('parses edge cells into edges Map', () => {
    const { edges } = parseDrawioXml(xml);
    expect(edges.size).toBe(1);
    const edge = edges.get('e_1');
    expect(edge.value).toBe('calls');
    expect(edge.source).toBe('n_server');
    expect(edge.target).toBe('n_db');
  });

  test('returns empty maps for empty/invalid XML', () => {
    const { cells, edges } = parseDrawioXml('');
    expect(cells.size).toBe(0);
    expect(edges.size).toBe(0);
  });
});

describe('serializeToXml', () => {
  test('round-trip: parse then serialize preserves data', () => {
    const xml = '<mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/><mxCell id="n_a" value="NodeA" style="rounded=1;fillColor=#1a3320;" vertex="1" parent="1"><mxGeometry x="40" y="80" width="120" height="50" as="geometry"/></mxCell></root></mxGraphModel>';
    const { cells, edges } = parseDrawioXml(xml);
    const result = serializeToXml(cells, edges);
    const reparsed = parseDrawioXml(result);
    expect(reparsed.cells.size).toBe(1);
    const node = reparsed.cells.get('n_a');
    expect(node.value).toBe('NodeA');
    expect(node.x).toBe(40);
    expect(node.y).toBe(80);
    expect(node.style.fillColor).toBe('#1a3320');
  });
});
