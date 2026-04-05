/**
 * svg-renderer.js — draw.io XML parser and serializer
 *
 * Pure functions with no runtime dependencies.
 * XML parsing uses regex rather than DOMParser so the module works in both
 * browser and Node.js (vitest) environments without jsdom.
 */

/**
 * Parse a draw.io semicolon-delimited style string into a plain object.
 * Bare tokens without '=' are treated as truthy flags with value "1".
 *
 * @param {string|undefined} str
 * @returns {Record<string, string>}
 */
export function parseStyle(str) {
  if (!str) return {};
  const result = {};
  for (const token of str.split(';')) {
    const trimmed = token.trim();
    if (!trimmed) continue;
    const eqIdx = trimmed.indexOf('=');
    if (eqIdx === -1) {
      result[trimmed] = '1';
    } else {
      result[trimmed.slice(0, eqIdx)] = trimmed.slice(eqIdx + 1);
    }
  }
  return result;
}

/**
 * Serialize a style object back to a draw.io style string.
 *
 * @param {Record<string, string>} obj
 * @returns {string}
 */
export function styleToString(obj) {
  if (!obj) return '';
  return Object.entries(obj)
    .map(([k, v]) => `${k}=${v}`)
    .join(';') + ';';
}

/**
 * Escape a value for use as an XML attribute.
 *
 * @param {string} str
 * @returns {string}
 */
function escapeXmlAttr(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Decode XML attribute entities back to plain text.
 *
 * @param {string} str
 * @returns {string}
 */
function decodeXmlAttr(str) {
  return str
    .replace(/&#xa;/gi, '\n')
    .replace(/&#10;/g, '\n')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'");
}

/**
 * Extract all attribute key/value pairs from a tag string.
 * Handles double-quoted values (standard in draw.io XML).
 *
 * @param {string} tag  e.g. `id="n_1" value="Hello" vertex="1"`
 * @returns {Record<string, string>}
 */
function parseAttrs(tag) {
  const attrs = {};
  const re = /(\w[\w:.-]*)\s*=\s*"([^"]*)"/g;
  let m;
  while ((m = re.exec(tag)) !== null) {
    attrs[m[1]] = m[2];
  }
  return attrs;
}

/**
 * Parse draw.io XML into { cells: Map, edges: Map }.
 *
 * cells Map values: { id, value, x, y, width, height, style }
 * edges Map values: { id, value, source, target, style, points }
 *
 * @param {string} xmlStr
 * @returns {{ cells: Map<string, object>, edges: Map<string, object> }}
 */
export function parseDrawioXml(xmlStr) {
  const empty = { cells: new Map(), edges: new Map() };
  if (!xmlStr || !xmlStr.trim()) return empty;

  const cells = new Map();
  const edges = new Map();

  // Match <mxCell … /> (self-closing) or <mxCell …>…</mxCell> (with children).
  // Self-closing is listed first so the alternation resolves correctly.
  // Attribute chars exclude '/' so a self-closing tag is not mis-parsed as open.
  const cellBlockRe = /<mxCell\b((?:[^>"'/]|"[^"]*")*)\s*\/>|<mxCell\b((?:[^>"'/]|"[^"]*")*)\s*>([\s\S]*?)<\/mxCell>/g;

  let m;
  while ((m = cellBlockRe.exec(xmlStr)) !== null) {
    const attrStr = m[1] !== undefined ? m[1] : m[2];
    const innerXml = m[3] || '';

    const attrs = parseAttrs(attrStr);
    const id = attrs.id;
    if (!id || id === '0' || id === '1') continue;

    const value = decodeXmlAttr(attrs.value || '');
    const style = parseStyle(attrs.style || '');

    if (attrs.vertex === '1') {
      const geoMatch = /<mxGeometry\b((?:[^>"']|"[^"]*")*)\/?>/.exec(innerXml);
      const geoAttrs = geoMatch ? parseAttrs(geoMatch[1]) : {};
      const x = parseFloat(geoAttrs.x || '0') || 0;
      const y = parseFloat(geoAttrs.y || '0') || 0;
      const width = geoAttrs.width !== undefined ? (parseFloat(geoAttrs.width) || 120) : 120;
      const height = geoAttrs.height !== undefined ? (parseFloat(geoAttrs.height) || 60) : 60;

      cells.set(id, { id, value, x, y, width, height, style });
    } else if (attrs.edge === '1') {
      const source = attrs.source || '';
      const target = attrs.target || '';

      // Collect waypoints from <Array as="points"><mxPoint …/></Array>
      const points = [];
      const arrayMatch = /<Array[^>]*as="points"[^>]*>([\s\S]*?)<\/Array>/.exec(innerXml);
      if (arrayMatch) {
        const ptRe = /<mxPoint\b((?:[^>"']|"[^"]*")*)\s*\/>/g;
        let pm;
        while ((pm = ptRe.exec(arrayMatch[1])) !== null) {
          const ptAttrs = parseAttrs(pm[1]);
          points.push({
            x: parseFloat(ptAttrs.x || '0') || 0,
            y: parseFloat(ptAttrs.y || '0') || 0,
          });
        }
      }

      edges.set(id, { id, value, source, target, style, points });
    }
  }

  return { cells, edges };
}

/**
 * Serialize cells and edges back to a draw.io XML string.
 *
 * @param {Map<string, object>} cells
 * @param {Map<string, object>} edges
 * @returns {string}
 */
export function serializeToXml(cells, edges) {
  const parts = [
    '<mxGraphModel>',
    '<root>',
    '<mxCell id="0"/>',
    '<mxCell id="1" parent="0"/>',
  ];

  for (const cell of cells.values()) {
    const value = escapeXmlAttr(cell.value.replace(/\n/g, '&#xa;'));
    const style = escapeXmlAttr(styleToString(cell.style));
    const x = cell.x ?? 0;
    const y = cell.y ?? 0;
    const width = cell.width ?? 120;
    const height = cell.height ?? 60;

    parts.push(
      `<mxCell id="${escapeXmlAttr(cell.id)}" value="${value}" style="${style}" vertex="1" parent="1">` +
      `<mxGeometry x="${x}" y="${y}" width="${width}" height="${height}" as="geometry"/>` +
      `</mxCell>`
    );
  }

  for (const edge of edges.values()) {
    const value = escapeXmlAttr(edge.value || '');
    const style = escapeXmlAttr(styleToString(edge.style));
    const source = escapeXmlAttr(edge.source || '');
    const target = escapeXmlAttr(edge.target || '');

    parts.push(
      `<mxCell id="${escapeXmlAttr(edge.id)}" value="${value}" style="${style}" edge="1" source="${source}" target="${target}" parent="1">` +
      `<mxGeometry relative="1" as="geometry"/>` +
      `</mxCell>`
    );
  }

  parts.push('</root>', '</mxGraphModel>');
  return parts.join('');
}
