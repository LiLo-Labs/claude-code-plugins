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

  # Add another and clear specific
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
