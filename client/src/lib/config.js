export const STATUS_COLORS = {
  done: '#10b981', 'in-progress': '#eab308', planned: '#3b82f6',
  blocked: '#f85149', cut: '#8b949e', placeholder: '#64748b',
};

export const DEPTH_COLORS = {
  system: '#5580a8', domain: '#7a5fa0', module: '#3d8a85', 'interface': '#a06830',
};

export function statusColor(status) { return STATUS_COLORS[status] || '#64748b'; }
export function depthColor(depth) { return DEPTH_COLORS[depth] || '#64748b'; }
