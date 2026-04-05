/**
 * Shape Registry — universal shape library for code-canvas.
 *
 * Every shape is a self-contained definition:
 * - style: draw.io/maxGraph style string
 * - width/height: default dimensions
 * - match: function(node) → boolean — when to auto-select this shape
 * - tags: searchable categories
 *
 * To add a new shape:
 * 1. Add it to the appropriate section below
 * 2. Define match() if it should be auto-selected from node properties
 * 3. It's immediately available to all diagrams in all repos
 *
 * To manually assign: set `shape: "shapeName"` on a node's data.
 */

const SHAPES = {};

function register(name, def) {
  SHAPES[name] = { name, ...def };
}

// ── Actors & People ──

register('actor', {
  style: 'shape=actor;whiteSpace=wrap;fontSize=12;fontColor=#e6edf3;',
  width: 40, height: 60,
  tags: ['uml', 'people', 'user'],
  description: 'UML stick figure — users, external systems, personas',
  match: (node) => node.category === 'actor' || node.depth === 'actor',
});

register('persona', {
  style: 'shape=actor;whiteSpace=wrap;fontSize=12;fontColor=#e6edf3;fillColor=#2a1a3a;strokeColor=#bc8cff;',
  width: 40, height: 60,
  tags: ['uml', 'people'],
  description: 'Purple actor — internal user/persona',
  match: () => false, // manual only
});

// ── Infrastructure ──

register('server', {
  style: 'rounded=1;whiteSpace=wrap;fontStyle=1;fontSize=13;fontColor=#e6edf3;arcSize=8;',
  width: 220, height: 60,
  tags: ['infra', 'system', 'backend'],
  description: 'Bold rounded rectangle — servers, APIs, system-level components',
  match: (node) => node.depth === 'system',
});

register('database', {
  style: 'shape=cylinder3;whiteSpace=wrap;boundedLbl=1;backgroundOutline=1;size=12;fontSize=12;fontColor=#e6edf3;fillColor=#1a3320;strokeColor=#3fb950;',
  width: 80, height: 80,
  tags: ['infra', 'data', 'storage'],
  description: 'Cylinder — databases, data stores',
  match: (node) => {
    const l = (node.label || '').toLowerCase();
    return l.includes('database') || l.includes('postgres') || l.includes('mysql')
      || l.includes('mongo') || l.includes('sqlite') || l.includes('dynamo')
      || node.category === 'database' || node.category === 'data-store';
  },
});

register('queue', {
  style: 'shape=process;whiteSpace=wrap;fontSize=12;fontColor=#e6edf3;fillColor=#2a2a10;strokeColor=#d29922;size=0.15;',
  width: 120, height: 50,
  tags: ['infra', 'async', 'messaging'],
  description: 'Process shape — message queues, event buses',
  match: (node) => {
    const l = (node.label || '').toLowerCase();
    return l.includes('queue') || l.includes('rabbit') || l.includes('kafka')
      || l.includes('sqs') || l.includes('pubsub') || node.category === 'queue';
  },
});

register('cache', {
  style: 'shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;fontSize=12;fontColor=#e6edf3;fillColor=#1e2a3a;strokeColor=#58a6ff;size=0.2;',
  width: 100, height: 55,
  tags: ['infra', 'performance'],
  description: 'Hexagon — caches, CDNs, fast lookup stores',
  match: (node) => {
    const l = (node.label || '').toLowerCase();
    return l.includes('cache') || l.includes('redis') || l.includes('memcache')
      || l.includes('cdn') || node.category === 'cache';
  },
});

register('cloud', {
  style: 'shape=cloud;whiteSpace=wrap;fontSize=12;fontColor=#e6edf3;fillColor=#1e2a3a;strokeColor=#8b949e;',
  width: 120, height: 70,
  tags: ['infra', 'external', 'service'],
  description: 'Cloud shape — external services, third-party APIs',
  match: (node) => node.category === 'external' || node.category === 'cloud',
});

// ── Domain & Logic ──

register('domain', {
  style: 'rounded=1;whiteSpace=wrap;fontStyle=1;fontSize=13;fontColor=#e6edf3;',
  width: 200, height: 60,
  tags: ['domain', 'business', 'core'],
  description: 'Bold rounded rectangle — domain/business logic components',
  match: (node) => node.depth === 'domain',
});

