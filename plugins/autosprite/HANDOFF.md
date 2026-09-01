# Handing autosprite on

Read this first. It is the state of the work, what is *measured* rather than
believed, the ordered backlog, and the dead ends that are not worth walking
again.

## Where it stands

The pipeline is sound and proven on real art. **20 CC0 sprites** (16×16 to
76×81; humanoids, creatures, props, and four cases chosen to break a silhouette
rigger) all build, with all eight verification checks passing on both backends.
438 tests, no network or model in any of them.

Quality, measured as **debris** — the share of a frame's pixels not connected to
its main blob, against the source's own figure:

| worst-frame shed, all 7 clips | silhouette backend |
|---|---|
| the 20-sprite corpus, at the start | 89.4% |
| after quadrupeds read their legs as columns | 68.6% |
| after the automatic repair | 44.3% |
| after the landmark fixes and a grounded shadow | **39.4%** |

And on the **vision backend**, which is the recommended one, the whole corpus
now measures **25.4%** -- of which 23.8 points are the potion's spin alone.
Every character in the corpus is at or under 0.9%, including
`platformer-grass-prowne`, whose jump the silhouette rigger cannot save (15.4%)
and whose vision rig holds together completely. All twenty build with all seven
checks passing.

**Eighteen of the twenty sprites now shed nothing on any animation.** What is
left is one character and one prop: `platformer-grass-prowne` (15.4% on jump,
an 8-pixel-wide character whose limbs are 2 pixels across) and
`props-potion-funnydude` (23.8% on spin, the cork coming off as the 2px neck
vanishes mid-squash). Both are reported by name, frame and part in the build's
`repairs`, and the repair says of both that damping cannot fix them.

Note that the corpus comparison harness had a bug worth remembering: it took
the debris baseline from the RAW png, background and all, so a sprite drawn in
two pieces was scored against a baseline of zero. Any figure measured before
that was fixed is inflated for `grafxkid-oldhero`, the only corpus sprite the
bug touched.

`scripts/build.py` warns per clip which frame sheds most, so a regression
announces itself.

## The thing to understand before changing anything

**Debris measures "came apart", not "reads wrong".** A robed figure whose hip
line is an admitted guess scores 0% and still walks badly. Every metric tried so
far has this shape, and the honest position is that no cheap metric has yet been
found that catches a *bad pose*. The GIFs in `preview/` remain the only real
review, which is why the skill insists on watching them.

That gap is what backlog item 1 exists to close.

## What the rig audit found

The rig-aware critic can be pointed at a rig instead of at a motion, and asked
only "is this rig right for this picture?". Run across all 20 sprites
(`/tmp/rig_audit.py`), **9 came back blaming the rig**, and its complaints are
specific and checkable rather than vague. Four themes, in the order they are
worth fixing:

1. ~~**Front-facing sprites get a profile rig.**~~ **Done.** Both top-down
   assets were called out independently: "a sagittal side-view rig applied to a
   sprite that has no depth axis", "there is no near/far side". Both measure
   0.0% debris, so the shed metric could not see it at all. `--facing` now takes
   `front` and `back`, and three things follow from it:

   - **Both limbs of a pair are drawn in front of the torso** and named left and
     right rather than near and far. The roles are untouched, because every
     animation and every exporter dispatches on role.
   - **Every clip trades its swing for travel** (`Animation.fronted`). A leg
     walking towards the camera foreshortens; what a viewer reads is the foot
     leaving the floor. The phase is kept and only what it drives changes, so
     limbs in counter-phase stay in counter-phase without this needing to know
     which side of the body each one is on. Measured on the built frames, the
     feet now alternate by 2-6px where a profile rig alternates them by 0.
   - **A face-on character is never rigged as a side-on animal.** `classify`
     reads the silhouette, and a stocky character drawn face-on is wider than
     it is tall exactly like a horse; the 16px roguelike hero was being rigged
     with its left arm as a head and its right arm as a tail.

   Asked again, the critic's "sagittal rig applied to a front view" complaint is
   gone from every sprite. What it says instead is that the template rigger's
   BOXES are wrong on these characters -- the helmet left inside the torso, legs
   captured as a 4%-tall sliver of foot. That is true, it is theme 3 below, and
   it is the next thing to fix.
