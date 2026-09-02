# Handing autosprite on

Read this first. It is the state of the work, what is *measured* rather than
believed, the ordered backlog, and the dead ends that are not worth walking
again.

## Where it stands

**28 CC0 sprites** -- 16x16 to 190x134, humanoids, creatures, props, buildings,
plants, cloth and weather -- all build with all eight verification checks
passing. **700 tests**, no network and no model in any of them.

Quality, measured as **debris** -- the share of a frame's pixels not connected to
its main blob, against the source's own figure:

| worst shed across the corpus | |
|---|---|
| at the start | 89.4% |
| after the rig fixes, `_reconnect`, `plant` and automatic repair | 15.4% |
| **after parts stopped tiling and overlapped at their joints** | **4.32%** |

**Twenty-seven of the twenty-eight assets now shed exactly 0.00% on every clip**,
and the twenty-eighth is `grafxkid-oldhero` at 4.32%, under the 5% the build
warns at. Nothing in the corpus is reported as a problem any more. The section
below on what is broken has been emptied by that change and says what replaced
it.

The rest of this file is the record of how, including the parts that were wrong.

### The historical figures, kept because the reasoning is in them

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
chain following the link before it, and a canopy lagging its trunk. It may also
carry an `along`, which is the axis it travels on: `x`, `-x`, `y`, `-y`,
`radial` (out from the anchor) or `chain` (distance along the skeleton, for a
tail that curls back on itself and reads as doubling back in every spatial
axis). Without one, the order is the order the rig happens to LIST its parts
in, which makes the direction of a wind a property of how carefully somebody
typed out a rig file.

The placement is by position, not by rank, and that is the substantive half.
Three stalks bunched at the left of a field and one alone at the right are four
ranks and so play at four even intervals, which is four things taking turns
rather than a wave; by position they play when the crest reaches them. The two
agree exactly when the parts are evenly spaced AND listed in order, so this
generalises the old behaviour instead of replacing it -- every clip that leaves
`along` unset samples byte-for-byte what it did before, and the whole suite
passed unchanged when it landed. `taper` reads the same placement, because a
canopy tapering toward its tip and a wave travelling toward its tip have to
agree about which end is the tip.

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

## Parts tile the sprite, and that is why limbs come off

The whole corpus's worst failure mode -- a limb coming away -- was structural,
and the fix is three lines.

`ownership` is a **partition**: the smallest box containing a pixel wins, ties go
to the front, strays go to the root. Every pixel belongs to exactly one part, so
the parts TILE the drawing, and each part's array is cropped to its own box, so
a part physically cannot hold a pixel outside its rectangle. Rotate one and it
drags a slab away from a hard edge: a hole on one side, a floating piece on the
other.

Look at what that cuts a CC0 32x32 knight into:

| part | size | pixels | what it actually is |
|---|---|---|---|
| torso | 26x12 | 263 | the whole upper body, **both arms included** |
| head | 18x14 | 236 | the helmet |
| leg_left / leg_right | 8x6 / 6x6 | 43 / 32 | **just the boots** -- the thighs are in the torso |
| arm_left / arm_right | 5x4 / 6x4 | **16 / 18** | corner scraps of pauldron |

So `walk` swings a sixteen-pixel scrap while the real arms sit frozen inside the
torso slab, and rotating that scrap tears it out of the body.

Real cutout rigs overlap generously at the joints for exactly this reason: an
upper arm is drawn as a whole limb reaching into the shoulder, not as the slice
of the drawing nobody else claimed. **Overlap costs nothing here.** Compositing
at rest still reproduces the source exactly -- the front-most part wins every
shared pixel and the collar is a copy of what was already there -- so `REST` is
untouched, and a test asserts it at four collar widths.

`COLLAR = 1`, one pixel, intersected with a spinner's disc so the hub rule is not
undone.

| | before | after |
|---|---|---|
| the knight's front walk | 7.92% shed | **0.00%** |
| corpus assets with a problem | 2 of 28 | **0 of 28** |
| worst shed in the corpus | 15.38% | **4.32%** |

That last row is the headline of the whole project: **89.4% at the start, 15.4%
after a year of repair work, 4.32% once the parts stopped tiling.** Both assets
that still failed are fixed -- including `platformer-grass-prowne`, the 8x23
character with 2px limbs that `repair` had correctly declared unfixable, because
the problem was never the motion.

### What it did to the tests

Three repair fixtures stopped demonstrating what they were written to
demonstrate, because the collar fixed them. None was relaxed; each was made more
extreme until the phenomenon returned, and the numbers are now in their
docstrings because they measure what the collar is worth:

- a lever-armed swing came apart at 16 degrees and now holds to 40, tearing at
  55 -- **about three times the swing before a limb leaves the body**;
- two parts that only ABUT survived a 2px lift where any lift used to part them,
  and damping now rescues everything up to 10px where 6px used to be hopeless;
- an overlapping pair needs 3px rather than 2px to detach.

## The ingest was deleting art, and one asset had no art left

`flood_background` seeds from the border and floods inward. It marked **every
border pixel as background before looking at what colour it was**:

```python
for y, x in _border_seeds(height, width):
    background[y, x] = True      # regardless of its colour
```

A seed was background for WHERE it sat, not what it was -- and a sprite cropped
flush to its own art has art on the border. Three of the twenty-eight corpus
assets were losing pixels to this, and one of them was losing its subject:

| asset | kept before | kept after | what was being deleted |
|---|---|---|---|
| `topdown-eldiran-rpg` | 542 | **574** | the top of the helmet and the sole of each boot, on a 32x32 knight packed edge to edge |
| `grafxkid-oldhero` | 131 | **138** | the soles of his boots, on the bottom row |
| `subject-flag-sbs` | 8316 | **24669** | **the entire blue field of the flag** |

The flag is the one that matters. Its blue runs to the left and right edges, so
every blue border pixel was an unconditional seed and the flood ran through the
whole field. What the pipeline had been animating, and what every flag
measurement in this project was taken against, was **the white Antarctica shape
on nothing** -- 8316 pixels of a 26112-pixel image, with 17796 pixels of flag
deleted before anything else ran.

Nothing downstream could catch it. `REST` proves the parts reassemble into the
INGESTED source, and the ingested source no longer had them. `PALETTE` proves
every output colour came from the input, and the deleted colours were simply not
in the input any more. The flag sat in every sweep as a clean asset.

The fix is small: the background is the colour that **dominates the border**, and
a border pixel seeds only if it is within tolerance of that. A sprite sheet's
background is one flat colour behind everything; art that reaches the frame edge
is a short run of some other colour, and it is a run of ART.

### What it cost, and what it corrected

The corpus went from **1 asset with a problem to 2**. `grafxkid-oldhero` --
already the second-worst asset, the corpus's smallest character at 10x17 -- got
the soles of its boots back and its worst clip went 3.88% -> **10.10%**, because
there is now more boot to come away. That is the right trade: the pipeline was
hiding a rigging weakness by discarding the pixels that expose it, and the build
already reports this one by name, frame and part, and says the rig is likely
wrong for the character. `subject-flag-sbs` went the other way, 1.63% -> 0.24%.

Every flag figure in this file, the README, four docstrings, the PR description
and a published gallery was measured against a flag with no flag in it, and all
of them are now re-derived. The conclusions all survived and got stronger:

| driving a flag's cloth | before, on the mutilated flag | re-measured |
|---|---|---|
| the artist's own frames disturb | 4594 px | **6608 px** |
| **`wave`** | 21.4%, moving 3822 | **11.0%, moving 5977** |
| `shear` instead | 68.2% | **66.3%** |
| `wave` + a lean | 63.6% | **59.2%** |

`wave` now beats `shear` six-fold rather than three-fold, and covers 0.90 of what
the artist disturbs. One conclusion did have to change: the reason a bigger wave
is a dead end. See that section.

## The character clips had never been measured, and now they have

Sixteen of the thirty clips here are character clips, and until now not one had
been compared to a real animation. `quality.footprint` existed and worked -- it
caught the windmill -- but it needs the artist's own frames of the same motion,
and the corpus had those only for a torch and a flag, both subject clips.

Several corpus characters were cut from **animated** sheets, so the ground truth
was there the whole time. Two are now measured, at opposite ends of the size
range, by `scripts/ground_truth.py`:

Two readings, because the error rises monotonically with coverage on every clip
and every character measured -- `footprint` alone always favours doing less.
**Shipped** is what a user actually gets, with the coverage beside it so it
cannot be read alone; **matched** is how clips compare to each other.

Twelve clips across five characters, sorted by the comparable column. **These
are the numbers on the current head**; the table this replaces was measured
before the joint collar, skinning, the legibility guard, the face-on walk fix and
-- most importantly -- before `sumohulk` was found to be mis-faced, so every one
of its rows in it was on a mirrored rig:

| subject | clip | content height | shipped | coverage | matched |
|---|---|---|---|---|---|
| `platformer-forest-64` | run | 45 px | **4.6%** | 0.77 | **11.1%** |
| `platformer-mv-male` | crouch | 46 px | 18.4% | 1.08 | **15.0%** |
| `platformer-mv-male` | attack | 46 px | 30.7% | 1.38 | 19.9% |
| `platformer-sumohulk-16` | walk | 15 px | 9.1% | 0.25 | 25.8% |
| `topdown-eldiran-rpg` | walk | 32 px | 24.1% | 0.75 | 26.0% |
| `creature-horse-scratchio` | walk | 33 px | 25.4% | 0.80 | 27.1% |
| `platformer-mv-male` | walk | 46 px | 25.2% | 0.85 | 23.0% |
| `platformer-sumohulk-16` | jump | 15 px | 41.5% | 1.45 | 28.7% |
| `creature-horse-scratchio` | run | 33 px | 18.8% | 0.75 | 31.7% |
| `platformer-sumohulk-16` | attack | 15 px | 40.6% | 0.97 | 40.6% |
| `creature-horse-scratchio` | idle | 33 px | 44.0% | 0.72 | **46.1%** |
| `platformer-sumohulk-16` | idle | 15 px | 59.4% | 0.63 | **61.1%** |