register('module', {
  style: 'rounded=1;whiteSpace=wrap;fontSize=12;fontColor=#e6edf3;',
  width: 180, height: 50,
  tags: ['module', 'component'],
  description: 'Standard rounded rectangle — modules, components',
  match: (node) => node.depth === 'module',
});

register('interface', {
  style: 'rounded=1;whiteSpace=wrap;fontSize=12;fontColor=#e6edf3;dashed=1;',
  width: 160, height: 45,
  tags: ['interface', 'api', 'contract'],
  description: 'Dashed rounded rectangle — interfaces, contracts, boundaries',
  match: (node) => node.depth === 'interface',
});

// ── UML ──

register('usecase', {
  style: 'ellipse;whiteSpace=wrap;fontSize=12;fontColor=#e6edf3;fillColor=#1e2a3a;strokeColor=#58a6ff;',
  width: 160, height: 70,
  tags: ['uml', 'use-case'],
  description: 'Ellipse — UML use cases',
  match: (node) => node.category === 'use-case',
});

register('package', {
  style: 'shape=folder;whiteSpace=wrap;fontSize=13;fontColor=#e6edf3;fontStyle=1;tabWidth=110;tabHeight=20;tabPosition=left;fillColor=#161b22;strokeColor=#30363d;',
  width: 240, height: 150,
  tags: ['uml', 'container', 'package'],
  description: 'Folder/package — UML packages, namespaces, groupings',
  match: (node) => node.category === 'package' || node.category === 'container',
});

register('class', {
  style: 'swimlane;fontStyle=1;align=center;startSize=26;fontSize=12;fontColor=#e6edf3;fillColor=#1e2a3a;strokeColor=#58a6ff;childLayout=stackLayout;horizontal=1;startSize=30;horizontalStack=0;resizeParent=1;resizeParentMax=0;collapsible=0;marginBottom=0;',
  width: 180, height: 90,
  tags: ['uml', 'class', 'oop'],
  description: 'UML class box — classes with compartments',
  match: (node) => node.category === 'class',
});

// ── Flow & State ──

register('decision', {
  style: 'rhombus;whiteSpace=wrap;fontSize=11;fontColor=#e6edf3;fillColor=#2a2a10;strokeColor=#d29922;',
  width: 80, height: 80,
  tags: ['flow', 'decision', 'branch'],
  description: 'Diamond — decision points, conditionals, branches',
  match: (node) => node.category === 'decision',
});

register('start', {
  style: 'ellipse;whiteSpace=wrap;fontSize=11;fontColor=#e6edf3;fillColor=#1a3320;strokeColor=#3fb950;aspect=fixed;',
  width: 40, height: 40,
  tags: ['flow', 'state', 'start'],
  description: 'Small circle — start/initial state',
  match: (node) => node.category === 'start',
});

register('end', {
  style: 'ellipse;whiteSpace=wrap;fontSize=11;fontColor=#e6edf3;fillColor=#2a1010;strokeColor=#f85149;aspect=fixed;strokeWidth=3;',
  width: 40, height: 40,
  tags: ['flow', 'state', 'end'],
  description: 'Bold circle — end/terminal state',
  match: (node) => node.category === 'end',
});

register('process', {
  style: 'rounded=1;whiteSpace=wrap;fontSize=12;fontColor=#e6edf3;arcSize=20;',
  width: 160, height: 50,
  tags: ['flow', 'process', 'step'],
  description: 'Rounded rectangle — process steps, actions',
  match: (node) => node.category === 'process' || node.category === 'step',
});

register('state', {
  style: 'rounded=1;whiteSpace=wrap;fontSize=12;fontColor=#e6edf3;arcSize=40;',
  width: 140, height: 50,
  tags: ['state', 'lifecycle'],
  description: 'Highly rounded rectangle — states in a state machine',
  match: (node) => node.category === 'state',
});

// ── Documents & Files ──

register('document', {
  style: 'shape=document;whiteSpace=wrap;fontSize=12;fontColor=#e6edf3;fillColor=#1e2a3a;strokeColor=#58a6ff;boundedLbl=1;size=0.15;',
  width: 120, height: 70,
  tags: ['document', 'file', 'spec'],
  description: 'Document shape — specs, configs, documentation',
  match: (node) => node.category === 'document' || node.category === 'spec',
});

