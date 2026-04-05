# Notes Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code plugin that lets users capture thoughts as a checklist via `/notes` and surfaces them to Claude automatically.

**Architecture:** A shell script (`notes.sh`) handles all JSON CRUD. A command file (`notes.md`) provides the `/notes` slash command. A skill (`SKILL.md`) teaches Claude when to check notes. A session-start hook auto-displays pending notes.

**Tech Stack:** Bash, jq (JSON processing), Claude Code plugin system (commands, skills, hooks)

---

### Task 1: Plugin Scaffold and Metadata

**Files:**
- Create: `plugins/notes/.claude-plugin/plugin.json`
- Create: `plugins/notes/README.md`

- [ ] **Step 1: Create plugin.json**

```json
{
  "name": "notes",
  "description": "Capture thoughts as a checklist during conversations and surface them to Claude at the right time",
  "version": "1.0.0",
  "author": {
    "name": "LiloLabs"
  }
}
```

- [ ] **Step 2: Create README.md**

```markdown
# Notes Plugin

A Claude Code plugin for capturing thoughts as a checklist during conversations — especially while agents are running — and surfacing them to Claude at the right time.

## Commands

| Command | Description |
|---------|-------------|
| `/notes add "text" #tag1 #tag2` | Add a note with optional tags |
| `/notes add --global "text"` | Add a global (cross-project) note |
| `/notes show` | Show all project notes |
| `/notes show --global` | Show global notes |
| `/notes show --tag X` | Filter by tag |
| `/notes show --done` / `--pending` | Filter by status |
| `/notes done N` | Mark note N as done |
| `/notes undo N` | Uncheck note N |
| `/notes clear` | Remove all done notes |
| `/notes clear N` | Remove specific note |
| `/notes clear --all` | Remove all notes |

## Storage

- **Project notes:** `~/.claude/projects/<project-path>/notes.json`
- **Global notes:** `~/.claude/notes.json`

## Behavior

- Pending notes are shown automatically at conversation start
- Claude checks for new notes after agents return
- Claude marks notes done as it addresses them
```

- [ ] **Step 3: Commit**

```bash
git add plugins/notes/.claude-plugin/plugin.json plugins/notes/README.md
git commit -m "feat(notes): add plugin scaffold and metadata"
```

---

### Task 2: Core Shell Script — File I/O and Add

**Files:**
- Create: `plugins/notes/scripts/notes.sh`
- Create: `plugins/notes/tests/test_notes.sh`

The script uses `jq` for JSON manipulation. All functions operate on a file path passed as context.

- [ ] **Step 1: Write test for project path resolution**

Create `plugins/notes/tests/test_notes.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTES_SH="$SCRIPT_DIR/../scripts/notes.sh"
TEST_TMPDIR=""
TESTS_RUN=0
TESTS_PASSED=0

setup() {
  TEST_TMPDIR="$(mktemp -d)"
  export CLAUDE_NOTES_PROJECT_FILE="$TEST_TMPDIR/project-notes.json"
  export CLAUDE_NOTES_GLOBAL_FILE="$TEST_TMPDIR/global-notes.json"
}

teardown() {
  rm -rf "$TEST_TMPDIR"
}

assert_eq() {
  local expected="$1" actual="$2" msg="${3:-}"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$expected" == "$actual" ]]; then
    TESTS_PASSED=$((TESTS_PASSED + 1))
    echo "  PASS: $msg"
  else
    echo "  FAIL: $msg"
    echo "    expected: $expected"
    echo "    actual:   $actual"
  fi
}

assert_contains() {
  local needle="$1" haystack="$2" msg="${3:-}"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$haystack" == *"$needle"* ]]; then
    TESTS_PASSED=$((TESTS_PASSED + 1))
    echo "  PASS: $msg"
  else
    echo "  FAIL: $msg"
    echo "    expected to contain: $needle"
    echo "    actual: $haystack"
  fi
}

# --- Tests ---