An earlier revision of this file drew a conclusion from the two walks agreeing to
a tenth of a point across a 46px biped and a 33px quadruped. **That coincidence
is gone** -- 27.9% against 27.1% -- and the claim went with it. It was one
decimal place of agreement between two numbers that have both since moved twice,
which is not evidence of anything.

A warning that has now caught the same asset twice: `truth.json` and the corpus's
own `meta.json` each carry a `facing`, and until 2026-09-02 they DISAGREED about
`sumohulk` -- `front` in one and `right` in the other. A corpus shed sweep and a
ground-truth run were therefore rigging the same sprite two different ways, and
any figure combining the two sources is suspect. They agree now; if a third
source of facing ever appears, make them agree at the point of reading.

For scale: the flag's `ripple`, the best-measured subject clip in the plugin, is
11.0%. The forest run at 4.8% shipped beats it; the brawler's idle is five
times worse than it, and moves half as much as it should while being two-thirds
wrong.

### The idle: measured, fixed, and the fix argued down twice on the way

The clip was a one-pixel bob and nothing else -- no squash at all -- while the
brawler's own idle redraws 109 of his 156 pixels. Adding a **widen-and-settle**
to the root track took it from 66.0% at 0.49 coverage to **58.3% at 0.66** on
the brawler and from 47.1% at 0.47 to **44.5% at 0.70** on the horse: error down
and coverage up on both, corpus unchanged (1 of 28 at the time; see the ingest
bug below, which later moved it to 2), all tests green.

It goes in the ROOT track rather than a `torso` one, because a root track's
squash already composes onto whatever part is the root -- the torso of a
humanoid, the body of a creature -- so one entry covers both and `body` stays a
role that rides its parent rather than one clips address directly. A test
asserts exactly that list of undriven roles, and it caught the first attempt.

Two things nearly went in and were argued down by looking:

**A deeper, taller breath.** `sx 0.90 / sy 1.15` scored *better still* on the
brawler. The critic: *"the barrel visibly narrows and stretches tall between
frames, reading rubbery rather than like breathing."* It is also the shape that
the mirrored-rig measurement below preferred, and it loses to widening once the
rig is right.

**A stronger version of the shipped shape.** `sx 1.10 / sy 0.94` scored better
on the horse than what shipped. The critic returned `rig` on the brawler and
named the cause: *"this blob has no arms; arm_far and arm_near boxes contain
only body and face pixels, so driving their angles rotates chunks of the
head/torso -- visible as the raised right-side nub and shifted notch in the last
frame."* That is the known silhouette-rigger defect, surfaced by a bigger
motion. `shed` reported 0.00% on it, because the nub stays connected.

On the shipped version the critic returns `good` on the horse and, on the
brawler, `rig` with two complaints and **no motion complaint at all**.

### The attack was too big, and the critic said which part of it

Measured on two characters and, on one of them, two different rigs, the attack
disturbed **1.6 to 1.8 times** as many pixels as the artist's own strike does
from the same standing pose. A uniform damp would have fixed the number; asking
the critic instead -- on a vision rig, because on the silhouette rig it kept
returning `rig` about arm boxes that are 2-pixel horizontal slivers -- got a
diagnosis of WHICH part:

> *"Both legs swing wide through every frame, so the stance slides instead of
> staying planted through the strike."*
> *"The lunge spread peaks harder than the arm swing, pulling focus away from
> the attack itself."*
> *"The head tips more than the torso at the peak, which reads as a wobble
> rather than a committed strike."*

So: the near leg steps once and holds through the contact, the far leg becomes
the planted one and barely moves, and the lunge halves. The arm arc is
untouched, because the arm was never the problem.

| | shipped before | after |
|---|---|---|
| `mv-male`, vision rig | 46.6% at 1.82 coverage | **40.7% at 1.60** |
| `mv-male`, template rig | 44.6% at 1.76 | **36.4% at 1.50** |
| `sumohulk`, template rig | 48.5% at 1.57 | **46.5% at 1.32** |

**The head note is the transferable part.** A part's angle composes onto its
parent's, so a head authored at +6 on a torso turning 11 turns **17** in the
world -- more than the torso it sits on. Every angle authored on a child is a
departure *from* its parent, and this is the clip where that stopped being
invisible. The head now counter-rotates.

### The silhouette rigger's sliver arms: a second dead end, measured

The critic says the same thing about the silhouette rig of every real character
it is shown: *"arm_far and arm_near boxes are 1-2 pixel-tall horizontal slivers
that catch only the shoulder line, not the arms that hang down"*. Measured
across four corpus humanoids, the arm box is 10% and 17% of the torso's height
on `mv-male` and `fry-caped`, against 64% and 100% on the other two.

Replacing a sliver with the outer third of the torso is already recorded as a
dead end -- it tears two clean characters to buy one back. The obvious
refinement is narrower and looked much better: the parted rows really did
measure WHERE the arm is, so keep the x range and stretch only the HEIGHT to the
shoulder-to-hip band. With ground truth now available it could be judged on the
animation rather than only on debris:

| `mv-male` | walk, matched | attack, matched | shed |
|---|---|---|---|
| sliver arms, as shipped | 26.4% | 20.9% | **0.00%** |
| stretched to the band | **21.7%** | 31.0% | **11.6%** |
| a vision rig | **19.4%** | 25.5% | 0.00% |

So it does move the walk toward the artist -- and sheds 11.6% doing it, which is
four frames of a character coming apart, because the stretched column swallows
torso pixels at the shoulder and hip and rotating them tears the body. Better
animation of a torn character is not better.

The information simply is not in the silhouette. What the rigger does now --
leave the measured box, say in the rig notes that the arm swing will hardly read,
and point at a vision rig -- remains the right answer, and the vision rig gets
this character's walk to 19.4%, the best humanoid walk measured.

### The torso lead, recorded rather than fitted

The critic's remaining complaint is the torso: *"the torso tilt is large enough
that the figure reads as toppling sideways rather than driving a blow."* There
is a real principle behind that -- **in a side view an in-plane torso rotation
is a lean, not a coil.** A real strike's torso rotation is about the vertical
axis, which a 2D side view cannot show at all, so authoring a large in-plane one
models the wrong thing.

Scaling it down improves both `mv-male` rigs monotonically (vision 40.7 -> 35.1%,
template 36.4 -> 26.9% at 0.3, coverage falling toward 1.0 the whole way). It
makes the 15px brawler *worse* at 0.7 and 0.5 and much better at 0.3, which is
the ~100-pixel noise that character's numbers have shown throughout.

It is not applied, because the bar for changing a shipped clip here is that it
improve every ground-truth subject and this improves two of three. The principle
is worth more than the change: it needs a third character with an attack strip
to settle.

### `--facing` is the one default that is both catastrophic and silent

The horse bug is not a harness bug, it is a product bug that the harness
happened to hit first. A user whose sprite faces left and who does not pass
`--facing left` gets every part box mirrored onto the wrong end of it, and the
whole gate stays green: `REST` passes because the parts still reassemble,
`PALETTE` passes, and on the corpus horse the mirrored rig sheds **0.00%** --
it sits in the sweep as one of the clean assets. On the synthetic test hero it
sheds 2.3%, which is below the 5% the build warns at. A test now records that
the gate cannot catch this, so that nobody later assumes it can.

It is also **not inferable**. The obvious silhouette heuristic -- a side-on
animal's head end is the taller end -- was measured against the ten corpus
assets that carry a left/right label and gets two of three creatures and
neither left-facing subject. No threshold, no detector.

So the answer is to stop it being silent: `--facing` now defaults to nothing at
the CLI, the build warns when it had to assume rather than be told, the
assumption is printed on the rig line and written into the rig file, and the
help text says what getting it wrong does. That is the whole fix, and it is the
right size of fix for something no measurement can decide.

### The critic caught a bug in the MEASUREMENT, which no measurement could

Asked to judge an idle variant, it opened with something nobody had asked about:

> *"The horse is drawn facing LEFT, but the rig assumes it faces right, so every
> part box is mirrored onto the wrong end of the animal ... the head box sits
> over the rump and tail, so `head dy` bobs the hindquarters instead of the
> head; the tail box sits over the head/neck/ear, so `tail angle` swings the
> horse's head around like a tail."*

The corpus meta says `"facing": "left"` and the harness had defaulted to right.
Every horse number reported before that was measured on a mirrored rig.
Corrected, the horse's walk moves from 32.8% to 26.5% matched -- and lands within
a tenth of a point of the mv-male walk, which is what made the correction
obviously right rather than merely different.

**And the mirrored rig still scored 14.7% on the run.** That is the third and
sharpest demonstration of what `footprint` actually rewards: a horse rigged
back-to-front still moves legs and a body, so it still overlaps the artist's
footprint. The metric is a strong detector of moving pixels the artist never
moves -- it caught the windmill that way -- and a weak guide to whether the
right pixels moved for the right reason. Nothing in this plugin could have
caught a backwards horse. The critic did, unprompted.

### The leads this opens, recorded rather than acted on

Neither is a fix yet, because both rest on ONE character and this measurement
has already killed one conclusion drawn from one character.

- **On the 15px brawler the clips lose their relative scale.** `jump` and
  `attack` ship at 1.72 and 1.57 of the artist's coverage; `walk` and `idle`
  ship at 0.60 and 0.49. Some too big, some too small, on the same character.
  On the 46px `mv-male` both clips ship between 1.00 and 1.07. So this is not a
  size *law* applied to everything -- it is individual clips coming apart from
  each other once the sprite is small enough for a 1px floor and integer
  rounding to dominate.
- **The `idle` is the worst clip in the plugin**, now on two characters rather
  than one. The brawler's own idle redraws 109 of his 156 pixels; ours moves 53
  and puts two-thirds of them where he does not. See the section below: several
  fixes improve the number on both characters and none of them survived being
  looked at.

**Two patterns, and the second is sharper than the first.**

*Matched error tracks size* -- 45px and 46px at 11.9 to 26.4%, 33px at 29.5 to
32.8%, 15px at 34.2 to 48.4%. That is consistent with everything else the corpus
says: the two assets `shed` still fails on are 8x23 and 10x17, the smallest
characters in it.

