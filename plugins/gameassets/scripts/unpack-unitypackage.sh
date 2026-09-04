#!/bin/bash
# Extracts a .unitypackage into a normal folder tree.
# A .unitypackage is a gzipped tar of GUID dirs, each holding:
#   asset (the real file), asset.meta, pathname (its original path)
# Unity-only artefacts (.mat/.prefab/.unity/.shadergraph) are skipped by default.
PKG="$1"; OUT="$2"; ALL="${3:-}"
[ -f "$PKG" ] && [ -n "$OUT" ] || { echo "usage: $0 <pkg.unitypackage> <outdir> [all]"; exit 1; }
TMP=$(mktemp -d); mkdir -p "$OUT"
tar xzf "$PKG" -C "$TMP" || exit 1
n=0; skip=0
for d in "$TMP"/*/; do
  [ -f "$d/pathname" ] && [ -f "$d/asset" ] || continue
  rel=$(head -1 "$d/pathname")
  case "${rel##*.}" in
    mat|prefab|unity|shadergraph|shadersubgraph|asset|terrainlayer|cs|wlt)
      [ -z "$ALL" ] && { skip=$((skip+1)); continue; } ;;
  esac
  dest="$OUT/${rel#Assets/}"
  mkdir -p "$(dirname "$dest")"
  cp "$d/asset" "$dest" && n=$((n+1))
done
rm -rf "$TMP"
echo "extracted $n files, skipped $skip Unity-only"
