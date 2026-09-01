# Handing autosprite on

Read this first. It is the state of the work, what is *measured* rather than
believed, the ordered backlog, and the dead ends that are not worth walking
again.

## Where it stands

The pipeline is sound and proven on real art. **20 CC0 sprites** (16×16 to
76×81; humanoids, creatures, props, and four cases chosen to break a silhouette
rigger) all build, with all eight verification checks passing on both backends.
470 tests, no network or model in any of them.

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
3b. ~~**Props rigged as bodies.**~~ **Done, in the prompt.** The sword's `hilt`
   was tagged `body` while `blade`, the bulk of the sprite, was tagged `prop` --
   the object's main mass swinging as an accessory of a fake body. The prompt
   now says that on an inanimate object the root is its main mass, that `prop`
   is for something a CHARACTER holds, and that a rigid object gets one part
   because splitting it only gives the pieces a chance to come apart. Re-rigged:
   the sword and the flask each became a single `body` part, and the chest kept
   exactly the one joint it has -- a hinged lid, with the lock plate as an
   accessory. Debris unchanged, because those rigs were not what was breaking;
   the rigs are simply now true.

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

## A second rig audit, after all of the above

Re-running the critic over all twenty **silhouette** rigs (the first audit was
of the vision rigs, so the two are not comparable and no claim of improvement
should be made from the pair) leaves one theme, said five different ways:

> The rigger splits a single mass and calls the halves a pair -- a floor-length
> robe hem, a slime, a squat 16px blob, a tunic, a cape.

Three more complaints are the harness's fault rather than the rigger's: the
chest, gem and sword were all shown a `walk`, and "a walk cycle does not apply
to a treasure chest" is true and not a bug. One is a genuine miss the silhouette
cannot fix: `topdown-dcss` is a cloaked humanoid whose outline is a smooth bell
with no parting and no neck, so it rigs as a prop. The critic can see a head and
two arms because it can see COLOUR. That is the vision backend's job.

## What has been done

Everything the original backlog listed is finished, and it is worth knowing what
each thing was so it is not redone. In the order it landed:

| | what it was |
|---|---|
| `quality.py` | measures what a viewer sees; every other check proved only bookkeeping |
| `critic.py` | asks a vision model what is wrong, and is shown the RIG so it can answer "the rig is wrong" |
| `repair.py` | damps exactly the part that measurably came apart; 103.7% of summed shed to 15.4% |
| quadruped legs | read as COLUMNS, not rows; pegasus 9.7%→0, horse 9.2%→0, dragon 1.9%→0 |
| `--facing front\|back` | face-on rigs and face-on motion, including for a supplied `--reference-front` |
| landmarks | `find_crown` (a raised sword is not a head), a local-minimum neck (a hood has none), a boot gap is not a hip |
| `shadow` role | a baked contact shadow is the floor; it stays put |
| the walk | was a pendulum retracing itself: 8 frames, 5 pictures. A bent knee at the passing pose fixes it |
| planting | **seven** clips keep a foot on the floor; corpus foot lift 265px → 0, and the walk's bob is now emergent |
| `crouch`, `block` | their sink moved from a root translation into a leg FOLD, so it survives planting: foot lift 45px and 37px → 0 |
| `_reconnect` | a transform must not break what the artist drew in one piece; the potion's spin 23.8% → 0, corpus 44.4% → **19.5%** |
| wings | `wing_near` and `wing_far` existed in the vocabulary, were found by the rigger and given a z-order by the exporter, and were driven by NOTHING. Six clips now move them and a `fly` clip exists |
| variants | re-verified end to end on real art: a grey ramp recoloured blue keeps all three of its shades, the walk is identical, and every check passes |
| parity | `--frames`, `--frame-size`, `--fps`, loop points, per-animation ZIP, eight more animations |
| `climb` | its arm reach was cut from 58° to 46° after measurement: 58 threw a hand clear of a 45px character and took the clip to 9.4% shed, 46 takes it to 0.8% for one point of frame-to-frame change |

The full history of each, with the numbers, is in the git log; the commits lead
with the failure rather than the change.

## The new direction, and the first evidence for it

The ask has changed: not fifteen named clips for characters, but **an
open-ended set of operations applicable to any subject from a single image** --
items, buildings, weather, plants -- with modular attachment so one item works
on any host, at a quality that reads as animation rather than as motion.