*Except the idles, which break the pattern completely.* The idle is the worst
clip in the library at every size, on a biped and on a quadruped alike, and it
was the only clip failing in both directions at once -- both idles disturbed
about 0.45 of what their artist disturbs AND put more than half of that in the
wrong place. The table above is after the fix below; before it, the two read
66.0% at 0.49 and 47.1% at 0.47. That is consistent with everything else
the corpus says -- the two assets `shed` still fails on are 8x23 and 10x17, the
smallest characters in the set -- and it has a plain explanation. At 15px an
artist is not transforming parts, they are REDRAWING: the brawler's idle
redraws 109 of his 156 pixels, and there is no rotation of a four-pixel arm
that gets there. Cutout animation has a floor, and it is somewhere between
these two sizes.

### Three ways this measurement lied before it was trusted

Each was caught by checking rather than by the number looking wrong, and each
changed an answer.

**The alignment has to be proved.** The script renders the rest pose, places it
back into the artist's coordinate space, and requires it to be byte-identical to
the source before reporting anything. This is the third time alignment has
produced a plausible wrong number in this project.

**Both footprints have to be measured from the same rest.** Our clips all start
from the source image; an artist's strips usually do not. On the brawler, only
the *idle* strip opens on the standing pose -- the walk, jump and punch strips
open 41 to 78 silhouette pixels away from it, on a 156-pixel character.
Measuring their strip against its own frame 0 and ours against standing
reported `attack` at **78.9%** where the parallel figure is **48.4%**, and
`jump` at 71.1% where it is 34.2%.

**The comparison has to be at matched coverage.** `footprint` is one-sided on
purpose -- it punishes moving the wrong pixels and not moving too few -- so it
rewards doing less. Damping the brawler's walk took it to **0.0% error while
moving 22 pixels against the artist's 102**. `quality.coverage` now returns the
other half of the reading, and the script compares at the scale whose
disturbed-pixel count comes closest to the artist's.

That last one also killed a conclusion. On the brawler alone, damping the walk
looked like a clean 32.1% -> 10.8% and the obvious reading was "the clips are
over-scaled for small sprites". The second character refuted it: at full scale
`mv-male` disturbs 535 pixels against the artist's 536, so its motion is already
the right size, and the brawler at matched coverage wants **more** motion, not
less. One data point would have shipped a scaling law that was wrong.

## The hip was in the middle of the leg, and a hip is not the middle of a leg

Every limb pivot the template rigger emitted was the **centre of the part's own
box**, which is where a leg's mass is and not where it is attached. The joint is
where the leg meets the pelvis: the end of the leg's x range nearest the body's
centreline. Pivoting at the middle swings the outer half of the hip away from the
torso and drives the inner half across the crotch, and both halves of that are
wrong in the same frame -- at 5x, `mv-male`'s walk splits her pelvis open high
and her thighs come away from her body, where the fixed rig keeps the crotch
solid and the legs emerging below it.

It is the first change in a long while that improves the mean **with nothing
worse on any reading**:

| | shipped | matched | at coverage 1.00 |
|---|---|---|---|
| hip at the box centre | 28.65% | 30.22% | 30.68% |
| **hip at the inner edge** | **28.48%** | **29.67%** | **30.08%** |

Per clip: `mv-male` walk 27.6% -> **22.2%**, `forest` run 14.3% -> 12.7%,
`mv-male` crouch 15.4% -> 15.0%, nine clips byte for byte unchanged, none worse.

And it sheds LESS rather than more, which a rig change moving joints had no right
to do for free: swept over the whole corpus, the worst pre-repair shed goes
7.58% -> 6.57% (`platformer-grass-prowne`'s block), every one of that asset's
seven shedding clips falls, one clip stops shedding altogether, and no clip that
shed nothing starts. A leg rotating about its own middle was itself pulling the
hip apart.

**The third reading is new and is the honest one.** `matched` picks the nearest
row of a coarse scale grid, so two rigs get compared at whatever coverage each
happens to land on -- on `mv-male`'s walk the old rig's nearest row is at 1.11
and the new rig's at 1.02. Interpolating the error to coverage exactly 1.00
compares them at the same place, and it is the reading to trust when two rigs are
being compared rather than two clips.

### Two gates, each of which cost something before it existed

**Only where the leg actually TURNS about the joint.** `Animation.fronted`
rewrites a face-on clip's swings as translations -- a leg walking towards the
camera foreshortens, and what reads is the foot leaving the floor -- and a
translation does not care where its pivot is. Applying the fix to the two
face-on characters as well costs 1.2 and 0.6 points for nothing.

**And only on a leg longer than it is wide.** A limb extends away from its joint
and that direction is its length, which is the same thing `fit.split_part` has to
know to cut one. `grafxkid-oldhero` is 10x18 with 5x5 legs, so the box's inner
edge is two pixels from its middle on a character ten pixels across, and moving
the joint there throws 0.3% of the sprite loose on its run where the corpus is
otherwise at 0.00%. The same size floor this project keeps rediscovering.

A third detail is a one-character bug that would have been invisible: the pivot
clamps to `box[2] - 1` and not `box[2]`, because boxes are half-open and a pivot
is a PIXEL. Clamped to `box[2]` the joint sits one column outside the leg, and a
foot that does not hang under its own joint swings DOWN as well as up -- which
sinks every planted clip below the row the character was drawn standing on,
because `plant` floors a clip at its deepest pose.

### What does NOT pay, measured on the same twelve clips

* **The arms, either way.** Moving the arm pivot to the box's inner edge is
  +0.75 matched; moving it to the shoulder row is +1.29 matched and **0 of the 5
  clips it touches improve**. An arm box on these rigs is a chip of mitten that
  barely separates from the body, so it has no inner edge worth finding.
* **The root pivot**, lifted anywhere from 5% to 50% of the torso: the best
  setting is worth -0.24 matched and costs the forest run between +2.2 and +4.7
  at every value. No rule fits both.
* A per-part sensitivity sweep (every pivot moved +/-1, 2 and 3 in x and y on two
  characters) says why the arms cannot pay: head and arm joints move the mean by
  at most 0.20 and 0.35, while the hip and the root move it by 1.2 to 1.4.

### And `fit` cannot judge a pivot at all

Moving EVERY limb pivot five pixels on a 32px character changes the fitted IoU by
**+0.0002**, and turning the translation channels off does not make it
discriminating either (0.7600 against 0.7607). Two reasons, both arithmetic: a
pivot change is exactly a rotation plus a translation the solve already searches
for -- rotating about p' is rotating about p plus (I-R)(p'-p), which is 1.6px for
a 3px joint move at 30 degrees, inside the 3.5px the solver is allowed anyway --
and the torso plus head are 544 of the knight's 676 opaque pixels, so all four
limbs together have under 0.2 of IoU range to argue over.

So rig geometry is a `ground_truth.py` question, and `fit` has nothing to say
about it. That is the same conclusion the section above reaches from the other
direction.

## The idle weight shift: a twenty-point win that tears the character in half

The `idle` is the worst clip in the library and has been every time this file
has been asked. Reading the brawler's own idle frame by frame says why, and the
observation is right: **a standing biped shifts its weight**, and this clip has
no lateral motion in it at all. His body -- head, chest, belt -- travels one
pixel and then two sideways while his feet stay in their columns, and his mass
goes UP, 156 pixels to 163, where ours falls to 138. At 0.63 coverage the clip
is plainly under-moving.

Authored as `torso dx 3`, that reads as a thirteen-point win: **59.4% error at
0.63 coverage to 45.8% at 0.98**, the shape a real fix has, with the horse
untouched because she roots on a `body` and not a `torso`.

**It is wrong, and the way it is wrong is instructive.** The legs are CHILDREN
of the torso in every humanoid rig the template rigger builds, so a torso `dx`
carries them bodily. The whole character skates:

| foot columns, per frame | frame 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| the artist's own brawler | (2,11) | (2,12) | (2,11) | -- |
| `mv-male` as shipped | (7,20) | (7,20) | (7,20) | (7,20) |
| `mv-male` with `torso dx 3` | (7,20) | **(9,22)** | **(11,24)** | **(9,22)** |

The artist's left foot edge never moves at all; only his right edge grows by
one, which is a foot taking weight. Ours travels four pixels and comes back --
a camera pan, scored as a weight shift because `footprint` rewards overlap and
the artist does disturb those columns. It scores well on the 15px brawler and
only on him, because at 15px three authored pixels scale to 1.4 and round to
one; every character above about 20px gets the skate at full size.

### Countering on the legs plants the feet, and tears the waist instead

The construction that is actually right: shift the torso and counter on the
legs. Skinning damps a part's pose by distance from its pivot, so a leg `dx` of
-k moves the foot by -k and leaves the hip where the torso put it. Body
travels, feet stay. Expressing "the legs of something that HAS a torso" needed
one new thing, and it is worth recording as a mechanism even though nothing
ships using it: a `under:` selector term, ANDed with the others --
`"trait:support under:torso"`. A horse's hind legs and a person's legs are both
`leg_near` and both `support`; the only thing separating them is what they hang
off, so a selector that cannot say `under:` cannot address one anatomy without
addressing the other.

It works exactly as designed. Feet planted on all four bipeds, the horse byte
for byte identical at every amount, and the brawler:

| brawler `idle` | shipped | coverage | matched |
|---|---|---|---|
| as it ships | 59.4% | 0.63 | 61.1% |
| torso dx 2, legs counter | 48.3% | 0.82 | 51.2% |
| torso dx 3, legs counter | 45.3% | 0.87 | 41.4% |
| **torso dx 4, legs counter** | **41.1%** | **1.03** | **41.1%** |

Twenty points at matched coverage, on the worst clip in the library, with the
feet provably still. **Rendered at 14x it is unusable.** The torso translates
rigidly -- a `dx` has zero corner spread, so `_legible` hands it a whole-pixel
translation and skinning never runs on it -- so the torso's bottom edge slides
off the hips it sits on and its outline pixels cut a dark diagonal gash across
the character's waist. At `dx 3` `mv-male`'s near leg is a brown wedge floating
free of her body. At `dx 2`, where her feet do not move by even one column, the
gash is still there.

