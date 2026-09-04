---
name: assets-deliver
description: Extract matching assets out of the library into a project folder, with credits
---

Deliver assets from the library into a project: **$ARGUMENTS**

First **search** so the user sees what they are getting, then deliver. Never deliver
blind — a silent copy of the wrong 50 files is worse than a slow one.

```bash
S="${CLAUDE_PLUGIN_ROOT}/scripts/deliver.py"

python3 "$S" <dest> --concept tileset --ext png --limit 30 --dry-run   # preview
python3 "$S" <dest> --concept tileset --ext png --limit 30             # deliver
```

Options: `--concept` (walks the taxonomy), `--query`, `--ext`, `--pack`, `--limit`,
`--flat` (no per-pack subfolders), `--allow-noncommercial`, `--dry-run`.

It extracts individual archive members — it never unpacks a whole archive — and
writes `CREDITS.md` recording every source pack and its licence position.

**Packs whose licence forbids commercial use are withheld by default.** If any match
is withheld the tool says so and gives the count. Only pass `--allow-noncommercial`
if the user has said the project is non-commercial; then tell them which packs are
affected so it does not become a surprise later.

After delivering, tell the user to read `CREDITS.md` — for most packs there is **no
licence file inside the archive**, and absence of a licence is not permission.