Six non-character subjects are now in the corpus, all CC0 from Dr. Jamgo's
*Basic Hex Tile Set - 16x16* (licence text: "No Copyright Notice required. A
note of tribute is appreciated though.", verified 2026-09-01 at
https://opengameart.org/content/basic-hex-tile-set-16x16): a **windmill**, a
**cottage**, a **farmhouse**, a **tree**, a **wheat field** and a **mine**. The
windmill matters most: the source pack ships **four rotation frames of its
sails**, so the artist's own animation sits beside it in
`reference-cycle/` as ground truth.

**What a windmill does today.** It builds, verifies, and offers exactly two
animations: `bob` and `spin`. The rigger says *"one piece: props animate as a
whole, never articulated"*, so the only thing on offer is a house that bobs, or
a house that spins.

**What happens when you push it by hand.** The vision backend, told what it is
looking at, DOES find the sails -- `sails`, pivot [7, 5], which is the hub, at
0.72 confidence. Driving that part through a full 360° over eight frames gives
**eight distinct frames, zero palette escapes, and sails that visibly turn**.
The architecture can already do this.

It is also not good enough, and the way it fails is the specification for what
comes next:

 - **8.6% shed.** The sails' box is `[0, 0, 15, 12]` -- the whole top of the
   image, tower included -- so rotating it drags tower pixels round with it and
   leaves a hole. A part that turns continuously needs a box tight to the thing
   that turns, and 4% of the sprite already falls outside every box.
 - **`accessory` is the wrong word and nothing drives it.** It was the closest
   role available. The vocabulary has no word for "this rotates about its hub",
   "this sways from its base", "this ripples", "this flickers".
 - Compared against the artist's own four frames, ours turn and theirs turn
   *and stay attached*.

That is the whole problem stated in one subject: **the geometry works, the
vocabulary does not.**

## What was built for the new direction, and what it cost

Four stages have landed, each measured on real CC0 art rather than on fixtures.

**1. A channel may have its own timeline (`Lane`).** A keyframe carried a whole
pose, so every channel of a part shared one set of instants -- and a key that
omitted a channel was ASSERTING that channel was at rest, not that it did not
care. Overlapping action and follow-through are exactly what that forbids:
adding a late squash key to a swing drags the swing back to zero with it. A
track may now carry lanes, which override the channels they name and leave the
rest of the pose alone, so the sixteen built-in clips -- none of which uses one
-- sample exactly as before. A test pins the three numbers from `cast`'s leg
squash, and a second checks no clip has quietly grown a lane.

Every mutator now goes through a small channel API on `Track` (`has`, `values`,
`adjust`, `foreshorten`) rather than reaching into key dicts, so scaling,
the squash and travel floors, the critic's edits and repair's damping all reach
into a lane without knowing it is one.

**2. Parts are addressed by what they ARE (traits and selectors).** A part's
traits come from its role (every `accessory` is a `stalk`, every leg is a
`support`) plus whatever the rig tags it with. A track may be addressed at
`trait:stalk` or `name:sails` as well as at a role. When several tracks match one
part the most specific is the base pose and the rest COMPOSE onto it, so "every
stalk lags by a frame" adds a lag without replacing anything's authored swing.
A track may carry a `spread`, so each matched part in turn plays the curve a
little later -- one field, and it is a wave travelling across a wheat field, a
chain following the link before it, and a canopy lagging its trunk.

Seven subject clips use it: `turn`, `sway`, `gust`, `ripple`, `creak`,
`flicker`, `shimmer`. A clip that ends up driving nothing is dropped with the
missing trait named. **Measured:** `gust` and `sway`, written for trees and
flags, drive a hero's cape with 0.00% shed and every frame distinct, because the
vision rig called the cape an `accessory` and an accessory is a stalk.

**3. Outfitting.** An item is composited into the character's art at rest and
the composed image becomes the source. Doing it BEFORE anything else runs is
what makes it cost nothing: the item is a rig part parented to the arm, so
forward kinematics carries it, and every check still means what it meant --
REST holds because the composed art IS the source, and PALETTE holds because the
input now contains the sword's colours. Sockets are DERIVED from the rig (a hand
is the free end of the near arm, measured rather than assumed), which is what
makes "works with every character" true. **Measured:** a CC0 hero and a CC0
sword by two different artists, 27 colours in and 27 out, all eight checks green.