2. **Limbs invented on blob characters.** The slime and the sumo hulk both get
   arms carved out of a body that has none: "rotating them punches holes in the
   body and leaves floating fragments". The slime is the corpus's worst
   remaining shed at 18.0%.
3. ~~**Boxes that swallow their neighbours.**~~ **Two of three done.**

   - **What a character holds up is not its head.** A raised sword, a musket
     barrel, a staff, a plume, a pair of horns: all stand above the head as a
     column a few pixels across, and all of them ARE the narrowest rows, so the
     neck search walked straight into them. The shieldmaiden's neck landed at
     row 4 of 23, inside her horns, and the rig called her sword tip a head and
     animated her helmet as torso. `find_crown` now finds where the character
     starts -- the topmost row reaching 35% of its widest -- and the neck is
     searched below that. Rows above still belong to the head box; horns are
     part of a helmet.
   - **A silhouette that only widens downwards has no neck to find.** A hood, a
     helmet worn over the shoulders, a slime: the narrowest row is just the top
     of the search band, and taking it made the head three rows of an
     eighteen-row character. `find_neck` now checks that its answer is a local
     minimum and falls back to a proportion when it is not. Head boxes: musket
     officer 3 rows -> 7, necromancer 3 -> 6, slime 3 -> 9, shieldmaiden from
     her sword tip to her whole horned helmet.
   - **A gap between two boots is not a hip.** The shieldmaiden's silhouette
     parts on its last row alone, so her "legs" were one row of boot swung about
     a joint fifteen rows above them. A parting is now believed only if it
     leaves more than three rows AND more than 15% of the character below it.
     Three characters gained real leg boxes with no change in shed.

   Still open in this theme: the head box that reaches the image edge because a
   raised weapon is inside it. The weapon wants its own `prop` part parented to
   an arm, which the silhouette cannot find and the vision backend can.
4. ~~**A baked contact shadow rides the character.**~~ **Done.** Not from the
   audit but from a parallel investigation, and the same shape of bug: the 16px
   hero stands on a five-pixel shadow a row below his boots, and rigged as part
   of him it rode the root -- five rows off the ground at the apex of a jump,
   two per walk step, with the ground line pumping along with the animation.
   Worse, both leg boxes reached the bottom of the image, so the shadow was
   split between two counter-rotating legs and torn in half.

   `find_shadow` now recognises a component lying below the character's feet
   (and only below: a floating orb or a held-out lantern is a separate
   component too, and belongs to the character), and gives it a `shadow` part
   that `world_transforms` hands the identity. It stays exactly where the
   artist drew it. Measured: the character's lowest row is now the same in
   every frame of every clip, where it moved five rows across a jump before,
   and his worst clip went 1.3% -> 0.2%.

   The first attempt is worth not repeating: giving the split piece wholly to
   the two legs' nearest common ancestor, the torso, does keep it in one piece
   -- and then it rides the torso instead, which measured WORSE on three of his
   five clips (-0.1% -> 3.3%, -0.3% -> 2.8%, -0.6% -> 3.7%). A shadow does not
   want a better owner, it wants not to move.

5. **Props rigged as bodies.** The sword's `hilt` is tagged `body` while
   `blade`, the bulk of the sprite, is tagged `prop` -- the split is inverted.
   The potion's `flask` box fully contains `bowl` and `neck`. These come from
   the VISION backend, not the template one.

Two cautions about using it this way. It was shown a `walk` for every asset,
including the chest and the sword, and several of its complaints are really
"a walk cycle does not apply to a treasure chest" -- true, but the harness's
fault. And its claim that overlapping boxes mean "the same pixels are drawn
twice" is **wrong about the mechanism**: `cutout` gives every pixel to exactly
one part. It is often right about the effect and wrong about the cause, which
is the normal failure mode of a critic that can see the picture but not the
code.

