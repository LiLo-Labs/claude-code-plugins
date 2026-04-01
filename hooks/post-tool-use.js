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

  const matchingNodes = findNodesForFile(relative, state.nodes);
  if (matchingNodes.length === 0) return;

  const toUpdate = matchingNodes.filter(id => {
    const node = state.nodes.get(id);
    return node && node.status === 'planned';
  });

  // Build context about which nodes this file touches
  const touchedLabels = matchingNodes.map(id => {
    const node = state.nodes.get(id);
    return node ? node.label : id;
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

  // Tell Claude which canvas nodes this file edit touches
  if (matchingNodes.length > 0) {
    const context = `Canvas: file "${relative}" touches nodes: ${touchedLabels.join(', ')}` +
      (toUpdate.length > 0 ? `. Updated ${toUpdate.length} to in-progress.` : '');
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: { hookEventName: 'PostToolUse', additionalContext: context },
    }));
  }
}

main().catch(() => {});