The limitation is real and stated: an item goes IN FRONT of what it hangs on,
because compositing at rest cannot record pixels hidden at rest.

**4. A channel that is not a movement (`cycle`).** A whole-numbered step along a
part's own shading ramp. Nothing moves; the light changes and the silhouette
does not. It is the strongest form of the palette guarantee here rather than a
weakening of it -- a step lands on another shade of the same ramp, and every
ramp comes from the locked source palette, so nothing can escape.

**5. `--rig`, which the README had been promising.** A corrected rig could be
previewed one clip at a time and there was no way to BUILD with it except
re-running the rigger and hoping. That is also the path a tag travels.

**6. Operators — a principle written once (`operators.py`).** An operator is a
function from (animation, rig) to animation whose only reach is a keyframe
number, so the artefact stays a readable table and the palette guarantee is
untouched by construction. Seven: `lag`, `envelope`, `taper`, `anticipate`,
`settle`, `damp`, `volume`. Three easings came with them (`back`, `elastic`,
`bounce`) because all five originals are monotone and therefore cannot overshoot
or go the wrong way first; a fourth, `arc`, bows a `dx`/`dy` pair.

**And the library uses them.** All sixteen clips give a trailing part
follow-through, off the torso, or off the head in `idle` and `die` which move
nothing else above the waist. **Measured:** fifteen of sixteen clips move a real
hero's cape where none did, and summed worst-frame shed across sixteen corpus
assets and all sixteen clips is 20.05% with the operators and 20.05% without --
no asset is worse. The gain is 0.85 rather than 1.0 because at 1.15 a pegasus's
already-swinging tail was amplified until it came away (1.82% loose), and the
amplification bought no extra motion at all.

`repair` now works in selector space. It blamed a ROLE and looked that role up
in the tracks, which stopped being how a track is addressed the moment a clip
could drive `trait:stalk` -- it would have reported a break it had no way to
touch.

**7. Two verification bugs of the same kind** -- the check was narrower than the
invariant, and the fallback hiding the gap was silent.

- **A legitimate `--front` build failed PALETTE.** The check re-ingested one
  `--reference` at default settings while the pipeline locks against every view
  at the user's actual parameters -- so any colour only the front view carries
  failed a correct build, which is what a front view is FOR. The atlas now
  records every source with the settings it was read at and a digest, and the
  check rebuilds the allowed set from those. The invariant generalised to what
  it always meant, not relaxed. Two things fall out: the check no longer needs
  to be told the reference at all, and a source that changed on disk since the
  build is reported rather than trusted.
- **`palette.enforce` was a laundry.** It snaps escapees on every frame with no
  report, which makes PALETTE pass whether or not the pipeline kept its promise
  -- and `palette.escapes`, the detector, had no production caller. It now says
  what it moved and the build warns. Instrumented across six sprites and all
  sixteen animations: **zero**.

### Findings from this work that are worth more than the code

- **A symmetric curve wastes half its frames.** `sway` swung evenly out and
  back; on the first caped hero it drew five different pictures out of eight,
  and raising the amplitude changed *nothing at all*, because the amplitude was
  never the problem -- a pendulum passes through the same angles going out and
  coming back. `sway`, `ripple` and `bob` are now asymmetric, and a test asserts
  it for every trait clip.
- **An outline lives in the ramp of whatever it outlines.** Ramps are found by
  hue and adjacency and an outline touches everything, so a brightening ramp
  step lifts the outline with the fill and the sprite goes soft at the edges.
  The rule is the art's darkest colour never moves and nothing steps down onto
  it -- the darkest of the WHOLE art, not of each ramp, because a material's own
  deepest shadow is a shade like any other.
- **A short clip has nowhere to hide.** `bob`'s keys sat between its four frame
  times, so the renderer sampled heights nobody chose and rounded two of them
  together. Keys on the frame times, at whole pixels, fixed it.
- **Looking at it beat every measurement, twice.** `shed` and `distinct_frames`
  both scored a windmill whose entire roof rotates at 0.00% and 8/8. That is why
  `quality.footprint` exists -- and pointing it at the artist's own frames then
  bought a rigging rule worth 40% to 9%.
