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
  local output
  output=$(bash "$NOTES_SH" show --pending)
  local count
  count=$(echo "$output" | grep -c '\[ \]' || true)
  assert_eq "2" "$count" "two pending notes"
  teardown
}

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

# --- Run ---

test_add_creates_file_if_missing
test_add_with_tags
test_add_global
test_add_multiple_increments_id
test_show_displays_notes
test_show_empty
test_show_global
test_show_tag_filter
test_show_pending_filter
test_done_marks_note
test_done_invalid_id
test_undo_unchecks_note
test_show_done_filter
test_clear_removes_done
test_clear_specific_id
test_clear_all
test_clear_invalid_id

echo ""
echo "Results: $TESTS_PASSED/$TESTS_RUN passed"
[[ "$TESTS_PASSED" -eq "$TESTS_RUN" ]] || exit 1