## Backlog, in value order

0. ~~**Repair a clip that measurably comes apart.**~~ **Done** --
   `spritepipe/repair.py`, on by default, `--no-repair` to turn it off.

   `quality.shed` already said which frame of a clip sheds worst. Rendering each
   part alone into that frame and intersecting it with the loose pixels says
   *which parts drew them* -- and doing the same to the REST pose and keeping
   only the parts that got worse stops a baked contact shadow from being blamed
   for every frame of every clip. Damping only those roles' rotation, by the
   smallest step that puts the character back together, took the corpus from
   103.7% of summed worst-frame shed to 15.4%, with eleven of the fourteen
   broken clips landing at exactly zero.

   It costs almost nothing in motion, because the other roles keep their full
   swing: measured on the six clips it repaired, frame-to-frame change fell by
   between 0.2 and 1.5 points while shed went to zero. And it costs nothing at
   all on a build where nothing is wrong -- the clip is measured, found whole,
   and handed back untouched.

   Two failure messages matter as much as the fix. When damping does not help,
   it says so and changes nothing, because a rig that far out needs a better rig
   rather than less motion. When the blamed part has no swing in that clip at
   all, it says a squash or a translation is pulling the character apart --
   which is the potion's spin, and is the one case here that is genuinely
   unsolved.

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
2. ~~**Bring `_creature` up to `_humanoid`.**~~ **Done for the legs.**

   The classification half was fixed first: `find_split` now looks past up to
   two merged rows at the floor, because hooves, boots on a ground line and
   baked contact shadows all merge the last row back into one span. A winged
   pony with six clearly parted rows of legs was being demoted to a one-piece
   prop by its hooves meeting on the final row.

   The builder half is now fixed too, and by measurement rather than by taste.
   A leave-one-out ablation — re-render the clip with one part frozen at rest
   and see how much shed goes away — put **all 9.8% of the pegasus's shed on a
   single part, `leg_far`**, and the cause was visible the moment you looked at
   it: `pair_boxes` reads a band row by row and halves any row that has not
   parted yet, which is right under a biped's hips and wrong under a horse. The
   pegasus's bottom row is one merged hoof, so the halving stretched `leg_far`
   from 5 pixels wide to 15 — a slab holding BOTH leg pairs, rotating about its
   middle.

   A side-on animal's legs are **columns**, so `leg_columns` measures each
   column's reach below the belly line, keeps the ones reaching 60% of the
   deepest, and returns their runs (bridging one-column notches). Shallow
   columns — belly fringe, contact shadow, a dragging tail tip — no longer
   widen a leg. `split_leg_groups` then splits those runs at the largest gap,
   which is the animal's own length, and `_leg_pair` builds four legs:
   **forelegs take the arm roles** and hindlegs the leg roles, matching what
   the vision backend independently chose, so the walk swings them in
   counter-phase for free.

   | | before | after |
   |---|---|---|
   | pegasus, all 7 clips | 9.7% | **0.0%** |
   | horse, all 7 clips | 9.2% | **0.0%** |
   | dragon, all 7 clips | 1.9% | **0.0%** |
   | whole corpus, template backend | 89.4% | **68.6%** |

   Every creature in the corpus now sheds nothing on any animation, with no
   other asset changed. What is NOT done: the pegasus's **wings** are still
   swallowed into `body`, because a silhouette cannot tell a wing from a
   shoulder. The vision backend finds them. That may simply be the honest
   division of labour between the two backends.

3. ~~**Per-animation exports.**~~ **Done.** `<name>-animations.zip` carries one
   folder per clip -- `<anim>/spritesheet.png`, `<anim>/atlas.json`,
   `<anim>/frames/01.png…` -- which is the shape autosprite.io's download has and
   what a user feeding an importer one animation at a time (GameMaker's
   multi-select flow is exactly that) needs instead of a flat archive of every
   frame of every clip.

   Every frame is cut out of the finished sheet rather than kept from before
   packing, and a new **ANIMZIP** check proves each one byte-identical to its
   master crop and to its own strip. A second copy of the same pixels is
   precisely the thing that drifts silently; it only earns its place if that
   cannot happen.