- **A visual check passed a bug for an hour.** `palette.step_ramp` matched each
  colour against the array it was writing, so every shade in a ramp cascaded to
  the top. A washed-out sprite is a plausible thing for a brightening step to
  produce, so it looked like a property of the art rather than a defect -- and I
  had already written "pixel art has headroom downward and almost none up" into
  two docstrings and a clip note before the arithmetic said otherwise.
- **A step must stay inside the part's own material.** A torch's fire and its
  timber are both hue 21 and they touch, so the ramp finder makes them one ramp
  and a step walked the flame into the wood. Clamping to the part's own occupied
  span fixes it without needing the ramp finder to be right, and makes the
  palette claim stronger: every colour a step produces was already in that part.

## Backlog, in value order

Honest and short. The easy things are gone.

1. **The rigger splits one mass and calls the halves a pair.** The silhouette
   backend's remaining defect, said by the critic of five corpus characters: a
   floor-length robe hem, a slime, a squat blob, a tunic, a cape. It cuts the
   mass down the middle, calls the halves `leg_far` and `leg_near`, and swings
   them apart.

   **The intervention is now validated and the detector is not.** Rigging the
   necromancer's lower body as ONE part instead of two legs and asking the
   critic about both:

   | | verdict | what it said |
   |---|---|---|
   | two legs | `rig` | "a robed, legless figure whose bottom is a single skirt/hem, not two limbs... the two 'legs' swing apart and read as detached blobs floating under the body" |
   | one hem | `loose` | the rig complaint is **gone**. Instead: "the cycle is nearly frozen... the body's rise-and-fall is too shallow to register twice per cycle, which is the only thing that can sell a walk on a legless, hem-bodied character" |

   So the fix is two things, not one: rig the hem as one part, AND give such a
   character a motion that suits it -- a deeper bob and a hem sway -- because a
   walk with no legs has nothing else to read. Note that planting makes this
   worse, not better: a character with no legs has nothing to plant against, so
   `plant` produces no bob at all, which is exactly the "too shallow" complaint.
   `skeleton.posed` should skip planting a rig with no leg parts, and the walk
   would then want its authored bob back for that case only.

   Measured, without the new motion: shed is **0.0% either way** (the repair
   already stops the tearing) and liveliness FALLS by 1 to 5 points on all five
   characters. So there is no number here to justify shipping the rig change on
   its own -- the motion has to come with it.

   **The unsolved part is telling which characters want it.** Every corpus
   silhouette parts somewhere, so "never parts" does not discriminate.
   `find_split` returning None catches the necromancer correctly and `fry-caped`
   incorrectly -- the caped hero has real legs whose gap is closed near the
   floor by his cape, which is a false negative in `find_split` rather than a
   legless character. The only separator found is "the deepest parting is within
   20% of the floor" (fry-caped 11%, necromancer 39%), and that is a threshold
   fitted to two points, which this file already records going wrong twice.
   **This wants more robed and blob-shaped CC0 art before it is worth fitting.**

   And it is worth remembering what the vision backend is for: a model can see
   that a robe hem is a robe hem, and already rigs these correctly. The
   silhouette rigger saying "the hip line is a proportion rather than a
   measurement" and pointing at the vision backend may simply be the honest
   ceiling.

2. **A wider motion library still.** Fifteen character clips against
   autosprite.io's ~100. Roll, slide, swim, fly, shoot, push, pull, wave, sit,
   kneel, taunt, revive. Each is a readable keyframe table; each must be checked
   against the distinct-picture warning, because a symmetric swing draws half as
   many pictures as it claims.

3. **`topdown-dcss` is a cloaked humanoid the silhouette reads as a prop.** Its
   outline is a smooth bell: no parting, no neck. The critic can see a head and
   two arms because it can see COLOUR. Whether the classifier should ever look
   at colour is an open question and a fragile one; the vision backend already
   gets this right.

