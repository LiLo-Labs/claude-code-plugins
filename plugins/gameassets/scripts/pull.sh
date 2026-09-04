#!/bin/bash
# Find a pack in INDEX.tsv and extract it somewhere useful.
#
#   ./pull.sh tileset                 # search only, show matches
#   ./pull.sh manaseed ~/proj/assets  # extract the single best match there
#
# Extracts one pack, not the library. Always prints the licence files it finds,
# because the licence is per-pack and is the thing that decides if you can ship it.
ROOT="$HOME/GameAssets"; I="$ROOT/INDEX.tsv"
q="$1"; dest="$2"
[ -n "$q" ] || { echo "usage: pull.sh <search> [dest-dir]"; exit 1; }

matches=$(awk -F'\t' -v q="$(echo "$q" | tr 'A-Z' 'a-z')" \
  'NR>1 && tolower($2) ~ q {printf "%s\t%s\t%s\t%s\n", $4, $5, $6, $2}' "$I" | sort -rn)
[ -z "$matches" ] && { echo "no match for '$q'"; exit 1; }

if [ -z "$dest" ]; then
  printf '%8s %8s  %-34s %s\n' MB FILES TYPES PACK
  printf '%s\n' "$matches" | head -20 | awk -F'\t' '{printf "%8s %8s  %-34s %s\n",$1,$2,substr($3,1,32),$4}'
  n=$(printf '%s\n' "$matches" | grep -c .)
  [ "$n" -gt 20 ] && echo "  ... $((n-20)) more"
  exit 0
fi

pack=$(printf '%s\n' "$matches" | head -1 | cut -f4)
src="$ROOT/$pack"
name=$(basename "$pack"); name="${name%.*}"
out="$dest/$name"
mkdir -p "$out"
echo "pack:   $pack"
echo "dest:   $out"
case "$src" in
  *.zip)          unzip -q "$src" -d "$out" ;;
  *.7z)           7z x -o"$out" "$src" >/dev/null ;;
  *.tar)          tar xf "$src" -C "$out" ;;
  *.tar.gz|*.tgz) tar xzf "$src" -C "$out" ;;
  *.unitypackage) "$ROOT/_tools/unpack-unitypackage.sh" "$src" "$out" ;;
  *)              cp -R "$src" "$out"/ ;;   # already-extracted pack
esac
echo "files:  $(find "$out" -type f | wc -l | tr -d ' ')"
find "$out" -type f | sed 's/.*\.//' | tr 'A-Z' 'a-z' | sort | uniq -c | sort -rn | head -5 | sed 's/^/        /'
echo "LICENCE files found (read before shipping):"
find "$out" \( -iname "*licen*" -o -iname "*eula*" -o -iname "*terms*" -o -iname "*readme*" \) \
  | head -6 | sed "s|$out|        .|"
