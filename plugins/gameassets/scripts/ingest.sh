#!/bin/bash
# Ingest new asset packs into the library.
#
#   ingest.sh                 process everything in $GAMEASSETS_ROOT/_inbox
#   ingest.sh <file|dir>...   process specific paths
#   ingest.sh --reindex       skip filing, just rebuild the index
#
# Files are routed to a collection by their source, guessed from the filename.
# Guessing wrong is cheap (move the file); guessing silently is not, so every
# routing decision is printed before it happens.
set -u
ROOT="${GAMEASSETS_ROOT:-$HOME/GameAssets}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INBOX="$ROOT/_inbox"
mkdir -p "$INBOX"

route() {   # filename -> collection
  local f; f=$(basename "$1" | tr 'A-Z' 'a-z')
  case "$f" in
    *kenney*|*quaternius*)                 echo cc0 ;;
    *.unitypackage)                        echo fab ;;
    *sonniss*|*gdc*)                       echo sonniss ;;
    *8dio*|*8Dio*)                         echo 8dio ;;
    *humble*|*bundle*)                     echo humble ;;
    *itch*)                                echo itch ;;
    *)                                     echo unsorted ;;
  esac
}

if [ "${1:-}" != "--reindex" ]; then
  shopt -s nullglob
  if [ $# -gt 0 ]; then items=("$@"); else items=("$INBOX"/*); fi
  [ ${#items[@]} -eq 0 ] && echo "nothing in $INBOX"
  moved=0
  for f in "${items[@]}"; do
    [ -e "$f" ] || continue
    coll=$(route "$f")
    dest="$ROOT/$coll"
    mkdir -p "$dest"
    base=$(basename "$f")
    if [ -e "$dest/$base" ]; then
      echo "  SKIP (already present): $coll/$base"
      continue
    fi
    echo "  -> $coll/$base"
    mv -n "$f" "$dest"/ && moved=$((moved+1))
  done
  echo "filed $moved item(s)"
  [ "$moved" -eq 0 ] && [ $# -eq 0 ] && exit 0
fi

echo
echo "rebuilding index (this takes several minutes)"
cd "$ROOT" || exit 1
# Order is load-bearing: build-db drops only its own tables, so `files` must be
# populated first, and build-graph reads `files`, so it must run last.
"$HERE/build-index.sh"                 || exit 1
python3 "$HERE/scan-licences.py"       || exit 1
python3 "$HERE/describe.py"            || exit 1
python3 "$HERE/index-files.py"         || exit 1
python3 "$HERE/build-db.py"            || exit 1
python3 "$HERE/build-graph.py"         || exit 1
echo "done"