4. **The critic proposes limb angles and nothing else.** Tallied over 40 calls
   across the two rig audits: 21 verdicts of `rig`, 13 `loose`, 6 `good`, and
   of the 13 clips that drew motion advice the roles touched were `leg_far` 11,
   `leg_near` 11, `arm_near` 9, `arm_far` 8, `root` 2, `torso` 1. `head` and
   `tail`: never. A scale channel: never.

   **Two of the three biases this file used to record are now closed or were
   never real.** It says "good" six times in forty, so "it never says good" is
   gone -- showing it the rig gave it a way to be satisfied. And `head` never
   appearing is not a bias at all: every one of those calls was a `walk`, the
   `walk` has no `head` track, and the prompt correctly tells it to touch only
   channels the track already uses. That was an artefact of only ever testing
   one clip, and this entry used to claim otherwise.

   What survives is narrower and real: it has **never once proposed a scale
   change**, even though the walk now drives `sy` on both legs for the bent
   knee, and it reached for `torso` in one clip of thirteen although every walk
   drives it. Worth understanding before trusting it to tune anything subtle,
   and worth re-tallying on a clip other than `walk`.

5. **N and S remain `substituted` without a reference.** No amount of rigging
   invents the back of a head. The labels are the honest ceiling and they are
   already said out loud; this is on the list only so nobody mistakes it for an
   oversight.

## What is broken, and needs a better rig rather than a better renderer

Both are the same shape of problem: a character too small for a rigid-limb rig
at the amplitudes the library uses.

- **`platformer-grass-prowne`'s jump on the silhouette backend, 15.4%.** An
  8-pixel-wide character whose limbs are 2 pixels across. Its VISION rig holds
  together completely, which is the honest answer for a sprite this small.
  Measured, the pieces separate by 2.0 to 3.6 pixels -- a quarter to a half of
  the character's whole width -- so the composite-level version of `_reconnect`
  would draw a visible thread across it rather than closing a seam. That was
  checked and not built.
- **`grafxkid-oldhero`, 3 to 4% on the faster clips.** The corpus's smallest
  character at 10x17, and what comes away is a boot, next to the baked shadow.
  Worth knowing before chasing it: the shadow's colour is the character's
  OUTLINE colour too, so measuring "the shadow" by colour finds 57 pixels
  spread over the whole figure. That mistake has now been made twice in this
  work; measure detached COMPONENTS, not colours.

The potion's spin used to sit here too, at 23.8%, described as needing "the
reducer to preserve connectivity, which has not been attempted". It has now
been attempted and it worked: see `render._reconnect`. **The lesson is worth
keeping.** That failure was chased three times as a MOTION problem -- floor the
squash, damp the squash, damp the swing -- and reverted every time, because a
sprite comes apart in the middle of a squash rather than at its extreme. It was
never a motion problem. A transform was breaking something the artist drew in
one piece, and the fix belonged where the breakage happened.

## `shear`, and the dead end it found

**`shear` is a seventh channel: a part's top leans away from its base, in
degrees, without turning.** A rotation moves a limb; a shear deforms a surface,
which is what cloth, water and smoke do and what a hinge cannot. It is affine,
so it is one more term in a matrix that was being built anyway -- same
nearest-neighbour path, same palette guarantee, no new render code. It shares
`rotate`'s sign so a positive value in either channel tips a part the same way.

`sway` and `ripple` now drive `shear` on `trait:surface` rather than `angle`.
**Measured on a CC0 flag with the artist's own sixteen frames:** worst-frame
shed 0.22% -> 0.03%, and closest to the artist in how much of the picture it
disturbs.

**The dead end that came first.** The obvious step is to cut a continuous
surface into vertical strips and use `spread` to travel a wave across them. It
tears, and not marginally:

| rig | worst-frame shed |
|---|---|
| one cloth, sheared as a whole | **0.05%** |
| 2 strips + spread | 44.6% |
| 3 strips + spread | 30.9% |
| 6 strips + spread | 61.3% |

Rigid strips at different phases separate from each other, and `render._reconnect`
cannot help because it repairs a layer that came apart *internally*, not a gap
*between* layers. Tested at three strip counts, so it is not a tuning problem.

**And the capability it named, now built.** `wave` and `wave_phase`: each
column of a part slides vertically by a whole number of pixels, sinusoidally in
its own position, and advancing the phase makes the crest travel. It is a
PERMUTATION of the part's pixels -- nothing sampled, averaged or invented --
which is the strongest palette claim in the vocabulary.

