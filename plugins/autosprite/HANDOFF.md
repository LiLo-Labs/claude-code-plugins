# Handing autosprite on

Read this first. It is the state of the work, what is *measured* rather than
believed, the ordered backlog, and the dead ends that are not worth walking
again.

## Where it stands

The pipeline is sound and proven on real art. **20 CC0 sprites** (16×16 to
76×81; humanoids, creatures, props, and four cases chosen to break a silhouette
rigger) all build, with all seven verification checks passing on both backends.
322 tests, no network or model in any of them.

Quality, measured as **debris** — the share of a frame's pixels not connected to
its main blob, against the source's own figure:

| | silhouette backend | vision backend |
|---|---|---|
| the 16-sprite corpus | 60.5% total, was 60.5% at the start | **15.1%** |
| the 4 adversarial cases | 5.6% | **0.0%** |

`scripts/build.py` warns per clip which frame sheds most, so a regression
announces itself.

## The thing to understand before changing anything

**Debris measures "came apart", not "reads wrong".** A robed figure whose hip
line is an admitted guess scores 0% and still walks badly. Every metric tried so
far has this shape, and the honest position is that no cheap metric has yet been
found that catches a *bad pose*. The GIFs in `preview/` remain the only real
review, which is why the skill insists on watching them.

That gap is what backlog item 1 exists to close.

## Backlog, in value order

1. ~~**A vision critic loop.**~~ **Done** — `spritepipe/critic.py`, exposed as
   `animate.py --critic claude --rounds N`. It renders the clip, shows the
   contact sheet to `claude -p`, and folds the returned keyframe deltas back in;
   every round is re-measured and one that makes the character come apart is
   thrown away.

   On the robed necromancer it correctly identified "the staff arm swings too
   far and reads as a detached blob" and "the legs barely alternate", closed the
   arms and opened the leg swing from ±26° to ±39°, and the visible result is a
   modest improvement with shed unchanged at 0%.

   **Still to do here:** it has only been run on one character. Run it across
   the corpus, and find out whether its adjustments generalise or whether it
   simply re-derives the same "open the legs" advice for everything. If the
   latter, the fix is probably to feed it the animation's current keyframe table
   alongside the picture so it can see what it is adjusting.
2. **Bring `_creature` up to `_humanoid`.** The humanoid builder got the neck,
   shadow and mirror work; the creature builder did not, and it shows — a winged
   pegasus falls through to `prop`. It needs the same treatment: find the spine,
   the head end and the leg pairs from measurements rather than proportions.
3. **Per-animation exports.** One PNG + atlas per animation, and the
   folder-per-animation ZIP (`<anim>/spritesheet.png`, `atlas.json`,
   `frames/01.png…`). Concrete parity, entirely deterministic.
4. **`--frames`, `--frame-size`, loop points.** autosprite.io exposes frame
   count 2–64, frame size 32–512, and loop start/end. All three are small.
5. **A wider motion library.** Seven character clips against their ~100. Climb,
   crouch, dash, land, block, cast, throw, sleep, die-variants. Cheap to add,
   each one a readable keyframe table.
6. **Eight directions that are actually drawn.** Today N/S are `substituted`
   unless the user supplies references. The vision backend could rig a supplied
   front/back reference into the same skeleton so the directions share motion.
7. **A pose-plausibility check.** Feet planted during walk contact frames, limb
   angles inside anatomical range. Would partly close the gap in the section
   above.

## Dead ends — measured, not guessed

Do not re-try these without new evidence. Each was implemented, measured, and
reverted.

- **Snapping sub-pixel motion to whole pixels.** A 2° torso lean displaces the
  head it carries by 0.45px, which cannot be drawn honestly, so this looks
  obviously right. Measured across every animation on both test characters it
  changed **zero frames**, and was 5% faster. Not a quality fix.
- **Flooring the squash by the sprite's narrowest feature**, and then by the
  deepest squash it survives. Both assume a spin breaks at its extreme. It does
  not: at `sx=0.14` a 10px potion is a clean sliver; it comes apart in the
  MIDDLE of the range, where its 2px cork lands on the reducer's coverage
  boundary. The first version also let a single 1px highlight veto all squash.
- **Blob count with a significance floor** as a quality metric. A 2% floor hides
  exactly the loose 3px fragments that make a frame look broken.
- **Mass conservation** as a quality metric. Mass is conserved when parts are
  merely scrambled, so it passes on visibly destroyed frames.
- **Joint gap** (child pixels' distance to parent pixels). Reported zero
  detachments on frames that were obviously wrong, because the debris is a
  part's own pixels scattering, not a part separating.
- **Shed as a fine-grained score.** It is a catastrophe detector, not a dial.
  Sweeping a leg-swing delta from -8° to +60° moves shed by at most half a
  percentage point and in no consistent direction: -4° makes it slightly worse,
  +60° slightly better. This is why the critic's guardrail tolerates two points
  rather than any increase - a tighter gate rejects good adjustments at random.

## Reproducing the corpus

The sprites are CC0 from OpenGameArt and Kenney, fetched into `/tmp/sprites/` by
a workflow; they are **not** checked in (`.gitignore` excludes PNGs, and vendored
art would bloat the repo). Each has a `meta.json` recording title, author,
licence and the licence page. To rebuild it, re-run the acquisition workflow, or
fetch from the `license_page` URLs in those files.

Harnesses used during this work live in `/tmp` and are not part of the plugin:
`batch.py` (run the corpus), `wall.py` (montages and GIFs), `sheets.py`
(per-asset evaluation sheets), `compare.py` (debris table). Promote any of them
into `scripts/` if they earn it.

## Rules that have already paid for themselves

- **Measure before claiming.** Two "obvious" fixes in this plugin's history
  changed nothing at all, and one reported defect ("the head is sheared") turned
  out to be the character's own eyes at low zoom.
- **Look at the output large.** Small-scale eyeballing produced a wrong
  diagnosis twice. Render at 6–10x before judging.
- **Real art first.** Every bug fixed here was invisible to the synthetic
  fixtures and obvious within minutes of running on a real sprite.
