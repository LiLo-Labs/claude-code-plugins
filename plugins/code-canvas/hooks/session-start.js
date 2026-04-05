#!/usr/bin/env node
import {
  findProjectDir,
  readEvents, replayState, generateL0, ensureServer,
} from './lib/canvas-client.js';

const pluginRoot = process.env.CLAUDE_PLUGIN_ROOT || new URL('..', import.meta.url).pathname;

async function main() {
  // Only activate if this project already has a .code-canvas/ directory.
  // Don't auto-create — let /canvas generate handle bootstrap.
  const projectDir = findProjectDir();

  if (!projectDir) {
    // No canvas yet — just tell Claude the commands exist
    const context = `## Code Canvas Available

Use \`/canvas generate\` to create a design canvas for this project. The canvas maps architecture, decisions, and progress as an interactive diagram.`;

    process.stdout.write(JSON.stringify({
      hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: context },
    }));
    return;
  }

  // Canvas exists — full context injection
  const events = readEvents(projectDir);
  const state = replayState(events);
  const isEmpty = state.nodes.size === 0;

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
    ? `\n\n### Getting Started\nUse \`/canvas generate\` to analyze the codebase and create an architecture diagram.\n\nWhen generating:\n- Each tab tells a story (data flow, components, deployment) — don't dump everything on one tab\n- Every node on a tab MUST have at least one edge — no floating nodes\n- Include a \`description\` on each view explaining what the diagram shows\n- Set real statuses with node.status events (default is "planned")\n- Include \`files\` glob patterns on nodes so edits auto-track progress\n- Keep tabs focused: 4-8 nodes ideal, connected nodes adjacent`
    : '';

  // Gather unresolved comments
  const unresolvedComments = state.comments.filter(c => !c.resolved);
  const commentsSection = unresolvedComments.length > 0
    ? `\n\n### Unresolved Comments (${unresolvedComments.length})\n` +
      unresolvedComments.map(c => `- **${c.targetLabel || c.target}**: "${c.text}" (${c.actor})`).join('\n')
    : '';

  // Gather recent decisions
  const recentDecisions = state.decisions.slice(-3);
  const decisionsSection = recentDecisions.length > 0
    ? `\n\n### Recent Decisions\n` +
      recentDecisions.map(d => `- **${d.nodeId}**: Chose "${d.chosen}" over ${d.alternatives.join(', ')} — ${d.reason}`).join('\n')
    : '';

  // List views with descriptions
  const viewsSection = state.views.length > 0
    ? `\n\n### Diagram Views\n` +
      state.views.map(v => `- **${v.name}**: ${v.description || '(no description)'}`).join('\n')
    : '';

  const context = `## Code Canvas Active

${l0}${bootstrap}${commentsSection}${decisionsSection}${viewsSection}

### Commands
- \`/canvas\` — Open canvas in browser
- \`/canvas generate\` — Generate canvas from spec/codebase
- \`/canvas update\` — Sync canvas with implementation progress
- \`/canvas comments\` — List unresolved comments
- \`/canvas story\` — Decision history narrative

### API
Server: ${serverUrl}
POST /api/events — append event (JSON body with {type, actor, data})
POST /api/events/batch — append multiple events (JSON array)
GET /api/state — current state (?level=L0|L1)

### Canvas Maintenance
After completing significant work, update the canvas:
- Change node statuses to reflect progress
- Record decisions with alternatives and reasoning (decision.recorded events)
- Update file patterns when creating/restructuring files
- Add comments noting deviations from the plan
- When making draw.io XML changes, use node IDs that match semantic node IDs (n_<slug>)

**IMPORTANT: The post-tool-use hook will alert you when files are edited that don't match any canvas node. When you see "Canvas: untracked file" — you MUST create a node for it and add it to the relevant diagram view. Every source file should be tracked by a node.**

### Status Line
To show canvas status in your Claude Code prompt, add to \`.claude/settings.json\`:
\`\`\`json
{"statusLine":{"type":"command","command":"bash \\"${pluginRoot}/hooks/statusline.sh\\""}}
\`\`\``;

  process.stdout.write(JSON.stringify({
    hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: context },
  }));
}

main().catch(() => { process.stdout.write('{}'); });
