#!/usr/bin/env bash
set -euo pipefail

# Notes CLI — deterministic CRUD for Claude Code notes plugin
# All state stored as JSON files, manipulated via jq.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# File paths — overridable via env vars for testing
resolve_project_path() {
  local cwd="${PWD}"
  # Claude Code convention: /Users/foo/bar -> -Users-foo-bar
  echo "${cwd}" | sed 's|/|-|g'
}

PROJECT_FILE="${CLAUDE_NOTES_PROJECT_FILE:-$HOME/.claude/projects/$(resolve_project_path)/notes.json}"
GLOBAL_FILE="${CLAUDE_NOTES_GLOBAL_FILE:-$HOME/.claude/notes.json}"

# Initialize empty notes file if missing
init_file() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    mkdir -p "$(dirname "$file")"
    echo '{"notes":[],"next_id":1}' | jq . > "$file"
  fi
}

# Parse tags from text: "some text #tag1 #tag2"
# Sets globals: PARSED_TEXT and PARSED_TAGS_JSON
parse_tags() {
  local input="$1"
  PARSED_TAGS_JSON="[]"
  local clean_text="$input"

  # Extract #tags
  local tags=()
  while [[ "$clean_text" =~ \#([a-zA-Z0-9_-]+) ]]; do
    tags+=("${BASH_REMATCH[1]}")
    clean_text="${clean_text//#${BASH_REMATCH[1]}/}"
  done

  # Clean up extra whitespace
  PARSED_TEXT="$(echo "$clean_text" | sed 's/  */ /g; s/^ *//; s/ *$//')"

  # Build JSON array of tags
  if [[ ${#tags[@]} -gt 0 ]]; then
    PARSED_TAGS_JSON=$(printf '%s\n' "${tags[@]}" | jq -R . | jq -s .)
  fi
}

# --- Subcommands ---

cmd_add() {
  local global=false
  local text=""

  # Parse flags
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --global) global=true; shift ;;
      *) text="$text $1"; shift ;;
    esac
  done
  text="$(echo "$text" | sed 's/^ *//; s/ *$//')"

  if [[ -z "$text" ]]; then
    echo "Usage: notes add [--global] \"note text\" [#tag1 #tag2]" >&2
    exit 1
  fi

  local file="$PROJECT_FILE"
  [[ "$global" == true ]] && file="$GLOBAL_FILE"

  init_file "$file"

  # Parse tags from text
  local PARSED_TEXT PARSED_TAGS_JSON
  parse_tags "$text"
  local clean_text="$PARSED_TEXT"
  local tags_json="$PARSED_TAGS_JSON"

  local now
  now="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  # Atomic read-modify-write
  local tmp="${file}.tmp.$$"
  jq --arg text "$clean_text" \
     --argjson tags "$tags_json" \
     --arg created "$now" \
     '.notes += [{
       id: .next_id,
       text: $text,
       tags: $tags,
       done: false,
       created: $created
     }] | .next_id += 1' "$file" > "$tmp" && mv "$tmp" "$file"

  echo "Added note #$(jq '.next_id - 1' "$file"): $clean_text"
}

# --- Main dispatch ---

subcommand="${1:-help}"
shift || true

case "$subcommand" in
  add) cmd_add "$@" ;;
  *)
    echo "Usage: notes <add|show|done|undo|clear> [args]" >&2
    exit 1
    ;;
esac
