#!/usr/bin/env node
import {
  findProjectDir, findGitRoot, initCanvasDir,
  readEvents, replayState, generateL0, ensureServer,
} from './lib/canvas-client.js';

const pluginRoot = process.env.CLAUDE_PLUGIN_ROOT || new URL('..', import.meta.url).pathname;

async function main() {
  // Find existing .code-canvas/ or bootstrap one at git root
  let projectDir = findProjectDir();
  if (!projectDir) {
    const gitRoot = findGitRoot();
    if (!gitRoot) { process.stdout.write('{}'); return; }
    projectDir = initCanvasDir(gitRoot);
  }

  const events = readEvents(projectDir);
  const state = replayState(events);
  const isEmpty = state.nodes.size === 0;

  // Always start the server
  let serverUrl = '';
  try {
    const url = await ensureServer(projectDir, pluginRoot);
    serverUrl = url || '(server failed to start)';
  } catch {
    serverUrl = '(server failed to start)';
  }

  const l0 = isEmpty
    ? 'Canvas is empty — no nodes yet.'
    : generateL0(state);

  const bootstrap = isEmpty
    ? `\n\n### Getting Started\nThis project has an empty design canvas. To populate it:\n1. Use \`/canvas generate\` to analyze the codebase and create an architecture diagram\n2. Or start manually: POST node/edge/view events to the API below\n\nThe canvas will automatically track your work once nodes have \`files\` patterns mapped to source files.`
    : '';

  const context = `## Code Canvas Active

${l0}${bootstrap}

### Commands
- \`/canvas\` — Open canvas in browser
- \`/canvas generate\` — Generate canvas from spec/codebase
- \`/canvas update\` — Sync canvas with implementation progress
- \`/canvas diff [since]\` — Show changes since timestamp
- \`/canvas comments\` — List unresolved comments
- \`/canvas story\` — Decision history narrative
- \`/canvas export md\` — Export as markdown

### API
Server: ${serverUrl}
POST /api/events — append event (JSON body with {type, actor, data})
POST /api/events/batch — append multiple events (JSON array)
GET /api/events — fetch all events
GET /api/state — current state (?level=L0|L1)

### Proactive Canvas Maintenance
After completing significant work, update the canvas:
- Change node statuses to reflect progress
- Record decisions with alternatives and reasoning (decision.recorded events)
- Update file patterns when creating/restructuring files
- Add comments noting deviations from the plan`;

  process.stdout.write(JSON.stringify({
    hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: context },
  }));
}

main().catch(() => { process.stdout.write('{}'); });
