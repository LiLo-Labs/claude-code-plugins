/**
 * Shared configuration for the canvas rendering system.
 * All sizing, spacing, and color values in one place.
 * Components import from here — no hardcoded values anywhere else.
 */

// ── Node Dimensions ──
export const NODE = {
  minWidth: 200,
  maxWidth: 360,
  paddingX: 20,
  paddingY: 16,
  titleSize: 14,
  subtitleSize: 11,
  borderRadius: 10,
  charWidth: 7.5,  // approximate px per character for width calculation
};

// ── Container Dimensions ──
export const CONTAINER = {
  headerHeight: 44,
  padding: 36,
  borderRadius: 14,
  headerFontSize: 14,
  tintOpacity: 0.05,
  tintOpacityHighlight: 0.1,
  borderOpacity: 0.25,
  borderOpacityHighlight: 0.5,
};

// ── Spacing ──
export const SPACING = {
  siblingGapH: 64,    // horizontal gap between siblings (generous)
  siblingGapV: 36,    // vertical gap between siblings (inside containers)
  topLevelGap: 80,    // gap between top-level nodes
  edgePadding: 60,    // canvas edge padding
};

// ── Edge Rendering ──
export const EDGE = {
  strokeWidth: 2,
  opacity: 0.65,
  labelFontSize: 11,
  labelPaddingX: 14,
  labelPaddingY: 6,
  labelRadius: 10,
  arrowWidth: 10,
  arrowHeight: 7,
};

// ── Depth Colors (desaturated accents for badges, dots) ──
export const DEPTH_COLORS = {
  system: '#5580a8',
  domain: '#7a5fa0',
  module: '#3d8a85',
  'interface': '#a06830',
};

// ── Depth Background Colors (barely off canvas #0f1117, subtle tint) ──
export const DEPTH_BG_COLORS = {
  system: '#141928',
  domain: '#1a1422',
  module: '#121d1c',
  'interface': '#1e1510',
};

// ── Depth Text Colors (muted, readable, not neon) ──
export const DEPTH_TEXT_COLORS = {
  system: '#7d9ec0',
  domain: '#9e87c2',
  module: '#6ba3a0',
  'interface': '#b89060',
};

// ── Status Colors ──
export const STATUS_COLORS = {
  done: '#10b981',
  'in-progress': '#eab308',
  planned: '#3b82f6',
  placeholder: '#64748b',
};

// ── Depth Tint Colors (for container backgrounds) ──
export const DEPTH_TINTS = {
  system: { r: 59, g: 130, b: 246 },
  domain: { r: 168, g: 85, b: 247 },
  module: { r: 20, g: 184, b: 166 },
  'interface': { r: 249, g: 115, b: 22 },
};

/**
 * Get the depth color for a node, with fallback.
 */
export function depthColor(depth) {
  return DEPTH_COLORS[depth] || '#64748b';
}

/**
 * Get the status color for a node, with fallback.
 */
export function statusColor(status) {
  return STATUS_COLORS[status] || '#64748b';
}

/**
 * Get an rgba tint string for container backgrounds.
 */
export function depthTint(depth, opacity) {
  const c = DEPTH_TINTS[depth] || { r: 100, g: 100, b: 100 };
  return `rgba(${c.r},${c.g},${c.b},${opacity})`;
}

/**
 * Estimate node width from its content.
 */
export function estimateNodeWidth(label, subtitle) {
  const titleW = (label || '').length * NODE.charWidth + NODE.paddingX * 2;
  const subW = (subtitle || '').length * (NODE.charWidth * 0.8) + NODE.paddingX * 2;
  const contentW = Math.max(titleW, subW);
  return Math.max(NODE.minWidth, Math.min(NODE.maxWidth, contentW));
}

/**
 * Compute node height based on whether it has a subtitle.
 */
export function estimateNodeHeight(subtitle) {
  const base = NODE.paddingY * 2 + NODE.titleSize;
  if (subtitle) return base + NODE.subtitleSize + 6; // 6px gap between title and subtitle
  return base;
}