So it is refused at every amount tested, in both constructions, and the `under:`
selector is reverted with it -- shipping an unused mechanism is a mistake this
file has already recorded twice.

**What it costs to know this: the metric said +20 and the eye said torn in
half, and that is now seven times in this project that they disagreed and the
eye was right every time.** The lesson has stopped being about any one clip.
`footprint` cannot see connectivity, `shed` cannot see a gash that stays
8-connected, and neither can see that a silhouette is a person. A number is
only ever a reason to go and look.

What the idle actually wants is unchanged and still open: it under-moves at 0.63
coverage and a biped really does shift its weight. The next section is how far
that got.

### Why the shift is blocked, exactly, and what unblocks it

The guard was measuring the wrong quantity for a skinned part, and that is now
fixed: a skinned pixel takes its weight's share of its part's transform, so the
pixel at the joint takes the **parent's** transform and the one at the free end
takes all of the part's own. The spread a viewer reads is between those two.
Measured among four corners that all take the part's transform together, a pure
translation has spread **zero** by construction -- so no translation could ever
be legible, and skinning could never run on one. `_legible` now takes a `pinned`
matrix, passed only for a part that will actually be skinned.

It is a correct fix and it buys almost nothing today: `mv-male`'s crouch goes
18.8% -> 18.6% and its attack 30.7% -> 30.8%, every other clip is byte for byte
identical, and all 761 tests pass plus three new ones. That is because the part
this was supposed to unblock -- the torso -- is the **root**, and
`skin.bands` returns `None` for a part with no parent, so a root is never
skinned at all.

**That exclusion is the real blocker, and it is not arbitrary.** A child
composes onto its parent's UNDAMPED world transform. Skin the root and its hip
pixels stay where the pivot is while the legs hanging off that hip attach as
though it had moved the full `dx` -- a gap at the hip instead of a gash across
the waist. Trading one tear for another.

What the whole thing wants is one change, and it is a real generalisation rather
than a patch: **a child should attach at its parent's transform evaluated at the
child's own attachment weight.** A leg touches the torso at the torso's pivot,
where the weight is ~0, so a weight-shifted torso would carry its legs by
almost nothing and the feet would stay planted with no counter-track authored at
all. Every other clip keeps working because at rest, and for any part whose
attachment sits at weight 0 today, the composition is unchanged. It touches
`skeleton.world_transforms`, so it is a change to measure across the whole
corpus rather than to bolt on -- and it looked, at the moment it was written
down, like the single thing standing between the library's worst clip and twenty
points. It was then built and measured, which is the next section.

### The generalisation that was supposed to fix it, measured and refused

The previous section named one change as "the single named thing standing
between the library's worst clip and twenty points": **a child should attach at
its parent's transform evaluated at the child's own attachment weight.** It is
built -- `cutout.attachment_weights` reads the parent's own weight field at the
child's pivot, and `skeleton._anchors` composes each part onto that -- and the
weights it reads are exactly what the argument predicted:

| | head | arms | legs |
|---|---|---|---|
| `mv-male` | 1.00 | 0.84, 0.87 | 0.13, 0.32 |
| `eldiran` | 1.00 | 0.98, 1.00 | 0.26, 0.44 |
| `sumohulk` | 0.93 | 1.00 | 0.37, 0.73 |

A head sits at the torso's free end and rides all of it; legs meet the torso at
its own pivot and ride almost none. That is the anatomy the argument claimed,
read off the art rather than asserted.

**It measures worse, on eleven of twelve clips or unchanged, and the mean goes
30.22% -> 31.05% at matched coverage.**

| clip | as it ships | anchored |
|---|---|---|
| `mv-male` walk | 27.9% | **27.2%** |
| `horse` walk / run, `sumohulk` jump / attack | unchanged | unchanged |
| `horse` idle | 46.1% | 46.4% |
| `forest` run | 12.4% | 12.7% |
| `sumohulk` walk | 25.8% | 26.5% |
| `eldiran` walk | 26.0% | 26.9% |
| `mv-male` crouch | 15.3% | 17.0% |
| `mv-male` attack | 19.9% | 22.2% |
| `sumohulk` idle | 61.1% | **65.6%** |

One clip better by 0.7 and the worst clip in the library worse by 4.5.

**Why the argument is wrong, and it is a distinction worth writing down.**
Skinning weight answers "how much of its OWN transform does this pixel take",
and it was used here to answer "how much of its PARENT does this child ride".
Those are different questions. A leg attached at the hip does travel with the
hips when a character walks -- rigidly, fully, all of it -- and damping that
removes motion the artist genuinely draws, which is why every locomotion clip
got worse. The case the damping is right for is narrow: a body leaning over feet
that stay planted, which is one clip, and `plant` already exists to handle it
from the other end.

Kept behind `render.ANCHORED = False`, with `world_transforms` and
`world_and_local` now sharing one implementation rather than two copies of the
same descend loop, and tested to render byte for byte what it always did when
off. **So the idle's weight shift has no route left that this branch has found.**
Both constructions of the clip are refused, the guard bug behind one of them is
fixed and bought nothing, and the generalisation that was supposed to unlock it
is refuted with numbers. The clip stays the worst in the library at 59.4% and
0.63 coverage, and the next person to look at it should start somewhere else.

## The attack's torso lean, halved, with the third reading it was waiting for

Damping this was written up and left unapplied once because it improved two
readings of three and made the 15px brawler worse. Re-measured independently on
the current pipeline it improves **both characters that have an artist's strike,
on both readings**:

| `attack` | brawler | coverage | brawler matched | `mv-male` | coverage | `mv-male` matched |
|---|---|---|---|---|---|---|
| lean -8 / +10 / +11 | 42.0% | 1.03 | 42.0% | 36.7% | 1.51 | 21.4% |
| **halved, -4 / +5 / +5.5** | **40.6%** | **0.97** | **40.6%** | **30.7%** | **1.38** | **19.9%** |

Half is the brawler's matched-coverage point. Going on to zero buys `mv-male`
another nine points and drops the brawler to 0.83 coverage, which is
`footprint`'s one-sidedness paying itself rather than a better animation.

The principle is what justifies the direction and it did not come from the
number: **in a side view an in-plane torso rotation is a lean, not a coil.** A
real strike turns the torso about the vertical axis, which a 2D side view cannot
show at all, so a large in-plane rotation models the wrong thing -- and the
critic, shown the frames and told nothing, called it "the figure topples
sideways rather than driving a blow".

Cost, swept over the whole corpus on the only clip that changed:
`platformer-grass-prowne` goes from 5.00% to 5.23% pre-repair shed and
`grafxkid-oldhero` picks up 0.13% where it had none. The build takes **both to
0.00%** -- the first by the repair loop, which was already firing on it before
this change and damps the arm swing to 40%, and the second without needing a
repair at all.

This is the one change of the two that ships. Applied, the other ten
ground-truth clips are byte for byte unchanged and all 761 tests pass.

## Weather, and a class of motion that is passage rather than movement

Nothing in the plugin could animate rain. The user named "houses and weather"
and the vocabulary had no way to say what weather does: a sheet of rain does not
move, and it does not ripple either -- something travels THROUGH it while it
stays exactly where it is. `dx` moves the part, and a part that leaves its own
box comes away from whatever it hangs on.

Two channels, `scroll_x` and `scroll_y`, slide a part's pixels within its own
box and wrap what falls off the far side back to the near one. Rain, snow, a
waterfall, a river, a conveyor, a treadmill of ground under a runner, smoke
leaving a chimney. Two clips drive them, `fall` and `current`, addressed at a
new trait `flow`, which the vision prompt now offers with the distinction that
matters: a pond's surface RIPPLES and a river's surface FLOWS.

Three properties, and the first is the reason to prefer this to everything else
that was considered:

- **A wrap is a bijection.** Stronger than `wave`, which is a permutation that
  lets pixels slide off the end: here every output pixel is an input pixel AND
  every input pixel is an output pixel, so every colour keeps exactly the count
  it started with. It is the only motion in the plugin that structurally cannot
  detach anything from anything.
- **The unit is a fraction of the part's own box**, not a count of pixels, which
  is what lets one clip close its loop on a subject it has never met: "one whole
  box per cycle" is exact whether the box is 8px or 800. A test asserts the
  frame after the last IS the first, byte for byte, at three sizes.
- **It closes for free.** Scroll by a whole box and you are where you started,
  so there is nothing to stitch and nothing to drift.

Verified end to end: a rain sheet built from one image, `fall` and `current`
both drawn, all eight checks green, pixel count identical in every frame.

### A sheet of rain broke a measurement, which was the more useful half

`shed` asks how much of the subject came AWAY from it, and that presumes there
is an "it" -- one connected thing a limb can detach from. Rain is fifty separate
marks. Moving them changes which ones happen to touch, so `shed` reported
**10.71%** on frames whose pixel count was **exactly** the source's, 112 for
112, with zero invented colours. Nothing had gone wrong; the question could not
be asked.

Every one of the twenty-eight corpus sprites has a largest connected blob of
**96.2% to 100%** of its pixels, so art that is genuinely in pieces is easy to
recognise with an enormous margin. Such a subject is now measured for
CONSERVATION instead -- `quality.conserved`, the largest share of pixels any
frame gained or lost -- which is a far stricter question, because any drift at
all is a bug rather than a matter of degree. A test asserts a rotation fails it,
so the check is not vacuous.

`repair` is skipped for the same reason and stated: it damps whatever `shed`
blames, so on scattered art it chases a number that cannot mean anything, and it
had been explaining a sheet of rain in the language of limbs coming off a body
("a squash is pulling it apart, which damping cannot fix") -- a sentence the
user then has to disbelieve.

## Outfitting: "one item fits every character" was aspirational

The module's own docstring said an item ends up "in the right hand of a
character it has never met, at the right size". Both halves were false, and the
picture showed it before any number did -- a CC0 sword pasted on four corpus
characters floated beside each of them, at four wildly different sizes.

### It was pasted at whatever size it was drawn

