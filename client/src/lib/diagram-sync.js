/**
 * Keeps diagram XML in sync with node state.
 *
 * When a node's status changes, this updates the shape's fill color
 * in the drawio XML so the diagram reflects current state without
 * requiring a full regeneration.
 *
 * Uses string operations instead of dynamic RegExp to avoid ReDoS concerns.
 */

const STATUS_FILLS = {
  done:          { fill: '#1a3320', stroke: '#3fb950' },
  'in-progress': { fill: '#2a2a10', stroke: '#d29922' },
  planned:       { fill: '#1e2a3a', stroke: '#58a6ff' },
  blocked:       { fill: '#2a1010', stroke: '#f85149' },
  cut:           { fill: '#1a1a1a', stroke: '#8b949e' },
  placeholder:   { fill: '#1a1a1a', stroke: '#484f58' },
};

/**
 * Update the fill/stroke color of a shape in drawio XML to match its node status.
 * Returns the updated XML string, or the original if the shape wasn't found.
 */
export function updateShapeStatus(xml, nodeId, status) {
  if (!xml || !nodeId || !status) return xml;
  const colors = STATUS_FILLS[status];
  if (!colors) return xml;

  // Find the mxCell with this exact id using string search (no dynamic regex)
  const idAttr = `id="${nodeId}"`;
  const cellIdx = xml.indexOf(idAttr);
  if (cellIdx === -1) return xml;

  // Find the style attribute for this cell
  // Look backwards for <mxCell and forwards for the style=""
  const cellStart = xml.lastIndexOf('<mxCell', cellIdx);
  if (cellStart === -1) return xml;

  // Find the closing > of this cell tag (or /> for self-closing)
  const cellEnd = xml.indexOf('>', cellIdx);
  if (cellEnd === -1) return xml;

  // Extract the cell tag substring
  const cellTag = xml.slice(cellStart, cellEnd + 1);

  // Only update vertex cells (shapes), not edge cells
  if (!cellTag.includes('vertex="1"')) return xml;

  // Find and update the style attribute within this cell tag
  const styleStart = cellTag.indexOf('style="');
  if (styleStart === -1) return xml;
  const styleValStart = styleStart + 7; // length of 'style="'
  const styleValEnd = cellTag.indexOf('"', styleValStart);
  if (styleValEnd === -1) return xml;

  let style = cellTag.slice(styleValStart, styleValEnd);
  style = setStyleProp(style, 'fillColor', colors.fill);
  style = setStyleProp(style, 'strokeColor', colors.stroke);

  const updatedTag = cellTag.slice(0, styleValStart) + style + cellTag.slice(styleValEnd);
  return xml.slice(0, cellStart) + updatedTag + xml.slice(cellEnd + 1);
}

/**
 * Batch update multiple node statuses in one XML string.
 */
export function updateMultipleStatuses(xml, statusMap) {
  let result = xml;
  for (const [nodeId, status] of Object.entries(statusMap)) {
    result = updateShapeStatus(result, nodeId, status);
  }
  return result;
}

/**
 * Check which node IDs from the store are missing from a view's XML.
 * Returns an array of missing node IDs.
 */
export function findMissingNodes(xml, nodeIds) {
  if (!xml) return [...nodeIds];
  const missing = [];
  for (const id of nodeIds) {
    if (!xml.includes(`id="${id}"`)) missing.push(id);
  }
  return missing;
}

/**
 * Set a style property value using string operations (no regex).
 */
function setStyleProp(style, prop, value) {
  const needle = prop + '=';
  const idx = style.indexOf(needle);
  if (idx !== -1) {
    // Find the end of this property (next ; or end of string)
    const valStart = idx + needle.length;
    let valEnd = style.indexOf(';', valStart);
    if (valEnd === -1) valEnd = style.length;
    return style.slice(0, valStart) + value + style.slice(valEnd);
  }
  // Property doesn't exist — append it
  const sep = style.endsWith(';') ? '' : ';';
  return style + sep + prop + '=' + value + ';';
}
