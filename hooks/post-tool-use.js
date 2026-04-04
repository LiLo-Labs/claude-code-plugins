#!/usr/bin/env node
import { findProjectDir, readEvents, replayState, findNodesForFile, ensureServer, postEvent } from './lib/canvas-client.js';

const pluginRoot = process.env.CLAUDE_PLUGIN_ROOT || new URL('..', import.meta.url).pathname;

async function main() {
  let input = '';
  for await (const chunk of process.stdin) input += chunk;

  let toolResult;
  try { toolResult = JSON.parse(input); } catch { return; }

  const filePath = toolResult?.tool_input?.file_path
    || toolResult?.tool_input?.path
    || toolResult?.file_path
    || null;
  if (!filePath) return;

  const projectDir = findProjectDir();
  if (!projectDir) return;

  const events = readEvents(projectDir);
  const state = replayState(events);

  const relative = filePath.startsWith(projectDir)
    ? filePath.slice(projectDir.length + 1)
    : filePath;

  // Skip non-source files
  if (relative.startsWith('.code-canvas/') || relative.startsWith('node_modules/')) return;

  const matchingNodes = findNodesForFile(relative, state.nodes);

  // Auto-transition planned → in-progress for matched nodes
  const toUpdate = matchingNodes.filter(id => {
    const node = state.nodes.get(id);
    return node && node.status === 'planned';
  });

  if (toUpdate.length > 0) {
    const serverUrl = await ensureServer(projectDir, pluginRoot);
    if (serverUrl) {
      for (const nodeId of toUpdate) {
        await postEvent(serverUrl, {
          type: 'node.status',
          actor: 'system',
          data: { nodeId, status: 'in-progress', prev: 'planned' },
        });
      }
    }
  }

  // Build context with actionable instructions
  const parts = [];

  if (matchingNodes.length > 0) {
    const labels = matchingNodes.map(id => {
      const node = state.nodes.get(id);
      return node ? `${node.label} (${id})` : id;
    });
    parts.push(`Canvas: \`${relative}\` → ${labels.join(', ')}`);
    if (toUpdate.length > 0) {
      parts.push(`Auto-updated ${toUpdate.length} node(s) to in-progress.`);
    }
  }

  // CRITICAL: Detect untracked files and instruct Claude to act
  if (matchingNodes.length === 0 && state.nodes.size > 0) {
    const slug = relative.replace(/[^a-zA-Z0-9]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '').toLowerCase();
    parts.push(
      `**Canvas: untracked file \`${relative}\`** — no node covers this file.`,
      `ACTION REQUIRED: Create a node for this file by POSTing to the canvas API:`,
      `\`\`\``,
      `curl -X POST "$(cat .code-canvas/.server-info | node -e "console.log(JSON.parse(require('fs').readFileSync('/dev/stdin','utf8')).url)")/api/events" \\`,
      `  -H 'Content-Type: application/json' \\`,
      `  -d '{"type":"node.created","actor":"claude","data":{"nodeId":"n_${slug}","label":"<descriptive name>","subtitle":"<what this file does>","depth":"module","category":"arch","status":"in-progress","files":["${relative}"]}}'`,
      `\`\`\``,
      `Then update the relevant view's drawioXml to include this node.`,
    );
  }

  // Surface unresolved user comments
  const userComments = state.comments.filter(c => !c.resolved && c.actor === 'user');
  if (userComments.length > 0) {
    parts.push(
      `Canvas comments (${userComments.length}): ` +
      userComments.map(c => `"${c.text}" on ${c.targetLabel || c.target}`).join('; ')
    );
  }

  if (parts.length > 0) {
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: { hookEventName: 'PostToolUse', additionalContext: parts.join('\n') },
    }));
  }
}

main().catch(() => {});