The CC0 sword is 30px long. Across seventeen corpus characters the arm it hangs
on runs from 1px to 21px, so at its drawn size it landed anywhere from **1.4x to
30x** the length of that arm. On a 15px character it was a sword twice as tall
as the character.

An item is now scaled to the part it meets: a hand prop is about twice the long
axis of the arm holding it, a hat about the width of the head. Those are the
animator's rules of thumb and they are what makes one sword fit everything --
`PROPORTIONS` in `outfit.py`, overridable per item.

| | worst miss from the 2.0x target |
|---|---|
| pasted at its drawn size | **28.0x** |
| scaled to the arm | **3.0x** |

Every real character lands between 1.9x and 2.2x. The one outlier is
`props-potion-funnydude`, whose "arm" the template rigger invented as 1px wide,
and 1/6 is the smallest ratio on offer -- that is the known "the silhouette
rigger splits a single mass and calls the halves a pair" defect showing through,
not a scaling failure.

The scale is **snapped to a simple ratio** (1/6 up to 4, in log space so halving
and doubling are equally near). Pixel art does not scale by 0.37: a blade
reduced by an arbitrary fraction comes out two pixels wide in one place and one
in another. Nearest-neighbour in both directions, so no colour is invented and
`PALETTE` goes on meaning exactly what it meant.

### It was hung on the corner of a bounding box

A part's box is a rectangle around a limb, and a limb is not a rectangle. Two
separate errors compounded:

- **An off-by-one.** A box's right and bottom are exclusive, so the last pixel
  of a part is one before them. `_free_end` returned `y1`, which is one pixel
  *past* the limb -- and since an item's grip sits at its own content edge,
  that is a visible gap between a hand and what it is holding. A test asserted
  the wrong value, so it had encoded the bug.
- **The box instead of the pixels.** Even corrected, the box rule puts a hand
  at the middle of the box's far edge, which for a bent or tapering arm is
  empty space.

`sockets(rig, pixels)` now measures the point on what is actually drawn inside
the part's box -- the free end being the drawn pixel furthest from the part's
own hinge, which is what a hand *is*. `pixels` is optional, so a caller holding
only a rig still gets the box rule.

| socket points landing on a solid pixel of the character | |
|---|---|
| before | 41 of 80 (51%) |
| off-by-one fixed | 53 of 80 (66%) |
| measured on the pixels | **79 of 80 (99%)** |

Verified end to end on the corpus's smallest character: a 15px sprite with the
30px sword scaled to 0.25x, all eight checks green, and the build says
*"scaled 0.25x: 30 px drawn against a 4 px arm_near"* rather than resizing
silently.

## Three hypotheses tested and refuted, in one sitting

Each was cheap, and each would have been a plausible thing to build.

**A longer or shorter cloth wave.** The flag disturbs 5977 pixels against the
artist's 6608 -- 0.90 coverage -- and the misses are 83% concentrated in the top
and bottom fifths of the cloth. So: more amplitude, or a different wavelength?

A **different wavelength does nothing at all**. One, one and a half, two and
three periods across the part give 11.0%, 11.0%, 11.0% and 11.0%, moving 5977,
5972, 5982 and 5960 pixels. A `wave_length` channel would have been a dial that
provably does not move.

**More amplitude does reach those pixels**, and costs more than it buys:

| amplitude | error | pixels moved | of the artist's, missed |
|---|---|---|---|
| 2 | 4.7% | 3779 | 3005 |
| **4, what ships** | **11.0%** | **5977** | **1288** |
| 8 | 30.6% | 9335 | 125 |
| 12 | 44.7% | 11887 | 38 |
| 18 | 56.2% | 15043 | 25 |

At 8 the crest reaches almost everything the artist touches -- 125 pixels missed
of 6608 -- and is wrong about three times as often, disturbing 1.41 of what the
artist disturbs. Amplitude 4 is the matched-coverage point and the best error
there, so it stays. (An earlier telling of this said the missed count "barely
moves"; that was measured on a flag whose blue field the ingest was deleting,
and it is not true of the real one.)

**A stillness check, to catch a windmill without ground truth.** The windmill's
rotating roof was caught only by `footprint` and by the critic. The hypothesis:
a part the clip does not drive should not move, and checking that needs no
artist frames. It cannot work, and the reason is worth keeping: the roof moved
because *ownership gave it to the sails*, and once given, the roof IS a sail. A
check over owned pixels is vacuously true, because the renderer transforms each
part's own sprite by that part's own pose. Only something that knows what the
picture is OF -- artist frames, or the critic -- can tell that the roof was the
tower's.

**Limb width as a signal for "this rigger is out of its depth".** The one corpus
asset still failing is an 8x23 character with 2px limbs, whose vision rig
measures 0.00%. If narrow limbs predicted failure, the silhouette rigger could
refuse instead of shipping debris. Measured across the whole corpus: the
narrowest limb is 1px in the worst asset -- and also in three assets at exactly
0.00%, while the second-worst has 3px limbs. No separation, no threshold.

## A spread of a whole frame is a copy, and three shipped clips were one

The two-banner test that found it is four lines: put a CC0 flag on the canvas
twice, tag both `surface`, run `ripple`, and ask whether the right banner's
frames are the left banner's frames rolled by *k*. They were, at *k* = 1 --
byte-identical, compared as bytes.

The cause is arithmetic. `ripple` spread by 0.125 on an eight-frame clip, and
0.125 of a cycle IS one frame. Every part it drove was therefore the same
picture as its neighbour, later. Auditing every spread in both libraries against
its own frame period found three of six:

| clip | frames | spread | in frames |
|---|---|---|---|
| `sway` | 8 | 0.09 | 0.72 |
| `gust` | 10 | 0.06 | 0.60 |
| `creak` | 6 | 0.15 | 0.90 |
| **`ripple`** | 8 | **0.125** | **1.00** |
| **`flicker`** | 6 | **0.1667** | **1.00** |
| **`shimmer`** | 8 | **0.25** | **2.00** |

`ripple` was fixed by moving it to 0.15, and the two banners stopped being
copies. **The other two were not, and the reason is the more useful half.**

### A spread cannot vary a stepped channel at all

`flicker` and `shimmer` drive `cycle`, and the renderer rounds `cycle` to whole
shades, because a third of a shade is the same shade. So:

- Moving `shimmer` off a whole frame -- 0.25 to 0.30 -- produced **byte-identical
  frames**. The rounding absorbed the entire change.
- Moving `flicker` off a whole frame made it **worse**: the offset torch fell
  from three distinct pictures to two, and gained two consecutive frames on the
  same shade, which is the one guarantee that clip is built around.

A spread on a rounded channel does not decorrelate anything. It hands the next
part the same table read from a different place, and every whole-table offset
is the same set of pictures in a different order. There is no value that helps,
which is why both spreads were left exactly as they were.

What does work is a per-part wander. `turbulence` at 0.6 of a shade:

| | pictures, part A | pictures, part B | consecutive repeats | is B a copy of A |
|---|---|---|---|---|
| two torches, `flicker` as written | 3 of 6 | 3 of 6 | 0 | **yes, by 1 frame** |
| + turbulence 0.6 | 3 of 6 | 3 of 6 | 0 | no |
| two gem faces, `shimmer` as written | 5 of 8 | 5 of 8 | 0 | **yes, by 2 frames** |
| + turbulence 0.6 | 5 of 8 | **4 of 8** | 0 | no |

Free on the torch; on the gem it costs the second face one picture out of eight,
and that was taken deliberately -- two faces showing the same five pictures two
frames apart is the exact failure `shimmer` exists to avoid. Shed stayed 0.00%
throughout.

Below 0.6 nothing happens **at all** (0.3, 0.4 and 0.5 give byte-identical
frames) and at 0.6 exactly one step flips. On a rounded channel there is no
gentle version: a wander smaller than half a step is invisible and one large
enough to see costs a whole step.

Both rules are now `motion.cautions`, which is advisory and separate from
`validate_animation` on purpose -- a problem means the clip cannot be built and
stops the run, and every one of these builds perfectly and is still not what
anyone meant. The build reports them; a test asserts both shipped libraries
raise none.

## `turbulence`: wind is not a sine wave

Every wind clip in the library is one curve played by every part, so a field
reads as machinery. `turbulence` gives each part its own small wander on top of
whatever it was already doing. Three properties, each load-bearing:

- **It closes.** The signal is a sum of sines at whole-numbered frequencies in
  the cycle, so its period is the cycle exactly. Sampled noise would need its
  ends stitched and would still drift; this cannot, because nothing in it fails
  to repeat. A test asserts frame 0 and *t* = 1 agree exactly.
- **It does not depend on the rig's typing.** Each part's phase is hashed from
  its NAME, with FNV-1a written out here rather than Python's `hash()`, whose
  salt changes per process and would make a build irreproducible. A test pins
  the exact hash, which is the only way to catch a switch back.
- **It composes rather than replaces.** The wander is emitted as `name:` tracks
  holding nothing but the departure, and `name:` outranks the trait selector the
  parts were addressed by, so the authored swing composes on top and the
  rotations add. `spread` still spreads, `taper` still finds its own track, and
  the two work in either order.

`amount` is a true ceiling rather than an average: the signal is scaled so the
largest departure at any frame of any part is exactly `amount`.

### Measured against the artist, and it did NOT pay there

On the CC0 flag, against the artist's own sixteen frames:

| | footprint error | pixels moved |
|---|---|---|
| `ripple` as written | 11.0% | 5977 |
| + turbulence 1.0 on `wave` | 10.9% | 5930 |
| + turbulence 2.0 on `wave` | 12.4% | 6100 |
| + turbulence 1.0 on `wave_phase` | **10.4%** | **5029** |
| + turbulence 1.0 on `angle` | 18.2% | 6905 |

The artist's own frames disturb **6608** pixels. The best-looking row is a trap:
`wave_phase` scores lowest by moving 16% less than `ripple` already does, and
`footprint` is one-sided by design -- it punishes moving the wrong pixels and
not moving too few. Same-coverage against same-coverage, turbulence is worth a
tenth of a point on 5977 pixels, which is six pixels and inside the noise.

