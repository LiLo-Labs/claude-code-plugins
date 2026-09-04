---
name: assets-find
description: Search the game-asset library by concept, keyword, licence or readiness
---

Search the local game-asset library for: **$ARGUMENTS**

Use the `gameassets` MCP tools. Choose the right one:

- **`search_concept`** — when the request names a *kind of thing* (belt, clothing,
  weapon, tileset, dungeon, piano). Walks the IS_A taxonomy, so `clothing` also
  returns belts, coats and boots. Set `include_parts` to also match components
  (a belt's buckle, strap, eyelet).
- **`search_files`** — when the request is about a *specific file property*:
  an extension, an exact pixel size (`"16x16"`), a filename fragment.
- **`search_assets`** — when the request is about a *whole pack* rather than
  individual files.
- **`concept_tree`** — when the user asks what categories exist, or where a
  concept sits.

Then report:
1. What you found, grouped sensibly — not a raw dump.
2. **The licence position.** Call `get_pack` on anything you would recommend.
   Say plainly if it is `commercial=NO`, or if no licence file exists in the
   archive — for most packs the terms live on the purchase page, not in the
   download, and absence of a licence file is not permission.
3. **What work it needs** via `how_to_use` if the tier is not `ready`.

Prefer CC0 packs (`source=cc0`) when the user just needs something that works —
they carry no attribution or restriction burden.
