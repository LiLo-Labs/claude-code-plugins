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

# Human-friendly relative time from an ISO-8601 UTC timestamp
relative_time() {
  local ts="$1"
  local now_epoch ts_epoch diff

  if [[ "$(uname)" == "Darwin" ]]; then
    now_epoch=$(date -u +%s)
    ts_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$ts" +%s 2>/dev/null) || { echo "unknown"; return; }
  else
    now_epoch=$(date -u +%s)
    ts_epoch=$(date -d "$ts" +%s 2>/dev/null) || { echo "unknown"; return; }
  fi

  diff=$(( now_epoch - ts_epoch ))

  if (( diff < 60 )); then
    echo "just now"
  elif (( diff < 3600 )); then
    echo "$(( diff / 60 ))m ago"
  elif (( diff < 86400 )); then
    echo "$(( diff / 3600 ))h ago"
  else
    echo "$(( diff / 86400 ))d ago"
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

cmd_show() {
  local global=false
  local filter_tag=""
  local filter_done=""   # "true", "false", or "" (no filter)

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --global)  global=true; shift ;;
      --tag)     filter_tag="$2"; shift 2 ;;
      --done)    filter_done="true"; shift ;;
      --pending) filter_done="false"; shift ;;
      *) shift ;;
    esac
  done

  local file="$PROJECT_FILE"
  [[ "$global" == true ]] && file="$GLOBAL_FILE"

  if [[ ! -f "$file" ]]; then
    echo "No notes."
    return 0
  fi

  # Build jq filter
  local jq_filter='.notes[]'
  if [[ -n "$filter_tag" ]]; then
    local filter_tag_lc
    filter_tag_lc=$(echo "$filter_tag" | tr '[:upper:]' '[:lower:]')
    jq_filter+=" | select(.tags | map(ascii_downcase) | any(. == \"${filter_tag_lc}\"))"
  fi
  if [[ "$filter_done" == "true" ]]; then
    jq_filter+=' | select(.done == true)'
  elif [[ "$filter_done" == "false" ]]; then
    jq_filter+=' | select(.done == false)'
  fi

  local notes
  notes=$(jq -c "[$jq_filter]" "$file")

  local count
  count=$(echo "$notes" | jq 'length')
  if [[ "$count" -eq 0 ]]; then
    echo "No notes."
    return 0
  fi

  # Format and print each note
  while IFS= read -r note; do
    local id text tags done_val created checkbox tags_str rel
    id=$(echo "$note" | jq -r '.id')
    text=$(echo "$note" | jq -r '.text')
    done_val=$(echo "$note" | jq -r '.done')
    created=$(echo "$note" | jq -r '.created')
    tags_str=$(echo "$note" | jq -r '.tags | map("#" + .) | join(" ")')
    rel=$(relative_time "$created")

    if [[ "$done_val" == "true" ]]; then
      checkbox="[x]"
    else
      checkbox="[ ]"
    fi

    printf "  %s #%-3s  %-40s  %-20s  (%s)\n" \
      "$checkbox" "$id" "$text" "$tags_str" "$rel"
  done < <(echo "$notes" | jq -c '.[]')
}

_set_note_done() {
  local note_id="$1"
  local done_val="$2"  # true or false
  local global=false

  # Check for --global in remaining args (already shifted out note_id)
  # We receive the file directly for simplicity; caller sets it
  local file="$3"

  init_file "$file"

  # Verify note exists
  local exists
  exists=$(jq --argjson id "$note_id" '.notes | any(.id == $id)' "$file")
  if [[ "$exists" != "true" ]]; then
    echo "Note #${note_id} not found." >&2
    exit 1
  fi

  local tmp="${file}.tmp.$$"
  jq --argjson id "$note_id" --argjson done "$done_val" \
    '(.notes[] | select(.id == $id)).done = $done' "$file" > "$tmp" && mv "$tmp" "$file"
}

cmd_done() {
  local global=false
  local note_id=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --global) global=true; shift ;;
      *) note_id="$1"; shift ;;
    esac
  done

  if [[ -z "$note_id" ]]; then
    echo "Usage: notes done [--global] <id>" >&2
    exit 1
  fi

  local file="$PROJECT_FILE"
  [[ "$global" == true ]] && file="$GLOBAL_FILE"

  _set_note_done "$note_id" "true" "$file"
  echo "Marked note #${note_id} as done."
}

cmd_clear() {
  local global=false
  local mode="done"  # "done" | "id" | "all"
  local note_id=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --global) global=true; shift ;;
      --all)    mode="all"; shift ;;
      [0-9]*)   mode="id"; note_id="$1"; shift ;;
      *) shift ;;
    esac
  done

  local file="$PROJECT_FILE"
  [[ "$global" == true ]] && file="$GLOBAL_FILE"

  init_file "$file"

  local tmp="${file}.tmp.$$"

  case "$mode" in
    done)
      jq '.notes = [.notes[] | select(.done == false)]' "$file" > "$tmp" && mv "$tmp" "$file"
      echo "Cleared done notes."
      ;;
    all)
      jq '.notes = []' "$file" > "$tmp" && mv "$tmp" "$file"
      echo "Cleared all notes."
      ;;
    id)
      local exists
      exists=$(jq --argjson id "$note_id" '.notes | any(.id == $id)' "$file")
      if [[ "$exists" != "true" ]]; then
        echo "Note #${note_id} not found." >&2
        exit 1
      fi
      jq --argjson id "$note_id" '.notes = [.notes[] | select(.id != $id)]' "$file" > "$tmp" && mv "$tmp" "$file"
      echo "Removed note #${note_id}."
      ;;
  esac
}

cmd_undo() {
  local global=false
  local note_id=""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --global) global=true; shift ;;
      *) note_id="$1"; shift ;;
    esac
  done

  if [[ -z "$note_id" ]]; then
    echo "Usage: notes undo [--global] <id>" >&2
    exit 1
  fi

  local file="$PROJECT_FILE"
  [[ "$global" == true ]] && file="$GLOBAL_FILE"

  _set_note_done "$note_id" "false" "$file"
  echo "Marked note #${note_id} as pending."
}

# --- Main dispatch ---

subcommand="${1:-help}"
shift || true

case "$subcommand" in
  add)  cmd_add  "$@" ;;
  show) cmd_show "$@" ;;
  done)  cmd_done  "$@" ;;
  undo)  cmd_undo  "$@" ;;
  clear) cmd_clear "$@" ;;
  *)
    echo "Usage: notes <add|show|done|undo|clear> [args]" >&2
    exit 1
    ;;
esac