So it is **not** applied to `ripple`, `sway` or `gust`. It ships applied only to
the two clips where a measurement supports it, both for the discrete-channel
reason above. The `angle` row is a third independent confirmation that cloth is
not a thing that leans.

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

Honest and short. The easy things are gone, and 2026-09-02 closed several of
them by refutation rather than by shipping -- read the sections named below
before re-attempting any of these, because each is a measured NO and not an
unexplored idea.

0. ~~**Measure the VISION backend.**~~ **DONE, and the answer is NO.**
0. ~~**A second segment per limb (knee, elbow).**~~ **Measured, and it makes
   the ground truth worse.** See "the knee is a motion requirement".
0. ~~**A wider `fit` search (scale, shear, more passes).**~~ **Refuted: every
   point of IoU it buys is bought by deforming the character.**
0. ~~**Better generated motion, or a different model.**~~ **Refuted: the fit
   score is very nearly a restatement of how far the target moved.**
0. ~~**The idle's lateral weight shift.**~~ **Refused in both constructions,
   and the generalisation meant to unlock it measures worse.**

1. **WIDEN THE GROUND TRUTH. This is now the highest-value item and it is not
   blocked.** Every conclusion in this file rests on **twelve clips across five
   characters**, and on 2026-09-02 alone that thinness nearly shipped three
   wrong answers: a lateral idle sway measured on the ONE 15px character where
   its three authored pixels round to one; a scaling law drawn from a single
   brawler and refuted by the second character; and a knee that improves the fit
   and costs the ground truth. Two of the five characters have no artist `idle`
   at all, so the worst clip in the library is tuned against a single subject.

   What is needed is CC0 sprites cut from ANIMATED sheets, which is what makes a
   character usable here -- the corpus already had them and nobody noticed for
   weeks. Priority order by what the current set cannot answer: a second
   quadruped, any character with an artist's `idle` above 20px, and a robed or
   blob-shaped figure (which also unblocks item 3). Verify each licence on its
   own licence page; commit no art.

2. **`motion.select` addresses parts by ROLE, so a split limb's two segments are
   indistinguishable.** Both halves of a split `leg_far` receive the same track,
   and because the shin is a child of the thigh their world rotations compound
   -- so every hand-authored clip in the library silently means something
   different on a split rig. This is the actual blocker under the knee, and it
   is a design question rather than a bug: either the splitter names segments
   distinctly and clips address them, or `select` learns depth. The `under:`
   selector built and reverted on 2026-09-02 (see "the idle weight shift") is
   one shape this could take.

3. **The rigger splits one mass and calls the halves a pair.** The silhouette
   backend's remaining defect, said by the critic of five corpus characters: a
   floor-length robe hem, a slime, a squat blob, a tunic, a cape. It cuts the
   mass down the middle, calls the halves `leg_far` and `leg_near`, and swings
   them apart.

   **The intervention is validated and the detector is not.** Rigging the
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

   **The unsolved part is telling which characters want it**, and it is blocked
   on item 1. Every corpus silhouette parts somewhere, so "never parts" does not
   discriminate. `find_split` returning None catches the necromancer correctly
   and `fry-caped` incorrectly -- the caped hero has real legs whose gap is
   closed near the floor by his cape, which is a false negative in `find_split`
   rather than a legless character. The only separator found is "the deepest
   parting is within 20% of the floor" (fry-caped 11%, necromancer 39%), and
   that is a threshold fitted to two points, which this file already records
   going wrong twice.

4. **A wider motion library still.** Fifteen character clips against
   autosprite.io's ~100. Roll, slide, swim, fly, shoot, push, pull, wave, sit,
   kneel, taunt, revive. Each is a readable keyframe table; each must be checked
   against the distinct-picture warning, because a symmetric swing draws half as
   many pictures as it claims.

5. **`topdown-dcss` is a cloaked humanoid the silhouette reads as a prop.** Its
   outline is a smooth bell: no parting, no neck. The critic can see a head and
   two arms because it can see COLOUR. Whether the classifier should ever look
   at colour is an open question and a fragile one; the vision backend already
   gets this right.

6. **The critic proposes limb angles and nothing else.** Tallied over 40 calls
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

## What was broken, and what a joint collar did to it

Both of these were the same shape of problem -- a character too small for a
rigid-limb rig at the amplitudes the library uses -- and **both are now at
0.00%**. Kept here because the diagnosis was right and the conclusion drawn from
it was wrong, which is worth remembering.

- **`platformer-grass-prowne`'s jump, 15.4% -> 0.00%.** An 8-pixel-wide
  character whose limbs are 2 pixels across, and for most of this project's life
  the corpus's worst asset. `repair` reported, correctly, that damping could not
  fix it and that *the rig is likely wrong for this character*. It was right
  that the motion was innocent and wrong about the remedy: the parts were
  TILING, so a two-pixel limb rotating away from a hard edge had nothing either
  side of the seam. One pixel of overlap fixed it outright. Everything measured
  about it below still holds -- the pieces really did separate by 2.0 to 3.6
  pixels -- it just stopped happening.
- **`grafxkid-oldhero`, now 4.32% and the only asset above zero.** The corpus's
  smallest character at 10x17, and what comes away is a boot, next to the baked
  shadow. It went 3.88% -> 10.10% when the ingest stopped deleting the soles of
  its boots, then to 4.32% with the collar: more boot to hold on, and something
  to hold it with.
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

| driving a flag's cloth | worst-frame shed | pixels moved | of what we disturb, the artist never touches |
|---|---|---|---|
| the artist's own sixteen frames | -- | 6608 | -- |
| `shear`, leaning it rigidly | 0.00% | 11188 | 66.3% |
| **`wave`, amplitude 4** | **0.00%** | **5977** | **11.0%** |
| `wave` + a lean on top | 0.00% | 13714 | 59.2% |

So cloth is not a thing that leans: adding a shear to the wave moves more than
twice as many pixels for a worse score. `ripple` and `sway`'s surface half now
drive `wave`.

Every row is rendered at `render.suggest_margin` and measured at that same
offset, and the answer is margin-independent -- 2, 8, 16, 32 and 114 all give
11.0% for `wave` (a zero margin gives 12.0%, because a limb swung past the edge
is clipped rather than misaligned), which is the check that the alignment is
right rather than lucky.

### A measurement error worth more than the measurement

`render_pose` draws into a canvas with a MARGIN and the art it is judged
against is trimmed flush, so `quality.footprint` was comparing a picture with a
*shifted copy* of another one. On this flag that turns a real 11.0% into 79.5%,
and nothing about 79.5% looks wrong -- it agrees with the story I already
believed, which is why the first round of flag numbers, reported at 70-79% in a
commit message and in this file, all survived.

**And the fix did not end it.** The numbers that replaced them -- 16% for `wave`
and 36% for `shear` -- were also wrong, were published in the README, in two
docstrings, in the PR description and in a gallery, and stood for hours. They
cannot be reproduced by ANY offset of the render they claim to describe: 113
gives 16.6%, 114 gives 11.0%, 115 gives 15.7%. The correct pair is **11.0% and
66.3%**, which makes the conclusion stronger than the wrong numbers did, and the
lesson sharper than the first telling of it: a measurement this sensitive is not
finished when it stops looking wrong. It is finished when it is reproduced from
scratch by a script that takes the render margin from the renderer, and when
varying that margin does not move the answer.

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
| assets with a problem | 3 of 28 | **2 of 28** (1 until the ingest fix below restored art that was being deleted) |

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
subject should be one part with a surface trait. Rigged its way: 0.00% shed
both, footprint error 11.2% against 11.0%, 5840 against 5977 pixels disturbed.
**No measurement here can tell those two rigs apart.** The critic could.

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

## Open: characters are drawn in a STANCE, and the library assumes neutral

Found by following one of the critic's motion complaints to its cause, and
measured — but not acted on, because the threshold cannot be justified from
eleven samples.

The critic said of `platformer-mv-male`'s walk: *"the legs split hard only once
in the cycle; the opposite contact never opens, so it reads as a single lunge
rather than an alternating walk."* The numbers agree: its silhouette widths per
frame are **[15, 15, 16, 20, 27, 21, 16, 14]** — one half of the cycle splays to
27 and the other stays at 15. Every other corpus character's half-cycle width gap
is 0–5; this one is 12.

**It is not the hips.** They sit within 1.5px of symmetric about the torso.
**It is not erosion.** The leg keeps 74 opaque pixels at both ±26°.
**It is the ART.** That leg is drawn as a diagonal band -- columns 3-7 at the
top, 0-4 at the bottom, a 9° lean. Rotating it +26° adds to the lean and the
horizontal extent doubles (x 21..34); rotating it −26° cancels the lean and it
stays narrow (x 31..39). The library's swings are symmetric and the rest pose
they are added to is not.

The right measurement is a limb's own AXIS -- the centre of its top third to the
centre of its bottom third -- not pivot-to-centroid, which is nearly blind to a
uniform lean (it reports 4° where the axis reports 9°).

| asset | far leg axis | near leg axis | difference |
|---|---|---|---|
| `awkward-musket-officer` | −6.3° | −5.9° | 0.4° |
| `topdown-eldiran-rpg` | 0.0° | −4.8° | 4.8° |
| `fry-caped` | −10.7° | −3.8° | 6.9° |
| `awkward-necromancer-robe` | −4.1° | +4.1° | 8.2° |
| `awkward-shieldmaiden` | 0.0° | −9.0° | 9.0° |
| **`platformer-mv-male`** | **−9.2°** | **+0.8°** | **10.0°** |
| `platformer-sumohulk-16` | +5.7° | +16.7° | 11.0° |
| `platformer-forest-64` | −10.6° | +2.9° | 13.4° |
| `topdown-kenney-roguelike` | −7.8° | +7.8° | 15.5° |
| **`platformer-grass-prowne`** | **−14.0°** | **−33.0°** | **19.0°** |
| `creature-slime-andhegames` | 0.0° | −49.4° | 49.4° |

`platformer-grass-prowne` -- the corpus's worst asset -- has a leg drawn at 33°.

