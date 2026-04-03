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
