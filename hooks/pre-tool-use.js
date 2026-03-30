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
    context = '## Design Canvas — Empty\n\nA design canvas exists but has no nodes yet. Use `/canvas generate` to analyze the codebase and create an architecture diagram before planning.';
  }

  process.stdout.write(JSON.stringify({
    hookSpecificOutput: { hookEventName: 'PreToolUse', additionalContext: context },
  }));
}

try { main(); } catch { process.stdout.write('{}'); }
