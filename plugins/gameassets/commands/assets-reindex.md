---
name: assets-reindex
description: Rebuild the asset index, licences, descriptions, database and concept graph
---

Rebuild the game-asset library index. The library root is `$GAMEASSETS_ROOT`
(default `~/GameAssets`).

Run in this order — each stage consumes the previous one's output:

```bash
cd "${GAMEASSETS_ROOT:-$HOME/GameAssets}"
"${CLAUDE_PLUGIN_ROOT}/scripts/build-index.sh"          # archives -> INDEX.tsv
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/scan-licences.py" # licence text -> licences.json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/describe.py"      # deep descriptions
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/index-files.py"   # 814k individual files
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/build-db.py"      # pack rows + categories
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/build-graph.py"   # concept graph + tagging
```

Run them in the background — the full chain takes several minutes.

**Order matters and is not arbitrary**: `build-db.py` drops and rebuilds only its
own tables, so it must not be run before `index-files.py` has populated `files`.
`build-graph.py` reads `files`, so it must run last.

Report the tier and licence distribution afterwards so the user can see what changed.
