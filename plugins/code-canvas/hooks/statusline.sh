#!/bin/bash
# Canvas status line for Claude Code
# Shows: server URL, node counts by status, unresolved comments

# Read session JSON from stdin (required by statusline protocol)
input=$(cat)

# Find .code-canvas in current dir or parents
dir="$PWD"
while [ "$dir" != "/" ]; do
  if [ -d "$dir/.code-canvas" ]; then
    break
  fi
  dir=$(dirname "$dir")
done

if [ ! -d "$dir/.code-canvas" ]; then
  exit 0
fi

# Get server URL
info_file="$dir/.code-canvas/.server-info"
if [ ! -f "$info_file" ]; then
  echo "Canvas: not running"
  exit 0
fi

url=$(node -e "try{console.log(JSON.parse(require('fs').readFileSync('$info_file','utf8')).url)}catch{}" 2>/dev/null)
if [ -z "$url" ]; then
  echo "Canvas: server info missing"
  exit 0
fi

# Quick health check + state query
state=$(curl -s --max-time 1 "$url/api/state?level=L0" 2>/dev/null)
if [ -z "$state" ]; then
  echo "Canvas: offline"
  exit 0
fi

# Parse the summary
summary=$(echo "$state" | node -e "
try {
  const d = JSON.parse(require('fs').readFileSync('/dev/stdin','utf8'));
  const s = d.summary || '';
  const nodes = s.match(/Nodes: (\\d+)/)?.[1] || '0';
  const status = s.match(/Nodes: \\d+ \\((.+?)\\)/)?.[1] || '';
  const comments = s.match(/Comments: (\\d+)/)?.[1] || '0';
  const parts = ['$url', nodes + ' nodes'];
  if (status) parts.push(status);
  if (comments !== '0') parts.push(comments + ' comments');
  console.log(parts.join(' | '));
} catch { console.log('$url'); }
" 2>/dev/null)

echo "$summary"
