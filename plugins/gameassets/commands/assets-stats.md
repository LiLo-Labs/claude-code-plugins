---
name: assets-stats
description: Show what the game-asset library contains, by source, readiness and licence
---

Call `library_stats` and `list_categories` from the `gameassets` MCP server, then
summarise for the user.

Lead with what is **actually usable** rather than the headline size. Much of the
library is not directly importable — Kontakt sample libraries, shipped games, and
scrape metadata all inflate a raw total. The `tier` breakdown is the honest number.

If the user asks about a specific area, follow up with `concept_tree` to show what
exists beneath it.