| driving a flag's cloth | worst-frame shed | of what we disturb, the artist never touches |
|---|---|---|
| `shear`, leaning it rigidly | 0.10% | 36% |
| **`wave`, amplitude 4** | **0.00%** | **16%** |
| `wave` + a lean on top | 0.00% | 26-38% |

So cloth is not a thing that leans: adding a shear to the wave makes it worse at
every amplitude tried. `ripple` and `sway`'s surface half now drive `wave`.

### A measurement error worth more than the measurement

Every flag number above was first reported at **70-79%**, in a commit message
and in this file, and all of them were wrong. `render_pose` draws into a canvas
with a MARGIN and the art it is judged against is trimmed flush, so
`quality.footprint` was comparing a picture with a *shifted copy* of another
one. It turned a real 15% into 68%, and nothing about 68% looked wrong -- it
agreed with the story I already believed, which is why it survived.

`footprint` now takes the margin as a parameter rather than trying to infer it,
because a frame's own content box moves with the animation and there is nothing
honest to infer it from. A test asserts that the untold case gives a different
answer from the told one. The strip numbers above are unaffected: `shed` is
measured within a frame and does not care where the frame sits.

## `repair` had a wrong assumption, and the corpus found it

The file said, in a docstring, that damping is rotation-only because "a
translation moves a part without changing its shape and cannot shear it off".
Shearing a part is not the failure `shed` measures. **Coming away is**, and a
part that merely ABUTS its parent rather than overlapping it comes away the
moment it is moved at all.

A top-down RPG character found it. `topdown-eldiran-rpg` is 26x30 with legs that
are a five-pixel stub below a torso they do not overlap, and **on the face-on
path** the walk's 1.4px lift detached them: five clips at ~6%, with `repair`
correctly saying it could not help, because the rotation it was damping was
never the problem.

Two changes, and the corpus needed both:

1. **A second pass that damps translation as well as rotation.** Rotation still
   goes first and alone, so every previously-measured repair is unchanged; only
   clips that the first pass could not fix get a second chance.
2. **A limb's partner is damped with it.** Blame named `leg_far`, and damping
   `leg_far` alone left 5.96% loose *however far it was reduced*, because the
   near leg was lifting away at the same instant. Damping the pair took it to
   zero. The second justification would be enough on its own: two legs in
   counter-phase are the same limb seen twice, and damping one and not the other
   makes the cycle limp.

**Measured across the whole corpus, building every asset:**

| | before | after |
|---|---|---|
| `topdown-eldiran-rpg` | 7.14% | **0.00%** |
| `creature-slime-andhegames` | 5.45% | **0.00%** |
| assets with a problem | 3 of 28 | **1 of 28** |

The slime was fixed by the same change without being looked at: it is a 23x28
blob with two three-pixel feet under a body they barely touch, which is the same
defect wearing a different shape. Nothing else moved. The one asset left is
`platformer-grass-prowne`, an 8x23 character with 2px limbs whose vision rig
measures 0.00% -- and the build says so, by name.

## What the critic is actually worth, measured

Run on the new subject clips, it did two things nothing else here can and one
thing that had to be fixed.

**It caught a clip every measurement scored perfectly.** The corpus windmill's
turn, on the rig the vision backend returned, is 0.00% shed with 8 of 8 distinct
frames -- and the whole roof rotates with the sails. The critic returned verdict
`rig` and said: *"The tower's roof and upper wall tip and wobble with the sails
instead of standing still, so the building reads as leaning rather than the
sails spinning"*, and *"the sails are two separate blades either side of the
tower and cannot be isolated by one axis-aligned box"*. That is the diagnosis
this session reached by looking at the frames, arrived at independently.

It also said, in the same breath, that the hex tile should not have the `shadow`
role because "treating it as shadow lets the base drift and squash with the
character". **That is false**, and I repeated it before checking: a `shadow`
part is in `skeleton.GROUNDED` and keeps the IDENTITY transform in every clip,
measured across `turn`, `bob` and `pulse`. The vision backend got that role
right and the critic was reasoning from guessed semantics. The prompt now states
what each role does.

