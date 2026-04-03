#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTES_SH="$SCRIPT_DIR/../scripts/notes.sh"

# Collect pending notes from both scopes
project_notes=$("$NOTES_SH" show --pending 2>/dev/null || true)
global_notes=$("$NOTES_SH" show --global --pending 2>/dev/null || true)

# Build output — only if there are actual notes
output=""

if [[ -n "$project_notes" && "$project_notes" != "No notes." ]]; then
  output="Project Notes:\\n$project_notes"
fi

if [[ -n "$global_notes" && "$global_notes" != "No notes." ]]; then
  [[ -n "$output" ]] && output="$output\\n\\n"
  output="${output}Global Notes:\\n$global_notes"
fi

# If no notes, exit silently
if [[ -z "$output" ]]; then
  exit 0
fi

# Output as additionalContext for the session
cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "Pending notes from the user's checklist (captured via /notes plugin):\\n\\n$output"
  }
}
EOF

exit 0
