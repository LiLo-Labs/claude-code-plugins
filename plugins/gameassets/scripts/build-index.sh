#!/bin/bash
# Emits INDEX.tsv: one row per PACK.
# A pack is either a standalone archive, or the deepest directory that directly
# contains files. Archive rows report the archive's internal contents (read from
# the zip central directory, no extraction); directory rows report what's on disk.
ROOT="$HOME/GameAssets"
OUT="$ROOT/INDEX.tsv"
printf 'source\tpack\tkind\tsize_mb\tfiles\ttop_types\n' > "$OUT"

exts() { grep -o '\.[A-Za-z0-9]\{1,13\}$' | tr 'A-Z' 'a-z' | sort | uniq -c | sort -rn \
         | head -4 | awk '{printf "%s:%s,", substr($2,2), $1}' | sed 's/,$//'; }

archive_row() {                       # $1=source $2=path
  local f="$2" listing n top
  case "$f" in
    *.zip)          listing=$(unzip -Z1 "$f" 2>/dev/null) ;;
    *.tar)          listing=$(tar tf  "$f" 2>/dev/null) ;;
    *.7z)           listing=$(7z l -ba -slt "$f" 2>/dev/null | sed -n 's/^Path = //p') ;;
    *.tar.gz|*.tgz|*.unitypackage) listing=$(tar tzf "$f" 2>/dev/null) ;;
    *)              listing="" ;;
  esac
  n=$(printf '%s\n' "$listing" | grep -c . 2>/dev/null); [ -z "$listing" ] && n="?"
  top=$(printf '%s\n' "$listing" | exts)
  printf '%s\t%s\tarchive\t%s\t%s\t%s\n' "$1" "${f#$ROOT/}" \
    "$(( $(stat -f %z "$f") / 1048576 ))" "$n" "${top:--}" >> "$OUT"
}

for coll in "$ROOT"/*/; do
  src=$(basename "$coll")
  # standalone archives anywhere in this collection
  while IFS= read -r f; do archive_row "$src" "$f"; done < <(
    find "$coll" -type f \( -iname "*.zip" -o -iname "*.tar" -o -iname "*.tgz" \
         -o -iname "*.tar.gz" -o -iname "*.unitypackage" -o -iname "*.7z" \) 2>/dev/null)
  # directories that directly contain non-archive files -> one aggregated row
  while IFS= read -r d; do
    files=$(find "$d" -maxdepth 1 -type f ! -name ".*" ! -iname "*.zip" ! -iname "*.tar" \
              ! -iname "*.tgz" ! -iname "*.unitypackage" ! -iname "*.7z" 2>/dev/null)
    [ -z "$files" ] && continue
    n=$(printf '%s\n' "$files" | grep -c .)
    top=$(printf '%s\n' "$files" | exts)
    bytes=$(printf '%s\n' "$files" | tr '\n' '\0' | xargs -0 stat -f %z 2>/dev/null | awk '{s+=$1} END{print s+0}')
    printf '%s\t%s\tfiles\t%s\t%s\t%s\n' "$src" "${d#$ROOT/}" \
      "$(( bytes / 1048576 ))" "$n" "${top:--}" >> "$OUT"
  done < <(find "$coll" -type d 2>/dev/null)
done

# Second pass: packs that are archives-of-archives. Reporting them by inner-zip
# count is truthful but useless (a 5.5 GB pack read as "8 files"), so recurse one
# level and emit a row per inner archive, tagged "nested".
NEST=$(mktemp -d)
awk -F'\t' 'NR>1 && $6 ~ /^zip:/ {print $2}' "$OUT" | while IFS= read -r pack; do
  src="$ROOT/$pack"
  [ -f "$src" ] || continue
  rm -rf "${NEST:?}"/*
  unzip -q -o "$src" -d "$NEST" 2>/dev/null || continue
  find "$NEST" -name "*.zip" ! -name "._*" | while IFS= read -r inner; do
    listing=$(unzip -Z1 "$inner" 2>/dev/null)
    n=$(printf '%s\n' "$listing" | grep -c .)
    [ "$n" -eq 0 ] && continue
    top=$(printf '%s\n' "$listing" | exts)
    printf 'nested\t%s :: %s\tarchive\t%s\t%s\t%s\n' "$pack" "$(basename "$inner")" \
      "$(( $(stat -f %z "$inner") / 1048576 ))" "$n" "${top:--}" >> "$OUT"
  done
done
rm -rf "$NEST"

echo "packs indexed: $(( $(wc -l < "$OUT") - 1 ))"
