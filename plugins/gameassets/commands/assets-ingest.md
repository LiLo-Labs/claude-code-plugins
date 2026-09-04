---
name: assets-ingest
description: File new asset packs into the library and rebuild the index
---

Add new asset packs to the library: **$ARGUMENTS**

```bash
I="${CLAUDE_PLUGIN_ROOT}/scripts/ingest.sh"

"$I"                       # process everything dropped in $GAMEASSETS_ROOT/_inbox
"$I" ~/Downloads/pack.zip  # process specific files
"$I" --reindex             # rebuild without filing anything
```

Packs are routed to a collection by filename (kenney/quaternius → `cc0`,
`.unitypackage` → `fab`, sonniss → `sonniss`, and so on). Anything unrecognised goes
to `unsorted/` rather than being guessed into the wrong collection — **check
`unsorted/` afterwards and move things deliberately.**

The rebuild takes several minutes over the full library, so run it in the background
and report the tier/licence distribution when it finishes.

Before ingesting anything the user is about to *buy*, search the library first.
Duplicate purchases are the common failure with a large library.