**And the first attempt at that fix was worse than the bug.** Adding "do not
report that a part will drift or squash unless a channel says it moves" made the
critic call this same visibly-broken windmill `good` on **three runs out of
three** -- because the roof it is dragging round belongs to a part that IS
driven, so the rule read as forbidding the observation. The rule now says both
halves: a part not in the channel list does not move on its own, AND a part that
is driven carries every pixel its box contains, so something standing still that
moves anyway is a box that swallowed it. Two runs after: verdict `rig` both
times, with a sharper diagnosis than the original -- one of them proposing the
tightened box by coordinates.

A prompt change is a code change and has to be measured the same way.

**It caught a rig that measured identically to a correct one.** The flag was
hand-rigged as pole + cloth. There is no pole in that drawing -- the "pole" part
was a 1%-wide sliver containing no pixels -- and the critic said so, and said the
subject should be one part with a surface trait. Rigged its way: same 0.00% shed,
same 16% footprint error, 3818 vs 3822 pixels disturbed. **No measurement here
can tell those two rigs apart.** The critic could.

**And it confabulated, on the one kind of clip where nothing moves.** Shown a
gem's `flicker` it reported that the gem popped larger, drifted sideways and
stalled for four frames. Measured: every pose has dx=0, dy=0, sx=1, sy=1, five
of six pictures are distinct, and consecutive frames differ by 379 pixels. All
three complaints were invented -- and the pipeline's guard caught it, because
the adjustments named channels no track in the clip has.

The cause was in the prompt: it told the critic the animation "was made by
cutting the character into parts and rotating them about their joints", which
is false for a clip that only steps a colour ramp. It is now given the exact
list of channels the clip writes, told the list is exhaustive, and told that
`cycle` moves nothing. Re-run on the same gem: verdict `good`, no invented
problems.

## Dead ends — measured, not guessed

### Giving a sliver arm the outer-strip fallback instead

**Found by the vision critic, and the measurement said no.** The first case
where the two disagree, and it is worth knowing which wins.

Run on eight corpus characters, the critic returned verdict `rig` on four of
them, and the same complaint each time: *"arm_far and arm_near boxes are ~1px
tall slivers that contain no arm pixels, so the driven arm swing cannot read at
all"*, and *"the character's actual arms fall inside the torso box, so they
rotate rigidly with the chest instead of swinging"*.

It is exactly right about the cause. `core_and_limbs` collects only the rows
where the silhouette parts into three spans -- correct about the PIXELS, since
an arm touching the body there belongs to the torso -- and hands back a BOX as
tall as however many rows happened to part. Measured across the corpus, arms
that genuinely separate cover 40-95% of the shoulder-to-hip band and the slivers
cover 7-33%: a shieldmaiden's arm box is **4x1**.

Treating a sliver as "not found" and using the existing outer-strip fallback
gives boxes that look right -- 4x1 becomes 4x6, 3x2 becomes 4x21 -- and makes
the animation worse:

| shipped, whole corpus | before | sliver fix, outer third | sliver fix, outer sixth |
|---|---|---|---|
| `platformer-grass-prowne` | 15.38% | 15.38% | **3.65%** |
| `platformer-mv-male` | **0.00%** | 18.66% | 11.42% |
| `fry-caped` | **0.00%** | 0.00% | 6.45% |
| worst overall | 15.38% | 18.66% | 11.42% |
| assets with a problem | **1** | 2 | 2 |

It trades one broken character for two. The narrower strip is monotonically
better (summed pre-repair shed 144.6% at a third, 125.7% at a sixth) and still
does not get there: on a 16px-wide sprite, two outer strips leave six of
fourteen torso columns and swinging both arms apart splits the body.

**The rule underneath is the same one the hip lift found:** a guess that is
bigger is a worse guess when it is wrong, and on a character whose arms never
leave the body there is nothing in the silhouette to find. So the box is left as
it is and the RIG NOW SAYS SO -- a note naming how many rows of the band the arm
actually covers, alongside the note the "never separate" case already emitted.
The user is told to reach for a vision rig, which finds the real arms.

### Lifting the hip above where the silhouette parts

Anatomically true, looks obviously right, and it was **built, measured and
reverted**. The silhouette parts where the legs separate FROM EACH OTHER, which
is the crotch; a drawn leg's top is above that, inside the torso. Pivoting at
the split gives a short leg on a low joint, and rotating that swings the foot a
long way for very little visible bend.

