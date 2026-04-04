#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { findProjectDir, readEvents, replayState, findNodesForFile } from './lib/canvas-client.js';

function main() {
  const projectDir = findProjectDir();
  if (!projectDir) return;

  const events = readEvents(projectDir);
  const state = replayState(events);
  if (state.nodes.size === 0) return;

  // Check for in-progress nodes that might need status update
  const inProgress = [...state.nodes.values()].filter(n => n.status === 'in-progress');

  // Check for unresolved comments
  const unresolvedComments = state.comments.filter(c => !c.resolved);

  const parts = [];

  if (inProgress.length > 0) {
    parts.push(
      `**Canvas: ${inProgress.length} node(s) still in-progress:** ${inProgress.map(n => n.label).join(', ')}`,
      `If work is complete, update their status to "done" via: POST /api/events with type "node.status"`,
    );
  }

  if (unresolvedComments.length > 0) {
    parts.push(
      `**Canvas: ${unresolvedComments.length} unresolved comment(s)** — review and resolve if addressed.`,
    );
  }

  // Scan for source files not tracked by any node
  const srcDir = path.join(projectDir, 'src');
  const clientSrcDir = path.join(projectDir, 'client', 'src');
  const dirsToScan = [srcDir, clientSrcDir].filter(d => fs.existsSync(d));

  const untrackedFiles = [];
  for (const dir of dirsToScan) {
    scanDir(dir, projectDir, state.nodes, untrackedFiles);
  }

  if (untrackedFiles.length > 0) {
    parts.push(
      `**Canvas: ${untrackedFiles.length} source file(s) not tracked by any node:**`,
      untrackedFiles.map(f => `  - ${f}`).join('\n'),
      `Consider creating nodes for these or adding their patterns to existing nodes' \`files\` arrays.`,
    );
  }

  if (parts.length > 0) {
    process.stdout.write(JSON.stringify({
      hookSpecificOutput: { hookEventName: 'Stop', additionalContext: parts.join('\n') },
    }));
  }
}

function scanDir(dir, projectDir, nodes, untrackedFiles) {
  try {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory() && entry.name !== 'node_modules' && entry.name !== 'dist') {
        scanDir(full, projectDir, nodes, untrackedFiles);
      } else if (entry.isFile() && /\.(js|ts|svelte|jsx|tsx|py|go|rs)$/.test(entry.name)) {
        const relative = full.slice(projectDir.length + 1);
        const matched = findNodesForFile(relative, nodes);
        if (matched.length === 0) untrackedFiles.push(relative);
      }
    }
  } catch {}
}

try { main(); } catch {}
