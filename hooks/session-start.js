#!/usr/bin/env node
import { findProjectDir, readEvents, replayState, generateL0, ensureServer } from './lib/canvas-client.js';

const pluginRoot = process.env.CLAUDE_PLUGIN_ROOT || new URL('..', import.meta.url).pathname;

async function main() {
  const projectDir = findProjectDir();
  if (!projectDir) { process.stdout.write('{}'); return; }

  const events = readEvents(projectDir);
  const state = replayState(events);
  const l0 = generateL0(state);

  let serverUrl = '';
  try {
    const url = await ensureServer(projectDir, pluginRoot);
    serverUrl = url || '(server failed to start — run `npm start` in plugin dir to diagnose)';
  } catch {
    serverUrl = '(server failed to start)';
  }

  const context = `## Code Canvas Active\n\n${l0}\n\n### Commands\n- \`/canvas\` — Open canvas in browser\n- \`/canvas generate\` — Generate canvas from spec/codebase\n- \`/canvas update\` — Sync canvas with implementation progress\n- \`/canvas diff [since]\` — Show changes since timestamp\n- \`/canvas comments\` — List unresolved comments\n- \`/canvas story\` — Decision history narrative\n- \`/canvas export md\` — Export as markdown\n\n### API\nServer: ${serverUrl}\nPOST /api/events — append event (JSON body with {type, actor, data})\nPOST /api/events/batch — append multiple events (JSON array)\nGET /api/events — fetch all events\nGET /api/state — current state (?level=L0|L1)\n\n### Proactive Canvas Maintenance\nAfter completing significant work, update the canvas:\n- Change node statuses to reflect progress\n- Record decisions with alternatives and reasoning (decision.recorded events)\n- Update file patterns when creating/restructuring files\n- Add comments noting deviations from the plan`;

  process.stdout.write(JSON.stringify({
    hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: context },
  }));
}

main().catch(() => { process.stdout.write('{}'); });
