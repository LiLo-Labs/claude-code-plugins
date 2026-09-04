---
name: gameassets
description: Use when the user needs game art, audio, 3D models, tilesets, UI or VFX for a game project, or asks what assets they own — "do I have a dungeon tileset", "find me a sword sprite", "what 3D models do I have", "can I ship this asset". Searches a local asset library indexed by concept taxonomy, licence, and the work each pack needs before it is usable. Also use before buying or downloading any game asset, to check whether it is already owned.
---

# Game asset library

A local library at `$GAMEASSETS_ROOT` (default `~/GameAssets`), searchable through the
`gameassets` MCP server.

## What is indexed

| | |
|---|---|
| packs | source, size, licence, readiness tier, deep description |
| individual files | name, path inside archive, extension, size |
| images | **real pixel dimensions**, read from file headers |
| concepts | IS_A hierarchy + HAS_PART edges, domain-gated |
| concept tags | per-file, walked transitively at search time |

Call `library_stats` for the actual figures — they are specific to this
installation and change as packs are added.

## The three questions to answer, in order

**1. Do we own something suitable?** — `search_concept` walks the taxonomy, so asking
for `clothing` also returns belts, boots and coats. `search_files` filters by extension
or exact pixel size. Never conclude the library lacks something without trying a
concept search; filename search alone under-reports badly.

**2. Can it be shipped?** — this is the question that costs real money to get wrong.
Call `get_pack` and read the `commercial` field:

- `YES` — the pack's own licence permits commercial use
- `NO` — **it does not.** Two packs in the library are in this state.
- `UNCLEAR` — a licence exists but is silent
- *absent* — **no licence file inside the archive at all.** Usually the majority of a
  library. Terms live on the purchase page. Say this plainly rather than implying
  permission.

CC0 packs (`source=cc0`, 327 packs) carry no attribution or restriction burden. Prefer
them when the user just needs something that works.

**3. What work does it need?** — `how_to_use` gives the tool, the steps and the caveats.
Tiers: `ready` (import directly), `unpack` (a script here handles it), `tool` (needs a
third-party app), `game` (a shipped game, not an asset pack), `metadata` (not an asset).

## Beware the headline size

Raw library size is a poor guide to usable content. Kontakt sample libraries, shipped
games and scrape metadata can dominate a total while contributing nothing importable.
**The `tier` breakdown from `library_stats` is the honest number** — lead with that.

## Maintenance

`/assets-reindex` rebuilds everything. Stage order matters — see that command.
