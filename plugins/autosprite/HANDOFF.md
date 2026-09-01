# Handing autosprite on

Read this first. It is the state of the work, what is *measured* rather than
believed, the ordered backlog, and the dead ends that are not worth walking
again.

## Where it stands

The pipeline is sound and proven on real art. **20 CC0 sprites** (16×16 to
76×81; humanoids, creatures, props, and four cases chosen to break a silhouette
rigger) all build, with all eight verification checks passing on both backends.
467 tests, no network or model in any of them.

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
| variants | re-verified end to end on real art: a grey ramp recoloured blue keeps all three of its shades, the walk is identical, and every check passes |
| parity | `--frames`, `--frame-size`, `--fps`, loop points, per-animation ZIP, eight more animations |
| `climb` | its arm reach was cut from 58° to 46° after measurement: 58 threw a hand clear of a 45px character and took the clip to 9.4% shed, 46 takes it to 0.8% for one point of frame-to-frame change |

The full history of each, with the numbers, is in the git log; the commits lead
with the failure rather than the change.

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
