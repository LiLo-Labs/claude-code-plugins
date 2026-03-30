#!/usr/bin/env node
import { findProjectDir, stopServer } from './lib/canvas-client.js';

function main() {
  const projectDir = findProjectDir();
  if (!projectDir) return;
  stopServer(projectDir);
}

try { main(); } catch {}