4. ~~**`--frames`, `--frame-size`.**~~ **Done.** `--frames N` (2-64) resamples
   every clip; because a track is a continuous curve this is a finer sampling of
   the same movement rather than an interpolation of finished pictures, and fps
   moves with the count so the timing is unchanged. `--frame-size N` (8-512)
   puts every frame in a square cell with the character standing at the bottom
   centre, so every clip of every character shares one floor and one origin, and
   refuses rather than crops when the art does not fit.

   **Loop points are still open** and are the cheapest remaining parity item:
   autosprite.io exposes loop start/end, and here it is atlas metadata plus two
   flags -- no pixels change.
5. ~~**A wider motion library.**~~ **Done for the obvious eight.** Fifteen
   character clips now: idle, walk, run, dash, climb, crouch, jump, land,
   attack, block, cast, throw, hurt, die, sleep, plus the `action` and
   `everything` preset sets.

   Every one was authored with the pendulum lesson applied and then measured
   across the corpus: **all 20 sprites build all 15 clips with all 8 checks
   passing, and only two clips anywhere exceed 5% shed** -- the two already
   known. Two clips carry a caveat the skill passes on to the user: `climb`
   reads as reaching rather than gripping, because a profile drawing has no
   front view to turn towards a wall, and `sleep` lays the character over with
   a root rotation, the same trick `die` uses, because a standing drawing
   cannot be folded into a lying pose any other way.

   Tuning three of them was driven by the new distinct-picture warning rather
   than by taste: `block`'s guard now overshoots and settles instead of holding
   three identical frames, and `idle`, `crouch` and `sleep` peak their breath
   off-centre -- quick in and slow out, which is both what breathing is and
   what stops a four-frame loop drawing the same picture on both off-beats.

6. **Eight directions that are actually drawn.** Half done. A supplied front or
   back reference is now rigged **face-on** rather than with the side view's
   facing, which had been quietly giving a picture with no depth axis a
   sagittal near/far rig -- the exact defect `--facing front` exists to fix,
   reintroduced through the back door for anyone who supplied the extra
   references. The southward walk of a four-direction sheet now lifts its feet
   where the eastward one sweeps its legs across the picture.

   What is still open is the harder half: N and S remain `substituted` when no
   reference is supplied, and no amount of rigging can invent the back of a
   head. The honest ceiling here is what the labels already say.

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
- **Rejecting an "arm" too thin to be an arm.** The same reasoning that fixed
  the boot gap, applied one limb up, and it does not survive contact: measured
  across the corpus at every threshold that fires, it makes things WORSE (total
  worst-frame shed 36% at 0.09, 54% at 0.15, 87% at 0.25, 117% at 0.35). A
  46px platformer hero whose arms show as a 10%-tall sliver goes from 0% to
  17.8% on its walk when that sliver is replaced by the outer third of the
  torso. The critic is right that a two-row pauldron is not an arm; it is still
  a better thing to swing than an invented one, because it barely moves. Only
  the LEG half of this idea pays.

- **Telling front-facing from side-facing by symmetry.** A front-on character
  is bilaterally symmetric and a profile is not, so this looks like a free
  measurement. It is not: measured over the corpus, silhouette symmetry puts a
  right-facing platformer hero at 0.93 and a front-facing RPG sprite at 0.93,
  and the front-facing range (0.73-1.00) sits entirely inside the side-facing
  one (0.14-0.93). Mirroring the COLOURS instead -- on the theory that a
  profile has one eye off the centreline -- separates them no better (front
  0.23-1.00, side 0.07-0.77). A standing character's outline is roughly
  symmetric whichever way it faces. Facing has to be told, by the user or by
  the vision backend; it cannot be measured from the art.
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
