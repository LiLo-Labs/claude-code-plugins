/**
 * Rendering hints — composable visual properties for views.
 * Claude picks hints when creating views; the renderer reads them.
 * All hints have sensible defaults so existing views render unchanged.
 */

export const DEFAULTS = {
  layout: 'grid',
  nodeShape: 'card',
  nodeSize: 'standard',
  nodeContent: ['label', 'subtitle'],
  edgeStyle: 'curve',
  edgeLabels: 'pill',
};

/**
 * Merge view-level hints with defaults.
 * Only properties in DEFAULTS get defaulted — unknown hints pass through.
 */
export function resolveHints(rendering = {}) {
  return {
    ...DEFAULTS,
    ...rendering,
  };
}
