#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { findProjectDir, readEvents, replayState } from './lib/canvas-client.js';

function main() {
  const projectDir = findProjectDir();
  if (!projectDir) { process.stdout.write('{}'); return; }

  const events = readEvents(projectDir);
  const state = replayState(events);
  if (state.nodes.size === 0 && state.comments.length === 0) {
    process.stdout.write('{}');
    return;
  }

  // Track what Claude last saw via a marker file
  const markerFile = path.join(projectDir, '.code-canvas', '.claude-last-seen');
  let lastSeenCount = 0;
  try {
    lastSeenCount = parseInt(fs.readFileSync(markerFile, 'utf-8').trim(), 10) || 0;
  } catch {}

  // Find events that happened since Claude last looked
  const newEvents = events.slice(lastSeenCount);
  const userEvents = newEvents.filter(e => e.actor === 'user' || e.actor === 'system');

  // Update the marker
  try {
    fs.writeFileSync(markerFile, String(events.length));
  } catch {}

  if (userEvents.length === 0) {
    process.stdout.write('{}');
    return;
  }

  // Categorize changes
  const changes = {
    comments: [],
    statusChanges: [],
    nodesCreated: [],
    nodesUpdated: [],
    nodesDeleted: [],
    viewChanges: [],
    decisions: [],
  };

  for (const e of userEvents) {
    switch (e.type) {
      case 'comment.added':
        changes.comments.push(`"${e.data.text}" on ${e.data.targetLabel || e.data.target} (${e.actor})`);
        break;
      case 'node.status':
        changes.statusChanges.push(`${e.data.nodeId}: ${e.data.prev} → ${e.data.status}`);
        break;
      case 'node.created':
        changes.nodesCreated.push(e.data.label || e.data.nodeId);
        break;
      case 'node.updated':
        changes.nodesUpdated.push(e.data.nodeId);
        break;
      case 'node.deleted':
        changes.nodesDeleted.push(e.data.nodeId);
        break;
      case 'view.created':
      case 'view.updated':
        changes.viewChanges.push(`${e.type.split('.')[1]}: ${e.data.name || e.data.viewId}`);
        break;
      case 'decision.recorded':
        changes.decisions.push(`${e.data.nodeId}: chose "${e.data.chosen}"`);
        break;
    }
  }

  // Build context message
  let context = `## Canvas Changes Since You Last Looked\n\n`;
  let hasChanges = false;

  if (changes.comments.length > 0) {
    context += `**New comments (${changes.comments.length}):**\n`;
    changes.comments.forEach(c => context += `- ${c}\n`);
    hasChanges = true;
  }
  if (changes.nodesCreated.length > 0) {
    context += `**New nodes:** ${changes.nodesCreated.join(', ')}\n`;
    hasChanges = true;
  }
  if (changes.nodesDeleted.length > 0) {
    context += `**Deleted nodes:** ${changes.nodesDeleted.join(', ')}\n`;
    hasChanges = true;
  }
  if (changes.nodesUpdated.length > 0) {
    context += `**Updated nodes:** ${changes.nodesUpdated.join(', ')}\n`;
    hasChanges = true;
  }
  if (changes.statusChanges.length > 0) {
    context += `**Status changes:** ${changes.statusChanges.join(', ')}\n`;
    hasChanges = true;
  }
  if (changes.decisions.length > 0) {
    context += `**Decisions:** ${changes.decisions.join(', ')}\n`;
    hasChanges = true;
  }
  if (changes.viewChanges.length > 0) {
    context += `**View changes:** ${changes.viewChanges.join(', ')}\n`;
    hasChanges = true;
  }

  if (hasChanges) {
    context += `\nReview these changes and ensure your next action is aligned with them.`;
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: { hookEventName: 'PreToolUse', additionalContext: context },
    }));
  } else {
    process.stdout.write('{}');
  }
}

try { main(); } catch { process.stdout.write('{}'); }