It does fix the corpus's worst asset. `platformer-grass-prowne` is 8x23 with 2px
limbs and its jump threw **15.4%** of the sprite loose, which no amount of
damping recovered; lifting the hip by 40% of the visible leg length takes it to
**0.00%** through the full pipeline. Summed pre-repair shed across sixteen
character assets went 109.9% -> 99.7%.

And it is not worth it, for two reasons the synthetic fixture caught and the
corpus did not:

- **The character gains 8.3% mass as it moves.** A leg whose top is inside the
  torso reveals backfilled torso when it swings, so the silhouette grows; the
  mass-conservation test allows 5%.
- **The face-on walk's feet stop alternating entirely** -- the measured lift
  goes to exactly zero, so the clip stops reading as a walk at all.

Both are the common case, and the benefit is one asset whose VISION rig already
measures 0.00%. 25% and 60% lifts are worse than 40% and worse than none.
If this is revisited, the thing to fix first is the mass gain, and the question
to answer is why planting cancels the face-on lift once the legs are longer.



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

- **Testing whether two paired limbs are "a matched pair".** The critic's own
  suggestion, and it fails in an instructive direction. On five corpus
  characters it says the same thing five ways -- a robe hem, a slime, a squat
  blob, a tunic, a cape -- the rigger has cut ONE mass in half and called the
  halves a pair. So compare them: area ratio, and how much palette they share.
  Measured, the two ranges lie exactly on top of each other (area: bad
  0.72-1.00, good 0.65-1.00; palette: bad 0.54-1.00, good 0.33-1.00), and the
  bad cases score HIGHER on similarity, because two halves of one uniform mass
  are the most similar pair it is possible to cut. Similarity is not just a weak
  signal here, it points the wrong way.

  This is the silhouette backend's real ceiling, and it is where the vision
  backend earns its place: a model can see that a robe hem is a robe hem. The
  docs already say so.

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

The sprites are CC0 from OpenGameArt and Kenney, fetched into `/tmp/corpus/` by
a workflow; they are **not** checked in (`.gitignore` excludes PNGs, and vendored
art would bloat the repo). Each has a `meta.json` recording title, author,
licence, licence text, download URL and the date the licence was verified. To
rebuild it, re-run the acquisition workflow, or fetch from the `license_page`
URLs in those files.

Twenty of the subjects are characters, creatures and props. Six are **not
characters at all**, and were added for the generalisation work:

| Slug | Subject | Why it is in the corpus |
|---|---|---|
| `subject-windmill-drjamgo` | windmill | A building with a moving part, and the pack ships the artist's own four sail-rotation frames as `reference-cycle/` ground truth |
| `subject-cottage-drjamgo` | cottage | A building with nothing that moves — the honest answer for it is chimney smoke, which is not a rigid part |
| `subject-farmhouse-drjamgo` | farmhouse | A second building, so a rule found on the cottage has somewhere to be wrong |
| `subject-tree-drjamgo` | tree | Sways from the base; the canopy should lag the trunk |
| `subject-wheatfield-drjamgo` | wheat field | A *field* of things, where the motion is a travelling wave and no single part owns it |
| `subject-mine-drjamgo` | mine entrance | Mostly static with one small feature; the case for "animate almost nothing" |

Two more carry the artist's own animation of the same motion, which is what
`quality.footprint` needs and what the hex tiles are too small to provide:

| Slug | Subject | Ground truth |
|---|---|---|
| `subject-torch-xlive99` | a wall torch | XLIVE99, CC0, six frames of the flame. 32x32, ten colours, clean pixel art. The bracket never moves, so it isolates `flicker` exactly |
| `subject-flag-sbs` | a flag | Screaming Brain Studios, CC0 (the pack ships its own `License.txt` saying so), **sixteen** frames of the wave at 192x136. Antarctica, as the least politically loaded of 229 |

All six hex tiles are from Dr. Jamgo's *Basic Hex Tile Set - 16x16*
(https://opengameart.org/content/basic-hex-tile-set-16x16), CC0, licence text
verified on 2026-09-01: "No Copyright Notice required. A note of tribute is
appreciated though." The tiles are cut from the pack's single sheet by
`/tmp/nc/tiles/`, and each subject directory records the cell it came from.

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
