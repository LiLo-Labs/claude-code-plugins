#!/usr/bin/env node
import { findProjectDir, readEvents, replayState, generateL1 } from './lib/canvas-client.js';

function main() {
  const projectDir = findProjectDir();
  if (!projectDir) { process.stdout.write('{}'); return; }

  const events = readEvents(projectDir);
  const state = replayState(events);

  let context;
  if (state.nodes.size > 0) {
    const l1 = generateL1(state);
    context = `## Design Canvas — Current Structure\n\n${l1}\n\nReview this structure before planning. Use \`/canvas\` to open in browser.`;
  } else {
    context = 'This project has a design canvas but it\'s empty. Use `/canvas generate` to populate it from a spec or codebase analysis.';
  }

  process.stdout.write(JSON.stringify({
    hookSpecificOutput: { hookEventName: 'PreToolUse', additionalContext: context },
  }));
}

try { main(); } catch { process.stdout.write('{}'); }