**Why nothing was shipped.** A threshold at 8° fires on eight of eleven, which
is noise; at 15° it fires on four and misses the case that started this. Most
pixel art *is* drawn in a slight stance, and there is no sample here big enough
to say where "slight" ends. Two options when it is picked up, and the second is
probably wrong:

1. **Warn**, naming both axes, and let the user supply a neutral frame or edit
   the rig. Honest, cheap, and the only one consistent with never redrawing.
2. **Neutralise** -- subtract each limb's drawn lean from its animation angles.
   `REST` survives (it is about the cut) but frame 0 of every clip stops looking
   like the source art: the character visibly straightens before it walks.

## Generated motion, fitted to the rig: what it fixed and what it did not

**The idea is Mixamo's and it is structurally right.** Mixamo never ships the
motion-capture actor's body; it ships YOUR character moved by a skeleton fitted
to the capture. Applied here: generate an animation, SOLVE for the rig pose that
explains each frame, discard the generated pixels. Identity stops being something
measured and becomes something untouched -- byte-exact REST and palette-subset
hold exactly as they always did, because no generated pixel is ever composited.
`fit.py`, and it works: solved against a generated walk, per-frame silhouette
agreement 0.88-1.00 -- read that as a diagnostic and not as a score, for the
reason two sections below.

It also makes a solved clip REUSABLE. Keyed by role, a walk solved once drives
every other character in the corpus. That is a motion library built by
generation rather than a generation step in every user's build, and most of the
per-user cost gone.

### Four bugs the fit found, three of them in the fit itself

* **A neck does not turn forty degrees.** Given an exaggerated target the solve
  rotated the HEAD forty degrees and smeared it across the chest, because a head
  is a large blob and moving a large blob covers more target than moving a leg.
  That pose scores 0.78 and is not a walk. `LIMITS` per role, and a `TIDINESS`
  charge so that among poses which explain the target equally well the tidiest
  wins. Cost: nothing. Worst-frame IoU 0.70 against 0.69, and a completely
  different animation.
* **A head does not slide either.** Unconstrained, the solve lifted the ROOT
  seven pixels -- a quarter of the character -- while sliding the head five
  pixels DOWN to cancel it: two channels fighting to explain the video's own
  camera drift. `SHIFTS` per role, scaled by character height.
* **A raised sword was shrinking the body raising it.** `to_sprite` normalised
  every video frame against ITS OWN content height, so a taller silhouette meant
  a smaller body, and the fitted attack came back squashed with the rig
  contorting to explain a shortening nobody drew. `calibrate` reads scale and
  floor once off frame 0 -- the one frame whose scale is known right, because
  drift measures 0 there. Attack fit 0.57-0.61 -> 0.69-0.77.
* **`split_part` cut limbs the wrong way.** It chose its axis by the box's
  aspect, and the corpus knight's left leg is eight wide by six tall with the hip
  on the top edge -- so it split SIDE BY SIDE into two half-legs standing next to
  each other. Its right leg, six by six, split correctly, which is how the bug
  survived a glance. The axis is now chosen by where the PIVOT sits: a limb
  extends away from its joint, and that direction is its length.

### A head is a face

At 32px a helmet is a dozen pixels of visor slit and ANY rotation
nearest-neighbour can draw smears them: three and a half degrees turned "|||"
into "\\\". Swept against an exaggerated walk, dropping the head from 14
degrees to 4 costs **0.01** of agreement. The same sweep found 14 and 8 degrees
produce byte-identical output, which is what pointed at the root -- the head was
not using its rotation at all, it was being carried.

### The measurement disagreed with the eye three times, and lost every time

Every constraint above COSTS silhouette agreement. Worst-frame IoU on the
exaggerated walk went 0.66 to 0.62 across them, and every one improved the
frames. Agreement rewards covering the target, and a contorted smeared knight
covers it perfectly well. **A fit score cannot tell a pose from a contortion.**

### The attack targets were not the character, and the fit score is mostly a
### restatement of how far the target moved

Two corrections to everything above, both found by looking at the targets rather
than at the scores.

**Rendered as masks, the `attack` targets are not a knight.** Frame 0 is the
source silhouette, because that is what frame 0 IS. Frames 1 to 7 are a solid
diagonal **wedge** with a blob on top -- no arms, no gap between the legs, no
figure. The generated video had abandoned the sprite and drawn something else,
`conform` faithfully reduced that something else onto the knight's grid, and the
solver then contorted the rig to cover a wedge. Every `attack` fit number in
this file was measured against it.

That also puts a **ceiling** on the score that has nothing to do with the rig.
Where a target's area differs from the source's, the best possible IoU is the
ratio of the two, because the rig can only rearrange the pixels it has. On the
knight, source area 574:

| clip | target areas | best IoU any rig could reach |
|---|---|---|
| `clip-walk` | 574..534 | mean 0.957 |
| `rich-bigattack` | 574..543 | mean 0.967 |
| `clip-attack` | 574, 382, 337, 299, ... | **mean 0.622** |

The 6-part rig scores .54 .53 .51 .50 .53 .52 .52 on `clip-attack` against a
ceiling of .67 .59 .52 .54 .57 .58 .52 -- **85 to 100% of what any rig could
score**. Read as "the rig cannot express a strike", that number was reading the
target.

**And agreement is one-sided in exactly the way `footprint` is.** Pooled over 40
frames, `IoU = 0.990 - 0.603 x motion` at **R^2 = 0.93**: the score is very
nearly a restatement of how far the target moved from the source, so a solver
that moves less scores better and different generative models are
indistinguishable once binned at matched motion. End to end this shows up as the
clip that fits BEST by IoU (0.941) footprinting WORST against the artist's own
frames (74.1%).

**So `fit`'s numbers judge one thing only: whether a pose explains a frame.**
They cannot rank rigs, they cannot rank generative models, and they cannot say a
clip is good. `scripts/ground_truth.py` against an artist's own frames is the
only judge in this project for any of that, and any figure in this file quoted as
an IoU should be read as a diagnostic and never as a score. The dead ends this
closes are recorded in their own sections: a second limb segment, a wider fit
search, and better video capture were each measured against IoU, and each
dissolves once the target is measured too.

### What is still wrong, and it is not the fit

The legs are mush and no constraint reaches it. Running the real build on the
corpus knight, the six shipped clips split cleanly by what a RIGID body can do:

    die     good      -- a whole-body topple is exactly a rigid rig's strength
    idle    good      -- subtle, character intact
    walk    fair      -- legs move, head steady
    run     fair
    hurt    fair
    attack  weak      -- a swing needs an elbow

The build's own warning says it: *"walk is 8 frames but only 7 different
pictures; either the motion is too small for a character this size"*. The clips
that look good are the ones a rigid body can perform. The clips that look bad
need a limb to bend. That is the whole remaining gap.

## Skinning: the joint does not move, and that was the ceiling

**The answer to the three refutations below.** A stretched arm box, a luminance
seam carve and an Opus vision rig all produce anatomically better parts and all
animate worse, and all three fail identically: give a limb the part of the body
it genuinely attaches to, transform it rigidly, and the shoulder swings as far as
the hand. The fault was never the boxes. It is that every pixel of a part gets
the same matrix.

    world(pixel) = parent's world transform @ local(pose * w(pixel), pivot)

`w` runs 0 at the joint to 1 at the free end. `skeleton.damped` weights the pose's
CHANNELS, not the matrix -- averaging two matrices is not a rigid transform, and
a half-weighted 40-degree rotation would collapse the limb towards a line.

**Bands, not per-pixel.** A per-pixel transform needs a forward scatter and a
forward scatter leaves holes. Each part is cut into bands of equal weight, each
transformed rigidly through the existing supersampled nearest-neighbour path, and
composited from the joint outwards. Bands OVERLAP by half a step, so a seam
between two of them is drawn twice rather than not at all. The band count is
chosen from the part's own differential travel, so a still limb costs nothing.

Three properties survive and they are the ones that matter. REST stays byte-exact
(at rest every channel is already at rest, so any weight leaves the identity).
The palette stays a subset (every band is nearest-neighbour). And skinning can
only ever move a pixel LESS than the rigid path, so it cannot invent anything.

### Three details that were each wrong once

* **The band's weight is the MAXIMUM in it**, not its midpoint and not its mean.
  A thin leg's outermost band holds weights 0.8 to 1.0, so its mean is 0.95 and
  the foot gets 95% of its swing -- a silent global damping of every clip, and on
  a 14px leg the difference between a foot that clears the floor by a pixel and
  one that does not. It broke `test_levelling_puts_the_drawn_feet_on_one_row`,
  which is exactly what that test is for.
* **The legibility guard judges the PART, once, before banding.** A band is a
  fraction of a limb and so has a fraction of its spread; asking the guard about
  each band separately quantises them all independently and puts a step in the
  middle of the limb. And if a part's own transform is too small to draw, there
  is nothing for skinning to protect either.
* **`_legible` returns its argument by identity** on every path that declines to
  quantise, because `render_pose` tests `is` against it to learn whether the
  transform was legible.

### The weight field: two goes, and the failure is the interesting half

The first version measured straight-line distance FROM THE PIVOT, and on the
knight's vision rig the chest strip its arm box wrongly caught scored **0.8 and
0.9 out of 1** -- because that strip is not near the pivot, it runs down the
inner edge five or six pixels below it. It took nearly the whole swing and went
on snapping the belt exactly as it had before skinning existed.

What actually distinguishes those pixels is that they are pressed against the
torso, which the cut already knows: `cutout.parent_mask` reads it straight off
the ownership map. Seeding a GEODESIC wavefront from where a part touches its
parent gives the field the argument asks for -- 0 down the chest strip, 9 at the
mitten -- and it is `WEIGHT_FIELD = "attachment"` in `skin.py`.

**It is not what ships**, and that is worth stating plainly:

| field | mean, matched coverage | |
|---|---|---|
| rigid, no skinning | 30.85% | |
| **pivot, straight-line** | **30.46%** | **shipped** -- 6 better, 2 worse |
| pivot, geodesic | 30.91% | |
| attachment, geodesic | 30.91-31.36% | 2 much better, 7 worse |

The attachment column is not uniformly worse. It splits, cleanly:

