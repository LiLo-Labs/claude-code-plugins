#!/usr/bin/env bash
# Downloads draw.io webapp for self-hosted embed mode.
# Caches in vendor/drawio/ — excluded from git.
set -euo pipefail

DRAWIO_VERSION="${DRAWIO_VERSION:-v26.0.9}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$(dirname "$SCRIPT_DIR")"
VENDOR_DIR="$PLUGIN_DIR/vendor/drawio"
MARKER="$VENDOR_DIR/.version"

# Already vendored?
if [ -f "$MARKER" ] && [ "$(cat "$MARKER")" = "$DRAWIO_VERSION" ]; then
  exit 0
fi

echo "Downloading draw.io $DRAWIO_VERSION webapp..."

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

# Clone just the webapp (shallow, sparse checkout)
git clone --depth 1 --filter=blob:none --sparse \
  --branch "$DRAWIO_VERSION" \
  https://github.com/jgraph/drawio.git "$TMPDIR/drawio" 2>/dev/null

cd "$TMPDIR/drawio"
git sparse-checkout set src/main/webapp

WEBAPP="$TMPDIR/drawio/src/main/webapp"

# Create vendor dir
rm -rf "$VENDOR_DIR"
mkdir -p "$VENDOR_DIR"

# Copy minimal file set for embed mode
cp "$WEBAPP/index.html" "$VENDOR_DIR/"
cp "$WEBAPP/favicon.ico" "$VENDOR_DIR/" 2>/dev/null || true

# JS — core embed files only (skip integrate.min.js, mermaid, onedrive, dropbox, orgchart)
mkdir -p "$VENDOR_DIR/js"
for f in PreConfig.js app.min.js PostConfig.js extensions.min.js \
         shapes.min.js shapes-14-6-5.min.js stencils.min.js; do
  cp "$WEBAPP/js/$f" "$VENDOR_DIR/js/" 2>/dev/null || true
done
# Small utility dirs needed by the editor
for d in sanitizer deflate spin freehand rough jszip cryptojs; do
  [ -d "$WEBAPP/js/$d" ] && cp -r "$WEBAPP/js/$d" "$VENDOR_DIR/js/"
done

# Styles
cp -r "$WEBAPP/styles" "$VENDOR_DIR/"

# Resources (i18n) — copy all, relatively small
cp -r "$WEBAPP/resources" "$VENDOR_DIR/"

# Images (editor icons) and img (clipart/stencils)
cp -r "$WEBAPP/images" "$VENDOR_DIR/"
cp -r "$WEBAPP/img" "$VENDOR_DIR/"

# Stencil XML definitions
cp -r "$WEBAPP/mxgraph" "$VENDOR_DIR/"

# Plugins dir (some built-in plugins)
[ -d "$WEBAPP/plugins" ] && cp -r "$WEBAPP/plugins" "$VENDOR_DIR/"

# Service worker (draw.io expects it)
cp "$WEBAPP/service-worker.js" "$VENDOR_DIR/" 2>/dev/null || true
cp "$WEBAPP/service-worker.js.map" "$VENDOR_DIR/" 2>/dev/null || true

# Write version marker
echo "$DRAWIO_VERSION" > "$MARKER"

SIZE=$(du -sh "$VENDOR_DIR" | cut -f1)
echo "draw.io $DRAWIO_VERSION vendored to vendor/drawio/ ($SIZE)"
