import { describe, it, expect } from 'vitest';
import { updateShapeStatus, updateMultipleStatuses, findMissingNodes } from './diagram-sync.js';

const SAMPLE_XML = [
  '<mxGraphModel><root>',
  '<mxCell id="0"/><mxCell id="1" parent="0"/>',
  '<mxCell id="n_api" value="API" style="rounded=1;fillColor=#1e3a5f;strokeColor=#4a90d9;fontColor=#e6edf3;" vertex="1" parent="1"><mxGeometry x="40" y="40" width="200" height="60" as="geometry"/></mxCell>',
  '<mxCell id="n_db" value="DB" style="rounded=1;fillColor=#1a3320;strokeColor=#3fb950;fontColor=#e6edf3;" vertex="1" parent="1"><mxGeometry x="40" y="140" width="200" height="60" as="geometry"/></mxCell>',
  '<mxCell id="e1" value="queries" style="rounded=1;curved=1;strokeColor=#8b949e;" edge="1" source="n_api" target="n_db" parent="1"><mxGeometry relative="1" as="geometry"/></mxCell>',
  '</root></mxGraphModel>',
].join('');

describe('updateShapeStatus', () => {
  it('updates fillColor and strokeColor for a node', () => {
    const result = updateShapeStatus(SAMPLE_XML, 'n_api', 'done');
    expect(result).toContain('fillColor=#1a3320');
    expect(result).toContain('strokeColor=#3fb950');
    expect(result).not.toContain('fillColor=#1e3a5f'); // old color gone
  });

  it('does not modify edge cells', () => {
    const result = updateShapeStatus(SAMPLE_XML, 'e1', 'done');
    // Edge should be unchanged
    expect(result).toBe(SAMPLE_XML);
  });

  it('returns original XML if node not found', () => {
    const result = updateShapeStatus(SAMPLE_XML, 'n_nonexistent', 'done');
    expect(result).toBe(SAMPLE_XML);
  });

  it('returns original XML for unknown status', () => {
    const result = updateShapeStatus(SAMPLE_XML, 'n_api', 'invalid-status');
    expect(result).toBe(SAMPLE_XML);
  });

  it('handles null/empty inputs', () => {
    expect(updateShapeStatus('', 'n_api', 'done')).toBe('');
    expect(updateShapeStatus(null, 'n_api', 'done')).toBeNull();
    expect(updateShapeStatus(SAMPLE_XML, '', 'done')).toBe(SAMPLE_XML);
    expect(updateShapeStatus(SAMPLE_XML, 'n_api', '')).toBe(SAMPLE_XML);
  });

  it('updates in-progress with correct colors', () => {
    const result = updateShapeStatus(SAMPLE_XML, 'n_api', 'in-progress');
    expect(result).toContain('fillColor=#2a2a10');
    expect(result).toContain('strokeColor=#d29922');
  });

  it('updates blocked with correct colors', () => {
    const result = updateShapeStatus(SAMPLE_XML, 'n_db', 'blocked');
    expect(result).toContain('fillColor=#2a1010');
    expect(result).toContain('strokeColor=#f85149');
  });
});

describe('updateMultipleStatuses', () => {
  it('updates multiple nodes in one pass', () => {
    const result = updateMultipleStatuses(SAMPLE_XML, {
      n_api: 'done',
      n_db: 'blocked',
    });
    // n_api should be done colors
    expect(result).toContain('id="n_api"');
    // n_db should be blocked colors
    const dbSection = result.slice(result.indexOf('id="n_db"'));
    expect(dbSection).toContain('fillColor=#2a1010');
  });
});

describe('findMissingNodes', () => {
  it('returns empty when all nodes are present', () => {
    expect(findMissingNodes(SAMPLE_XML, ['n_api', 'n_db'])).toEqual([]);
  });

  it('returns missing node IDs', () => {
    expect(findMissingNodes(SAMPLE_XML, ['n_api', 'n_db', 'n_auth'])).toEqual(['n_auth']);
  });

  it('returns all IDs when XML is empty', () => {
    expect(findMissingNodes('', ['n_api'])).toEqual(['n_api']);
  });

  it('returns all IDs when XML is null', () => {
    expect(findMissingNodes(null, ['n_api', 'n_db'])).toEqual(['n_api', 'n_db']);
  });
});
