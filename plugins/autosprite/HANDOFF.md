# Handing autosprite on

Read this first. It is the state of the work, what is *measured* rather than
believed, the ordered backlog, and the dead ends that are not worth walking
again.

## Where it stands

The pipeline is sound and proven on real art. **20 CC0 sprites** (16×16 to
76×81; humanoids, creatures, props, and four cases chosen to break a silhouette
rigger) all build, with all seven verification checks passing on both backends.
350 tests, no network or model in any of them.

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

   **Run across six characters' walk cycles, and the answer is mixed.** It does
   discriminate — the SIGNS differ, correctly:

   | character | legs | what it said |
   |---|---|---|
   | grafxkid-oldhero | **-10** | "stride too wide, the legs splay and read as loose blobs" |
   | platformer-mv-male | **-7** | "the legs splay so wide they merge into one blob" |
   | fry-caped | **+7** | "leg swing too small, several frames read nearly identical" |
   | creature-horse | **+5** | "stride amplitude too small for a body this size" |
   | awkward-shieldmaiden | +6 | but arms **-8**: "the shield arm reads as a detached blob" |
   | creature-slime | **+7** | "leg swing too small" |

   It closes down the two characters whose legs splay and opens up the ones whose
   legs barely move. That is not a canned response. It also independently
   corroborated a measurement: it called the shieldmaiden's shield arm a
   detached blob, and shed measures 5.6% on her attack.

   Three biases were visible in that table. **One is now fixed.**

   - **It judges the motion, not the rig.** ~~Fixed.~~ The critic is now shown
     the RIG — every part, its role, and its box as fractions of the sprite —
     alongside the contact sheet, and is asked to check the rig against the
     picture *first*. It can now answer verdict `"rig"` with a list of
     `rig_problems` and no adjustments at all, and `refine()` stops immediately
     rather than tuning motion on top of a wrong skeleton.

     The proof is the case that exposed the bias. On `creature-slime`, rigged
     (wrongly) as a humanoid, it used to advise `{"leg_near": {"angle": 7}, ...}`
     on limbs that do not exist. It now returns:

     > This is a legless, armless slime blob; `arm_far`, `arm_near`, `leg_far`
     > and `leg_near` carve limbs out of a body that has none.
     >
     > The `head` box `[0.00-0.11]` takes only the top sliver of the blob, while
     > the face sits well below it inside the torso part.
     >
     > `torso` spans the full width and overlaps both arm boxes, so the same
     > pixels are drawn by parts that rotate in opposite directions, creating
     > the vertical seam.

     …with `adjustments: {}`. Every one of those three is true and checkable
     against the rig table. This makes the critic useful for a second job it
     could not do before: **auditing the rigger**. Its rig complaints are the
     cheapest source of leads for backlog item 2.

   Two biases remain:

   - **It never says "good".** Six of six came back "loose". It will always find
     something, so a round is not evidence that anything was wrong. The prompt
     now warns it about this bias explicitly; that has not been re-measured
     across the six-character sweep, and doing so is the next check.
   - **It always reaches for the same four roles** (both arms, both legs), and
     touched `torso` in four and `root` in two. It has not once proposed a
     change to `head`, `tail` or a scale channel.
2. **Bring `_creature` up to `_humanoid`.** Half done.

   The classification half is fixed: `find_split` now looks past up to two
   merged rows at the floor, because hooves, boots on a ground line and baked
   contact shadows all merge the last row back into one span. A winged pony with
   six clearly parted rows of legs was being demoted to a one-piece prop by its
   hooves meeting on the final row. Pegasus and dragon now rig as creatures.

   **The builder half is not**, and the numbers say so plainly. `_creature`
   still places the head, tail and belly by proportion rather than measurement,
   and the result is that a correctly-classified pegasus animates WORSE than the
   static prop it used to be:

   | | as a prop (before) | as a creature (now) |
   |---|---|---|
   | dragon walk | 0.0% (static) | **0.0%**, and it moves |
   | pegasus walk | 0.0% (static) | **9.8%** |

   The dragon is a clear win. The pegasus trades "static but clean" for
   "animated but shedding a tenth of itself", which is not obviously better. The
   classification is still right — a pegasus is a creature — so the fix belongs
   in `_creature`: find the spine, the head end and the leg pairs from the
   silhouette the way `_humanoid` now finds the neck and the hips. Start by
   finding which part of the pegasus rig sheds; the wings are the obvious
   suspect, since they are currently swallowed into `body`.
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