| clip | drawn | rigid | attachment |
|---|---|---|---|
| sumohulk walk | face-on | 27.7% | **19.8%** |
| eldiran walk | face-on | 29.1% | **21.3%** |
| horse walk | profile | 27.2% | 36.5% |
| horse run | profile | 32.1% | 37.3% |
| forest run | profile | 12.5% | 16.9% |

Both big wins are FACE-ON characters and all three big losses are PROFILE ones.
That is not noise. `fronted` rewrites a face-on clip's swings as TRANSLATIONS,
and a translated limb slides off its socket, so pinning the socket is the whole
fix; a profile limb already rotates about a pivot AT its joint, so the joint is
pinned for free and attachment weighting only removes motion that was right.

**So the next thing to try is not a better field. It is choosing between these
two by whether the part's pose translates it or turns it.** A `JOINT_SHARE`
threshold -- "a joint is small, a tail lying along a rump is not" -- was built
and swept (0.0, 0.2, 0.35) and moves the mean by nothing at all: 30.91% at every
value. Recorded so it is not built twice.

## The vision rigger was the great hope, and it loses

**Backlog item zero, run, and the answer is no.** Every number in this file was
measured on the TEMPLATE backend, and the standing assumption -- stated in the
PR, in this file, and in the build's own warnings to the user -- was that the
silhouette rigger is the pipeline's largest remaining source of error and a
model that actually LOOKS at the art would beat it. One data point supported
that. Twelve now refute it.

Vision rigs built with `claude -p` on Opus, one per ground-truth subject, 21-49
seconds each. Both columns are the matched-coverage error, which is the only
comparable one:

| subject | clip | template | vision |
|---|---|---|---|
| sumohulk | walk | 27.7% | **27.6%** |
| sumohulk | idle | 61.1% | **59.6%** |
| sumohulk | jump | **28.7%** | 32.8% |
| sumohulk | attack | 42.0% | **38.6%** |
| horse | idle | 46.1% | **43.9%** |
| horse | walk | 27.2% | **26.0%** |
| horse | run | 32.1% | **29.1%** |
| forest | run | **12.5%** | 17.0% |
| mv-male | walk | 27.3% | **26.4%** |
| mv-male | crouch | **14.8%** | 30.1% |
| mv-male | attack | **21.6%** | 27.9% |
| eldiran | walk | **29.1%** | 59.8% |
| **mean** | | **30.9%** | 34.9% |

Six clips each, one tie, and the template wins the mean by four points. The
`19.4%` figure quoted elsewhere in this file for a vision rig is not reproduced
by any of these and should be treated as unverified until someone re-derives it.

**The reason is worth more than the result, and it is the same reason twice.**
The knight is the largest single gap -- 29.1% against 59.8% -- and it is exactly
the sprite where the vision rig's boxes look obviously more correct:

    template   torso (0, 14, 26, 26)   arms 5x4 chips of mitten, legs boot tips
    vision     torso (4, 14, 22, 26)   arms (0,14,8,26) and (18,14,26,26)
                                        legs from row 24, greaves included

That is the same segmentation the seam carve produced and this file already
records as refuted -- arrived at independently, by a model looking at the
picture, and it loses by thirty points. Rendered large the reason is plain: the
vision arm boxes OVERLAP the torso's x range, they are smaller than it, so
smallest-box-wins hands each arm a strip of chest -- and rotating that strip
**breaks the belt**, a solid red line across the waist, in half the frames. The
head bobs again too, because the arm carries shoulder with it.

So three independent attempts -- a stretched arm box (recorded above), a
luminance seam carve, and an Opus vision rig -- all produce anatomically better
parts and all animate worse, and all three fail the same way: a limb given the
part of the body it genuinely attaches to will TEAR that body when it moves
rigidly.

**The conclusion is that the ceiling is not the rigger.** It is that ownership
is a partition of rectangles and a part is moved rigidly. An artist's arm is
attached at the shoulder and free at the hand; ours is equally free along its
whole length, so every pixel of the shoulder travels as far as the mitten does.
Nothing about better boxes fixes that. What would: a per-part weight that falls
to zero at the joint, so a part DEFORMS rather than translates -- which is
skinning, and is a much larger change than any rig backend.

Two smaller findings from the same run:

* **`--facing` caught a fourth subject, and this time it caught the harness.**
  The vision model called `sumohulk` face-on; the ground-truth harness had been
  defaulting it to right-facing. The artist's own strip settles it -- a frog
  hopping AT the camera -- so every sumohulk number published before this was on
  a mis-faced rig. Corrected: walk 36.2% -> 27.7%, jump 34.7% -> 28.7%, attack
  54.5% -> 42.0% at matched coverage, idle 57.3% -> 61.1%.
* **And the model over-called it on two.** It read `forest` and `mv-male` as
  face-on; both artists' strips are unmistakable profiles. A silhouette-symmetry
  test was tried first to settle this and is useless -- hair and a held item put
  the two profile characters at 72.6% and 76.6% against the true face-on
  knight's 93.3%, with no threshold between them. **Only the artist's animation
  frames answer this question.** The facing field is the one thing a vision rig
  is measurably WORSE at than a default.

### A knee, added by default — refuted, and the split is by CHARACTER SIZE

**The most compelling win on this branch, and it is a regression in the actual
product.** Worth reading before anyone adds a joint again.

Fitting an exaggerated generated walk on the corpus knight, giving the legs a
second segment raises mean silhouette agreement over eight frames from **0.721 to
0.754**, and EVERY frame improves. The cut point barely matters (0.744 to 0.754
across 0.4 to 0.6), which is exactly what a real effect looks like -- the gain is
the joint, not its placement.

Then measured against the artists' own frames, at matched coverage, on all twelve
ground-truth clips:

    mean, matched coverage     6-part 30.46%     with knees 32.36%   (+1.90)
    3 clips better, 8 worse, 1 unchanged

The reason is simple once seen and was predictable: **the hand-authored clips
never author a knee bend.** Nothing in the library drives a lower leg segment, so
splitting the leg adds a seam that can tear and buys no motion at all. The
generated fit improves because generated motion HAS knee bend to capture; the
shipped clips do not.

**But the three that improve are all one character**, and it is the largest:

    mv-male, 46px   walk 27.9 -> 25.6    crouch 15.3 -> 14.1    attack 21.4 -> 20.4
    everything else, 15-33px             worse, up to 27.1 -> 36.8 on the horse

Same size floor this project keeps rediscovering. A 46px character has room for a
knee; a 15px brawler does not, and a joint there is a seam with nothing to gain
by it.

**So a knee is not a rig improvement, it is a motion requirement.** Add one only
where there is motion that needs it -- the fitted path, where `better_split`
already asks exactly that question -- or on a character big enough to draw it.
Never by default. `fit.split_part` and `fit.better_split` stay; nothing calls
them from `build`, and that is deliberate.

## Dead ends — measured, not guessed

### Segmenting a limb by the shading crease the artist drew — the third rig fix, refuted

**The most promising idea tried here, built end to end, and it does not pay.**
Recorded in full because it will be thought of again, and because the reason it
fails is not the reason you would guess.

The complaint it answers is real and is the one a viewer makes: on the corpus
knight, `torso` contains both pauldrons, both sleeves and the top of each boot,
while each `arm` is a **5x4 chip of the outer mitten** and each `leg` is a boot
tip. The walk then swings two chips and rotates the shoulders with the chest.
`core_and_limbs` is right about the pixels and blind above them — it keeps only
the rows where the silhouette parts into three spans, and the knight's parts on
three rows out of twelve.

But the boundary is not missing from the picture, only from its outline. A pixel
artist separates two overlapping parts with a crease a shade darker than either.
On the knight it runs unbroken from the shoulder down to the row where the arm
finally clears the body — two of its eight rows are pure black and one is a hole
right through the sprite:

```
     01234567890123456789012345      cols 9-10 and 20-21 are the creases
 15  ....abeefdbdaaaaaaaadbdfee      b = luminance  91
 17  ...aggdffbdfeeffffeefdbffd      d = luminance 122
 19  ...adbbgabdffeeffeeffdbahh      f = luminance 152
 21  ...aefffa.abddfddfddba..ad      e = luminance 193
```

So: cheapest 8-connected path from a column the silhouette PROVED is a boundary,
climbing to the shoulder, paying each pixel's luminance to pass through it and a
`drift` to step sideways, forbidden to leave the art (or the black outline —
the cheapest dark line on any sprite — swallows it), and stopping on the first
row where its own pixel is no darker than that row's median. Parts became
`(y, x0, x1)` spans on `Part.region`, honoured through the same `_reach` hook
the spinner disc already used, so ownership stayed a total function and REST
stayed byte-exact.

**It works as computer vision.** The seam lands on the artist's crease pixel for
pixel, symmetrically, over a `drift` plateau from 20 to 60. The parts it cuts
are visibly arms — a pauldron tapering into a mitten — instead of chips.

**It measures worse, and the artist's own pixels say why.** Against the knight's
three front-walk frames, at matched coverage:

| rig | best motion | error at matched coverage |
|---|---|---|
| shipped (chips) | arm `dx` | **25.5%** |
| seam arms, run to the shoulder | arm `dx` | 46.7% |
| seam arms, self-terminating | arm turns, full swing | 27.6% |
| seam arms + seam legs | arm turns x0.80 | 30.2% |

The artist moves **nothing above row 17**. The pauldron is anatomically part of
the arm and they animate it as part of the body — armour bolted to a shoulder
does not swing. A segmentation that is right about anatomy is not automatically
right about animation, and this is the cleanest example of that in the project.

**And it fires on 1 of 28 corpus assets.** The start column has to be *proved*,
which needs the silhouette to part into three spans — left arm, torso, right
arm. That happens on a character drawn face-on and essentially never on one in
profile, where the near arm hides the far one and the silhouette parts into two.
The character the seam would help most is the one it cannot start on.

Two things to take from it. The seam finder itself is sound and cheap, and if a
use is found where the start column comes from somewhere else — a vision model's
box, a user's click — it is forty lines. And "the arms barely separate from the
body" is still the honest note to give the user, because the information a rig
needs here is about how the character is BUILT, not how it is drawn.


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