register('file', {
  style: 'shape=note;whiteSpace=wrap;fontSize=11;fontColor=#e6edf3;fillColor=#161b22;strokeColor=#30363d;backgroundOutline=1;size=14;',
  width: 100, height: 60,
  tags: ['file', 'source'],
  description: 'Note shape — source files, scripts',
  match: (node) => node.category === 'file',
});

// ── Swimlanes & Containers ──

register('swimlane', {
  style: 'swimlane;startSize=35;fontSize=14;fontStyle=1;fontColor=#e6edf3;fillColor=#0d1117;strokeColor=#30363d;swimlaneLine=1;collapsible=0;',
  width: 400, height: 200,
  tags: ['container', 'swimlane', 'layer'],
  description: 'Horizontal swimlane — for grouping related components into layers',
  match: () => false, // always manual
});

register('group', {
  style: 'rounded=1;whiteSpace=wrap;fontSize=13;fontStyle=1;fontColor=#e6edf3;fillColor=#0d1117;strokeColor=#30363d;dashed=1;dashPattern=5 5;verticalAlign=top;spacingTop=10;container=1;collapsible=0;',
  width: 300, height: 180,
  tags: ['container', 'group', 'boundary'],
  description: 'Dashed container — logical grouping, bounded context',
  match: () => false, // always manual
});

// ═══════════════════════════════════════════════
// PUBLIC API
// ═══════════════════════════════════════════════

/**
 * Get a shape definition by name.
 */
export function getShapeByName(name) {
  return SHAPES[name] || null;
}

/**
 * Auto-select the best shape for a node based on its properties.
 * Checks match() functions in priority order.
 * Falls back to depth-based default.
 */
export function getShapeForNode(node) {
  // 1. Explicit shape override
  if (node.shape && SHAPES[node.shape]) return SHAPES[node.shape];

  // 2. Auto-match (specific shapes first — database, queue, cache, etc.)
  const specific = ['database', 'queue', 'cache', 'cloud', 'actor', 'usecase',
    'decision', 'start', 'end', 'process', 'state', 'document', 'class', 'package'];
  for (const name of specific) {
    if (SHAPES[name].match(node)) return SHAPES[name];
  }

  // 3. Fall back to depth-based
  const depthMap = { system: 'server', domain: 'domain', module: 'module', interface: 'interface' };
  const fallback = depthMap[node.depth];
  if (fallback && SHAPES[fallback]) return SHAPES[fallback];

  // 4. Ultimate fallback
  return SHAPES.module;
}

/**
 * List all registered shapes.
 */
export function listShapes() {
  return Object.values(SHAPES);
}

/**
 * Search shapes by tag.
 */
export function findShapesByTag(tag) {
  return Object.values(SHAPES).filter(s => s.tags.includes(tag));
}

/**
 * Get the style string for a node, with status colors applied.
 */
export function getStyledShape(node) {
  const shape = getShapeForNode(node);
  let style = shape.style;

  // Apply status-based colors
  const STATUS_FILLS = {
    done:          { fill: '#1a3320', stroke: '#3fb950' },
    'in-progress': { fill: '#2a2a10', stroke: '#d29922' },
    planned:       { fill: '#1e2a3a', stroke: '#58a6ff' },
    blocked:       { fill: '#2a1010', stroke: '#f85149' },
    cut:           { fill: '#1a1a1a', stroke: '#8b949e' },
    placeholder:   { fill: '#1a1a1a', stroke: '#484f58' },
  };

  const colors = STATUS_FILLS[node.status];
  if (colors) {
    style = setStyleProp(style, 'fillColor', colors.fill);
    style = setStyleProp(style, 'strokeColor', colors.stroke);
  }

  return { ...shape, style, width: shape.width, height: shape.height };
}

function setStyleProp(style, prop, value) {
  const needle = prop + '=';
  const idx = style.indexOf(needle);
  if (idx !== -1) {
    const valStart = idx + needle.length;
    let valEnd = style.indexOf(';', valStart);
    if (valEnd === -1) valEnd = style.length;
    return style.slice(0, valStart) + value + style.slice(valEnd);
  }
  const sep = style.endsWith(';') ? '' : ';';
  return style + sep + prop + '=' + value + ';';
}