test_add_creates_file_if_missing() {
  echo "test: add creates notes file if missing"
  setup
  bash "$NOTES_SH" add "first note"
  assert_eq "true" "$(test -f "$CLAUDE_NOTES_PROJECT_FILE" && echo true || echo false)" "file created"
  local text
  text=$(jq -r '.notes[0].text' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "first note" "$text" "note text stored"
  local done_val
  done_val=$(jq -r '.notes[0].done' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "false" "$done_val" "note starts unchecked"
  local next_id
  next_id=$(jq -r '.next_id' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "2" "$next_id" "next_id incremented"
  teardown
}

test_add_with_tags() {
  echo "test: add parses tags from text"
  setup
  bash "$NOTES_SH" add "consider webhooks #architecture #api"
  local tags
  tags=$(jq -r '.notes[0].tags | join(",")' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "architecture,api" "$tags" "tags parsed"
  local text
  text=$(jq -r '.notes[0].text' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "consider webhooks" "$text" "tags stripped from text"
  teardown
}

test_add_global() {
  echo "test: add --global writes to global file"
  setup
  bash "$NOTES_SH" add --global "global thought #devtools"
  assert_eq "true" "$(test -f "$CLAUDE_NOTES_GLOBAL_FILE" && echo true || echo false)" "global file created"
  assert_eq "false" "$(test -f "$CLAUDE_NOTES_PROJECT_FILE" && echo true || echo false)" "project file not created"
  local text
  text=$(jq -r '.notes[0].text' "$CLAUDE_NOTES_GLOBAL_FILE")
  assert_eq "global thought" "$text" "global note text"
  teardown
}

test_add_multiple_increments_id() {
  echo "test: adding multiple notes increments IDs"
  setup
  bash "$NOTES_SH" add "first"
  bash "$NOTES_SH" add "second"
  bash "$NOTES_SH" add "third"
  local id1 id2 id3 next_id
  id1=$(jq -r '.notes[0].id' "$CLAUDE_NOTES_PROJECT_FILE")
  id2=$(jq -r '.notes[1].id' "$CLAUDE_NOTES_PROJECT_FILE")
  id3=$(jq -r '.notes[2].id' "$CLAUDE_NOTES_PROJECT_FILE")
  next_id=$(jq -r '.next_id' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "1" "$id1" "first id"
  assert_eq "2" "$id2" "second id"
  assert_eq "3" "$id3" "third id"
  assert_eq "4" "$next_id" "next_id is 4"
  teardown
}

# --- Run ---

test_add_creates_file_if_missing
test_add_with_tags
test_add_global
test_add_multiple_increments_id

echo ""
echo "Results: $TESTS_PASSED/$TESTS_RUN passed"
[[ "$TESTS_PASSED" -eq "$TESTS_RUN" ]] || exit 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `bash plugins/notes/tests/test_notes.sh`
Expected: FAIL — `notes.sh` does not exist yet

- [ ] **Step 3: Write notes.sh with add subcommand**

Create `plugins/notes/scripts/notes.sh`:

```bash
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

# Parse tags from text: "some text #tag1 #tag2" -> text="some text" tags=["tag1","tag2"]
parse_tags() {
  local input="$1"
  local tags_json="[]"
  local clean_text="$input"

  # Extract #tags
  local tags=()
  while [[ "$clean_text" =~ \#([a-zA-Z0-9_-]+) ]]; do
    tags+=("${BASH_REMATCH[1]}")
    clean_text="${clean_text//#${BASH_REMATCH[1]}/}"
  done

  # Clean up extra whitespace
  clean_text="$(echo "$clean_text" | sed 's/  */ /g; s/^ *//; s/ *$//')"

  # Build JSON array of tags
  if [[ ${#tags[@]} -gt 0 ]]; then
    tags_json=$(printf '%s\n' "${tags[@]}" | jq -R . | jq -s .)
  fi

  echo "$clean_text"
  echo "$tags_json"
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
  local parsed
  parsed="$(parse_tags "$text")"
  local clean_text tags_json
  clean_text="$(echo "$parsed" | head -1)"
  tags_json="$(echo "$parsed" | tail -1)"

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
```

- [ ] **Step 4: Make script executable and run tests**

Run: `chmod +x plugins/notes/scripts/notes.sh && bash plugins/notes/tests/test_notes.sh`
Expected: All 4 tests pass

- [ ] **Step 5: Commit**

```bash
git add plugins/notes/scripts/notes.sh plugins/notes/tests/test_notes.sh
git commit -m "feat(notes): add core script with add subcommand and tests"
```

---

### Task 3: Shell Script — Show Subcommand

**Files:**
- Modify: `plugins/notes/scripts/notes.sh`
- Modify: `plugins/notes/tests/test_notes.sh`

- [ ] **Step 1: Add show tests**

Append to `plugins/notes/tests/test_notes.sh` (before the `# --- Run ---` section):

```bash
test_show_displays_notes() {
  echo "test: show displays notes with checkboxes and IDs"
  setup
  bash "$NOTES_SH" add "first note #api"
  bash "$NOTES_SH" add "second note #arch"
  local output
  output=$(bash "$NOTES_SH" show)
  assert_contains "[ ] #1" "$output" "shows unchecked #1"
  assert_contains "first note" "$output" "shows first note text"
  assert_contains "#api" "$output" "shows tag"
  assert_contains "[ ] #2" "$output" "shows unchecked #2"
  teardown
}

test_show_empty() {
  echo "test: show with no notes shows nothing"
  setup
  local output
  output=$(bash "$NOTES_SH" show 2>&1 || true)
  assert_contains "No notes" "$output" "empty message"
  teardown
}

test_show_global() {
  echo "test: show --global shows global notes"
  setup
  bash "$NOTES_SH" add --global "global note"
  bash "$NOTES_SH" add "project note"
  local output
  output=$(bash "$NOTES_SH" show --global)
  assert_contains "global note" "$output" "shows global"
  teardown
}

test_show_tag_filter() {
  echo "test: show --tag filters by tag"
  setup
  bash "$NOTES_SH" add "api thought #api"
  bash "$NOTES_SH" add "arch thought #architecture"
  local output
  output=$(bash "$NOTES_SH" show --tag api)
  assert_contains "api thought" "$output" "shows matching"
  # Should not contain arch thought — but it might appear in a loose check.
  # Count lines with note content instead.
  local count
  count=$(echo "$output" | grep -c '\[ \]' || true)
  assert_eq "1" "$count" "only one note shown"
  teardown
}

test_show_pending_filter() {
  echo "test: show --pending shows only unchecked"
  setup
  bash "$NOTES_SH" add "pending one"
  bash "$NOTES_SH" add "pending two"
  # We'll mark one done after Task 4, but for now both should show
  local output
  output=$(bash "$NOTES_SH" show --pending)
  local count
  count=$(echo "$output" | grep -c '\[ \]' || true)
  assert_eq "2" "$count" "two pending notes"
  teardown
}
```

Also add these to the Run section:

```bash
test_show_displays_notes
test_show_empty
test_show_global
test_show_tag_filter
test_show_pending_filter
```

- [ ] **Step 2: Run tests to verify new ones fail**

Run: `bash plugins/notes/tests/test_notes.sh`
Expected: New show tests FAIL, old add tests still PASS

- [ ] **Step 3: Implement show subcommand**

Add to `notes.sh` before the `# --- Main dispatch ---` section:

```bash
# Relative time display
relative_time() {
  local created="$1"
  local now_epoch created_epoch diff

  # macOS date vs GNU date
  if date -j -f "%Y-%m-%dT%H:%M:%SZ" "$created" "+%s" &>/dev/null; then
    created_epoch=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$created" "+%s")
  else
    created_epoch=$(date -d "$created" "+%s")
  fi
  now_epoch=$(date -u "+%s")
  diff=$((now_epoch - created_epoch))

  if [[ $diff -lt 60 ]]; then echo "just now"
  elif [[ $diff -lt 3600 ]]; then echo "$((diff / 60))m ago"
  elif [[ $diff -lt 86400 ]]; then echo "$((diff / 3600))h ago"
  else echo "$((diff / 86400))d ago"
  fi
}

cmd_show() {
  local global=false
  local tag_filter=""
  local status_filter="" # "done", "pending", or ""

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --global) global=true; shift ;;
      --tag) tag_filter="$2"; shift 2 ;;
      --done) status_filter="done"; shift ;;
      --pending) status_filter="pending"; shift ;;
      *) shift ;;
    esac
  done

  local file="$PROJECT_FILE"
  [[ "$global" == true ]] && file="$GLOBAL_FILE"

  if [[ ! -f "$file" ]]; then
    echo "No notes."
    return 0
  fi

  local notes_count
  notes_count=$(jq '.notes | length' "$file")
  if [[ "$notes_count" -eq 0 ]]; then
    echo "No notes."
    return 0
  fi

  # Build jq filter
  local jq_filter='.notes[]'
  if [[ -n "$tag_filter" ]]; then
    jq_filter="$jq_filter | select(.tags | index(\"$tag_filter\"))"
  fi
  if [[ "$status_filter" == "done" ]]; then
    jq_filter="$jq_filter | select(.done == true)"
  elif [[ "$status_filter" == "pending" ]]; then
    jq_filter="$jq_filter | select(.done == false)"
  fi

  local has_output=false
  while IFS=$'\t' read -r id text done_val tags_str created; do
    has_output=true
    local checkbox="[ ]"
    [[ "$done_val" == "true" ]] && checkbox="[x]"
    local tag_display=""
    if [[ -n "$tags_str" && "$tags_str" != "" ]]; then
      tag_display="  $tags_str"
    fi
    local time_display
    time_display="$(relative_time "$created")"
    printf "  %s #%s  %s%s  (%s)\n" "$checkbox" "$id" "$text" "$tag_display" "$time_display"
  done < <(jq -r "[$jq_filter] | .[] | [.id, .text, .done, (.tags | map(\"#\" + .) | join(\" \")), .created] | @tsv" "$file")

  if [[ "$has_output" == false ]]; then
    echo "No notes."
  fi
}
```

Update the main dispatch to include `show`:

```bash
case "$subcommand" in
  add) cmd_add "$@" ;;
  show) cmd_show "$@" ;;
  *)
    echo "Usage: notes <add|show|done|undo|clear> [args]" >&2
    exit 1
    ;;
esac
```

- [ ] **Step 4: Run tests**

Run: `bash plugins/notes/tests/test_notes.sh`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add plugins/notes/scripts/notes.sh plugins/notes/tests/test_notes.sh
git commit -m "feat(notes): add show subcommand with filters"
```

---

### Task 4: Shell Script — Done and Undo Subcommands

**Files:**
- Modify: `plugins/notes/scripts/notes.sh`
- Modify: `plugins/notes/tests/test_notes.sh`

- [ ] **Step 1: Add done/undo tests**

Append tests (before `# --- Run ---`):

```bash
test_done_marks_note() {
  echo "test: done marks a note as checked"
  setup
  bash "$NOTES_SH" add "first"
  bash "$NOTES_SH" add "second"
  bash "$NOTES_SH" done 1
  local done_val
  done_val=$(jq -r '.notes[0].done' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "true" "$done_val" "note 1 done"
  done_val=$(jq -r '.notes[1].done' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "false" "$done_val" "note 2 still pending"
  teardown
}

test_done_invalid_id() {
  echo "test: done with invalid ID shows error"
  setup
  bash "$NOTES_SH" add "first"
  local output
  output=$(bash "$NOTES_SH" done 99 2>&1 || true)
  assert_contains "not found" "$output" "error for invalid ID"
  teardown
}

test_undo_unchecks_note() {
  echo "test: undo unchecks a done note"
  setup
  bash "$NOTES_SH" add "first"
  bash "$NOTES_SH" done 1
  bash "$NOTES_SH" undo 1
  local done_val
  done_val=$(jq -r '.notes[0].done' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "false" "$done_val" "note 1 unchecked"
  teardown
}

test_show_done_filter() {
  echo "test: show --done shows only checked notes"
  setup
  bash "$NOTES_SH" add "pending"
  bash "$NOTES_SH" add "completed"
  bash "$NOTES_SH" done 2
  local output
  output=$(bash "$NOTES_SH" show --done)
  assert_contains "completed" "$output" "shows done note"
  local count
  count=$(echo "$output" | grep -c '\[x\]' || true)
  assert_eq "1" "$count" "only one done note"
  teardown
}
```

Add to Run section:

```bash
test_done_marks_note
test_done_invalid_id
test_undo_unchecks_note
test_show_done_filter
```

- [ ] **Step 2: Run tests to verify new ones fail**

Run: `bash plugins/notes/tests/test_notes.sh`
Expected: New done/undo tests FAIL

- [ ] **Step 3: Implement done and undo subcommands**

Add to `notes.sh` before `# --- Main dispatch ---`:

```bash
cmd_done() {
  local id="${1:-}"
  if [[ -z "$id" ]]; then
    echo "Usage: notes done <id>" >&2
    exit 1
  fi

  local file="$PROJECT_FILE"
  init_file "$file"

  local exists
  exists=$(jq --argjson id "$id" '[.notes[] | select(.id == $id)] | length' "$file")
  if [[ "$exists" -eq 0 ]]; then
    echo "Note #$id not found." >&2
    exit 1
  fi

  local tmp="${file}.tmp.$$"
  jq --argjson id "$id" '(.notes[] | select(.id == $id)).done = true' "$file" > "$tmp" && mv "$tmp" "$file"
  echo "Marked note #$id as done."
}

cmd_undo() {
  local id="${1:-}"
  if [[ -z "$id" ]]; then
    echo "Usage: notes undo <id>" >&2
    exit 1
  fi

  local file="$PROJECT_FILE"
  init_file "$file"

  local exists
  exists=$(jq --argjson id "$id" '[.notes[] | select(.id == $id)] | length' "$file")
  if [[ "$exists" -eq 0 ]]; then
    echo "Note #$id not found." >&2
    exit 1
  fi

  local tmp="${file}.tmp.$$"
  jq --argjson id "$id" '(.notes[] | select(.id == $id)).done = false' "$file" > "$tmp" && mv "$tmp" "$file"
  echo "Marked note #$id as pending."
}
```

Update dispatch:

```bash
case "$subcommand" in
  add) cmd_add "$@" ;;
  show) cmd_show "$@" ;;
  done) cmd_done "$@" ;;
  undo) cmd_undo "$@" ;;
  *)
    echo "Usage: notes <add|show|done|undo|clear> [args]" >&2
    exit 1
    ;;
esac
```

- [ ] **Step 4: Run tests**

Run: `bash plugins/notes/tests/test_notes.sh`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add plugins/notes/scripts/notes.sh plugins/notes/tests/test_notes.sh
git commit -m "feat(notes): add done and undo subcommands"
```

---

### Task 5: Shell Script — Clear Subcommand

**Files:**
- Modify: `plugins/notes/scripts/notes.sh`
- Modify: `plugins/notes/tests/test_notes.sh`

- [ ] **Step 1: Add clear tests**

Append tests:

```bash
test_clear_removes_done() {
  echo "test: clear removes all done notes"
  setup
  bash "$NOTES_SH" add "keep me"
  bash "$NOTES_SH" add "remove me"
  bash "$NOTES_SH" add "also keep"
  bash "$NOTES_SH" done 2
  bash "$NOTES_SH" clear
  local count
  count=$(jq '.notes | length' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "2" "$count" "two notes remain"
  local text1 text2
  text1=$(jq -r '.notes[0].text' "$CLAUDE_NOTES_PROJECT_FILE")
  text2=$(jq -r '.notes[1].text' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "keep me" "$text1" "first note kept"
  assert_eq "also keep" "$text2" "third note kept"
  teardown
}

test_clear_specific_id() {
  echo "test: clear N removes specific note"
  setup
  bash "$NOTES_SH" add "first"
  bash "$NOTES_SH" add "second"
  bash "$NOTES_SH" add "third"
  bash "$NOTES_SH" clear 2
  local count
  count=$(jq '.notes | length' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "2" "$count" "two notes remain"
  local ids
  ids=$(jq -r '.notes[].id' "$CLAUDE_NOTES_PROJECT_FILE" | tr '\n' ',')
  assert_eq "1,3," "$ids" "notes 1 and 3 remain"
  teardown
}

test_clear_all() {
  echo "test: clear --all removes everything"
  setup
  bash "$NOTES_SH" add "first"
  bash "$NOTES_SH" add "second"
  bash "$NOTES_SH" clear --all
  local count
  count=$(jq '.notes | length' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "0" "$count" "no notes remain"
  # next_id should NOT reset — IDs are never reused
  local next_id
  next_id=$(jq '.next_id' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "3" "$next_id" "next_id preserved"
  teardown
}

test_clear_invalid_id() {
  echo "test: clear with invalid ID shows error"
  setup
  bash "$NOTES_SH" add "first"
  local output
  output=$(bash "$NOTES_SH" clear 99 2>&1 || true)
  assert_contains "not found" "$output" "error for invalid ID"
  teardown
}
```

Add to Run section:

```bash
test_clear_removes_done
test_clear_specific_id
test_clear_all
test_clear_invalid_id
```

- [ ] **Step 2: Run tests to verify new ones fail**

Run: `bash plugins/notes/tests/test_notes.sh`
Expected: New clear tests FAIL

- [ ] **Step 3: Implement clear subcommand**

Add to `notes.sh` before `# --- Main dispatch ---`:

```bash
cmd_clear() {
  local file="$PROJECT_FILE"
  init_file "$file"

  if [[ $# -eq 0 ]]; then
    # Clear all done notes
    local tmp="${file}.tmp.$$"
    jq '[.notes[] | select(.done == false)] as $remaining | .notes = $remaining' "$file" > "$tmp" && mv "$tmp" "$file"
    echo "Cleared all done notes."
    return 0
  fi

  case "$1" in
    --all)
      local tmp="${file}.tmp.$$"
      jq '.notes = []' "$file" > "$tmp" && mv "$tmp" "$file"
      echo "Cleared all notes."
      ;;
    *)
      local id="$1"
      local exists
      exists=$(jq --argjson id "$id" '[.notes[] | select(.id == $id)] | length' "$file")
      if [[ "$exists" -eq 0 ]]; then
        echo "Note #$id not found." >&2
        exit 1
      fi
      local tmp="${file}.tmp.$$"
      jq --argjson id "$id" '.notes = [.notes[] | select(.id != $id)]' "$file" > "$tmp" && mv "$tmp" "$file"
      echo "Cleared note #$id."
      ;;
  esac
}
```

Update dispatch:

```bash
case "$subcommand" in
  add) cmd_add "$@" ;;
  show) cmd_show "$@" ;;
  done) cmd_done "$@" ;;
  undo) cmd_undo "$@" ;;
  clear) cmd_clear "$@" ;;
  *)
    echo "Usage: notes <add|show|done|undo|clear> [args]" >&2
    exit 1
    ;;
esac
```

- [ ] **Step 4: Run tests**

Run: `bash plugins/notes/tests/test_notes.sh`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add plugins/notes/scripts/notes.sh plugins/notes/tests/test_notes.sh
git commit -m "feat(notes): add clear subcommand"
```

---

### Task 6: Command File

**Files:**
- Create: `plugins/notes/commands/notes.md`

- [ ] **Step 1: Create the command file**

```markdown
---
allowed-tools: Bash(*)
description: Capture and manage thoughts as a checklist
---

## Your task

Run the notes script with the user's arguments. The script handles all subcommands.

Run: `"${CLAUDE_PLUGIN_ROOT}/scripts/notes.sh" $ARGUMENTS`

Display the output to the user exactly as returned. Do not add commentary.

If no arguments are provided, run: `"${CLAUDE_PLUGIN_ROOT}/scripts/notes.sh" show`

## Available subcommands

- `add "text" #tag1 #tag2` — add a note (project-scoped by default)
- `add --global "text"` — add a global note
- `show [--global] [--tag X] [--done] [--pending]` — display notes
- `done N` — mark note N as done
- `undo N` — uncheck note N
- `clear` — remove all done notes
- `clear N` — remove specific note
- `clear --all` — remove all notes
```

- [ ] **Step 2: Commit**

```bash
git add plugins/notes/commands/notes.md
git commit -m "feat(notes): add /notes slash command"
```

---

### Task 7: Skill File

**Files:**
- Create: `plugins/notes/skills/notes/SKILL.md`

- [ ] **Step 1: Create the skill file**

```markdown
---
name: notes
description: Use when starting a conversation, after agents return results, or when the user references their notes — manages a checklist of captured thoughts
---

# Notes Awareness

You have access to a notes system where the user captures thoughts — especially while agents are running. Notes are stored as checklists with IDs, tags, and done/pending status.

## When to Check Notes

**1. Conversation start:** Run the notes script to see pending notes:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/notes.sh" show --pending
"${CLAUDE_PLUGIN_ROOT}/scripts/notes.sh" show --global --pending
```

If there are pending notes, acknowledge them briefly: "You have N pending notes — I'll keep these in mind." Do not act on them unless the user asks.

**2. After agents return:** Before continuing work after a subagent completes, check for new notes. The user may have added thoughts while the agent was running:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/notes.sh" show --pending
```

Surface any notes relevant to the work that just completed.

**3. When you resolve a noted concern:** If your work directly addresses a pending note, mark it done:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/notes.sh" done <id>
```

Tell the user: "Marked note #N as done — [brief reason]."

## Rules

- Do NOT mark notes done speculatively — only when the concern is clearly resolved
- Do NOT act on notes unprompted — they are context, not instructions (unless the user asks)
- Keep acknowledgments brief — one line, not a summary of each note
- If no pending notes exist, say nothing about notes
```

- [ ] **Step 2: Commit**

```bash
git add plugins/notes/skills/notes/SKILL.md
git commit -m "feat(notes): add skill for auto-checking notes"
```

---

### Task 8: Session Start Hook

**Files:**
- Create: `plugins/notes/hooks/hooks.json`
- Create: `plugins/notes/hooks/session-start.sh`

- [ ] **Step 1: Create hooks.json**

```json
{
  "description": "Auto-display pending notes at conversation start",
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/session-start.sh"
          }
        ]
      }
    ]
  }
}
```

- [ ] **Step 2: Create session-start.sh**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTES_SH="$SCRIPT_DIR/../scripts/notes.sh"

# Collect pending notes from both scopes
project_notes=$("$NOTES_SH" show --pending 2>/dev/null || true)
global_notes=$(CLAUDE_NOTES_GLOBAL_FILE="${CLAUDE_NOTES_GLOBAL_FILE:-$HOME/.claude/notes.json}" "$NOTES_SH" show --global --pending 2>/dev/null || true)

# Build output — only if there are actual notes
output=""

if [[ -n "$project_notes" && "$project_notes" != "No notes." ]]; then
  output="Project Notes:\n$project_notes"
fi

if [[ -n "$global_notes" && "$global_notes" != "No notes." ]]; then
  [[ -n "$output" ]] && output="$output\n\n"
  output="${output}Global Notes:\n$global_notes"
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
    "additionalContext": "Pending notes from the user's checklist (captured via /notes plugin):\n\n$(echo -e "$output" | sed 's/"/\\"/g' | sed ':a;N;$!ba;s/\n/\\n/g')"
  }
}
EOF

exit 0
```

- [ ] **Step 3: Make hook executable**

Run: `chmod +x plugins/notes/hooks/session-start.sh`

- [ ] **Step 4: Commit**

```bash
git add plugins/notes/hooks/hooks.json plugins/notes/hooks/session-start.sh
git commit -m "feat(notes): add session-start hook for auto-displaying notes"
```

---

### Task 9: Integration Test

**Files:**
- Create: `plugins/notes/tests/test_integration.sh`

- [ ] **Step 1: Write integration test**

```bash
#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NOTES_SH="$SCRIPT_DIR/../scripts/notes.sh"
TEST_TMPDIR=""
TESTS_RUN=0
TESTS_PASSED=0

setup() {
  TEST_TMPDIR="$(mktemp -d)"
  export CLAUDE_NOTES_PROJECT_FILE="$TEST_TMPDIR/project-notes.json"
  export CLAUDE_NOTES_GLOBAL_FILE="$TEST_TMPDIR/global-notes.json"
}

teardown() {
  rm -rf "$TEST_TMPDIR"
}

assert_eq() {
  local expected="$1" actual="$2" msg="${3:-}"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$expected" == "$actual" ]]; then
    TESTS_PASSED=$((TESTS_PASSED + 1))
    echo "  PASS: $msg"
  else
    echo "  FAIL: $msg"
    echo "    expected: $expected"
    echo "    actual:   $actual"
  fi
}

assert_contains() {
  local needle="$1" haystack="$2" msg="${3:-}"
  TESTS_RUN=$((TESTS_RUN + 1))
  if [[ "$haystack" == *"$needle"* ]]; then
    TESTS_PASSED=$((TESTS_PASSED + 1))
    echo "  PASS: $msg"
  else
    echo "  FAIL: $msg"
    echo "    expected to contain: $needle"
    echo "    actual: $haystack"
  fi
}

test_full_lifecycle() {
  echo "test: full note lifecycle — add, show, done, show, clear"
  setup

  # Add notes
  bash "$NOTES_SH" add "implement auth #security #backend"
  bash "$NOTES_SH" add "review API design #api"
  bash "$NOTES_SH" add --global "update CI config #devops"

  # Show all project notes
  local output
  output=$(bash "$NOTES_SH" show)
  assert_contains "#1" "$output" "project note 1 visible"
  assert_contains "#2" "$output" "project note 2 visible"

  # Show global
  output=$(bash "$NOTES_SH" show --global)
  assert_contains "update CI config" "$output" "global note visible"

  # Mark one done
  bash "$NOTES_SH" done 1

  # Show pending only
  output=$(bash "$NOTES_SH" show --pending)
  assert_contains "review API design" "$output" "pending note visible"
  local pending_count
  pending_count=$(echo "$output" | grep -c '\[ \]' || true)
  assert_eq "1" "$pending_count" "only one pending"

  # Show done only
  output=$(bash "$NOTES_SH" show --done)
  assert_contains "implement auth" "$output" "done note visible"

  # Clear done notes
  bash "$NOTES_SH" clear
  local count
  count=$(jq '.notes | length' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "1" "$count" "one note remains after clear"

  # Undo, then clear specific
  bash "$NOTES_SH" add "temporary #tmp"
  bash "$NOTES_SH" clear 3
  count=$(jq '.notes | length' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "1" "$count" "still one note after clearing #3"

  # Clear all
  bash "$NOTES_SH" clear --all
  count=$(jq '.notes | length' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "0" "$count" "no notes after clear --all"

  teardown
}

test_ids_never_reuse() {
  echo "test: IDs are never reused after clear"
  setup
  bash "$NOTES_SH" add "first"
  bash "$NOTES_SH" add "second"
  bash "$NOTES_SH" clear --all
  bash "$NOTES_SH" add "third"
  local id
  id=$(jq '.notes[0].id' "$CLAUDE_NOTES_PROJECT_FILE")
  assert_eq "3" "$id" "new note gets id 3, not 1"
  teardown
}

test_full_lifecycle
test_ids_never_reuse

echo ""
echo "Results: $TESTS_PASSED/$TESTS_RUN passed"
[[ "$TESTS_PASSED" -eq "$TESTS_RUN" ]] || exit 1
```

- [ ] **Step 2: Run integration tests**

Run: `bash plugins/notes/tests/test_integration.sh`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add plugins/notes/tests/test_integration.sh
git commit -m "test(notes): add integration tests for full lifecycle"
```

---

### Task 10: Final Verification and Repo Setup

**Files:**
- None new — verification only

- [ ] **Step 1: Run all tests**

Run: `bash plugins/notes/tests/test_notes.sh && bash plugins/notes/tests/test_integration.sh`
Expected: All tests pass

- [ ] **Step 2: Verify plugin file structure**

Run: `find plugins/notes -type f | sort`

Expected output:
```
plugins/notes/.claude-plugin/plugin.json
plugins/notes/README.md
plugins/notes/commands/notes.md
plugins/notes/hooks/hooks.json
plugins/notes/hooks/session-start.sh
plugins/notes/scripts/notes.sh
plugins/notes/skills/notes/SKILL.md
plugins/notes/tests/test_integration.sh
plugins/notes/tests/test_notes.sh
```

- [ ] **Step 3: Create GitHub repo and push**

```bash
gh repo create lilolabs/claude-code-plugins --public --source=. --remote=origin --push
```

- [ ] **Step 4: Install plugin locally for testing**

Test that the plugin can be discovered by Claude Code by verifying the structure matches expectations.
