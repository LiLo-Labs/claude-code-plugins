#!/usr/bin/env python3
"""Stage 2 — Replace image placeholders with size-tiered descriptions.

Walks all `**Embedded image (…):** `<path>`` placeholders in `convert/*.md`.
Each placeholder gets replaced based on the referenced image's byte size:

  - <15 KB  →  `*[decorative icon — NKB bullet/glyph; no informational content]*`
  - <50 KB  →  `*[small graphic — NKB; likely logo/icon]*`
  - ≥50 KB  →  `*[graphic — NKB @ <path>; unviewed, likely meaningful — see file for details]*`

Meaningful images (≥15 KB) should then be reviewed by a smart agent that
shrinks them to thumbnails and writes detailed descriptions in place of these
fallback tags. This script's `--author-descriptions` flag accepts a JSON file
mapping `"<stem>/pageN_imgM.png"` → `"description"` and overrides the fallback.

Usage:
    python3 embed_images.py --dir <processed-folder>
        [--author-descriptions descriptions.json]

Operates in place on the markdown files produced by convert.py.
"""
from __future__ import annotations
import argparse, json, pathlib, re

PLACEHOLDER = re.compile(r"^\*\*Embedded image \([^)]+\):\*\* `([^`]+)`\s*$", re.MULTILINE)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="Processed folder (same --output used by convert.py)")
    ap.add_argument("--author-descriptions", default=None,
                    help="Optional JSON file mapping relpath → description")
    args = ap.parse_args()

    root = pathlib.Path(args.dir).expanduser().resolve()
    authored: dict[str, str] = {}
    if args.author_descriptions:
        authored = json.loads(pathlib.Path(args.author_descriptions).read_text())

    def describe(rel: str) -> str:
        path = root / rel
        key = str(pathlib.Path(rel).relative_to("embedded_images"))
        if key in authored:
            return f"**[Image — {key}]** {authored[key]}"
        if not path.exists():
            return f"*[missing image file: `{rel}`]*"
        size_kb = path.stat().st_size // 1024
        if size_kb < 15:
            return f"*[decorative icon — {size_kb}KB bullet/glyph; no informational content]*"
        if size_kb < 50:
            return f"*[small graphic — {size_kb}KB; likely logo/icon, low informational value]*"
        return f"*[graphic — {size_kb}KB @ `{key}`; not viewed in detail, size suggests a chart/diagram worth manual review]*"

    total = 0
    for md in sorted(root.glob("*.md")):
        text = md.read_text()
        n = 0
        def sub(m):
            nonlocal n
            n += 1
            return describe(m.group(1))
        new = PLACEHOLDER.sub(sub, text)
        if n:
            md.write_text(new)
            print(f"{md.name}: {n} placeholders")
            total += n
    print(f"\nTotal replaced: {total}")

if __name__ == "__main__":
    main()
