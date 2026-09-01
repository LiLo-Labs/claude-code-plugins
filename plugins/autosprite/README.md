# AutoSprite Plugin

> **Picking this work up?** Start with [HANDOFF.md](HANDOFF.md): what is
> measured to work, the ordered backlog, and the dead ends that are not worth
> walking again.

Turns one character image into a finished, engine-ready animated sprite sheet
from a single command.

```
hero.png                                       hero-sprites/
                          /autosprite            hero.png                 ← the sheet
                         ─────────────────►      hero.autosprite.json     ← clips, fps, loop, rects
                                                 hero.rig.json            ← the parts, editable
                                                 hero.png.meta            ← Unity, pre-sliced
                                                 hero.tres                ← Godot SpriteFrames
                                                 hero.phaser.json         ← Phaser / PixiJS
                                                 hero.unreal-paper2d.json ← Unreal Paper2D
                                                 hero.gamemaker.json      ← GameMaker strip params
                                                 $hero.png                ← RPG Maker MV/MZ
                                                 hero-frames.zip          ← every frame as a PNG
                                                 preview/*.gif            ← what you actually review
```

The input file is never written to.

## The palette guarantee

**Nothing in this plugin generates a pixel.** There is no image model anywhere
in it, and that is the design rather than a limitation: every pixel of every
output frame came out of the image you supplied, so the sheet is unambiguously
your art, and the pipeline can make a claim a generative one cannot.

Three mechanisms hold it:

1. **Every transform is nearest-neighbour.** Rotation, scaling, foreshortening
   and packing all sample without interpolating, so no colour is ever averaged
   into existence.
2. **Every composite is an alpha test, not a blend.** Two overlapping parts
   never average into a third colour.
3. **`verify.py` checks it and reports.** The `PALETTE` check compares the
   finished sheet's colours against the source's and fails on any escape.

The corollary is a real constraint, stated plainly: this plugin cannot draw a
view your reference does not contain. A back view needs a back drawing. It will
tell you which directions it approximated rather than implying otherwise.

## How it works

```
vision   ->  names the character's parts and where they hinge     rig.json
cutout   ->  cuts those parts out of your own pixels              parts
motion   ->  poses the skeleton over time                         poses
render   ->  composites the posed parts                           frames
pack     ->  lays the frames out                                  sheet.png
atlas    ->  writes what every engine needs to read it            *.json/.tres/.meta
verify   ->  proves the sheet still contains exactly those frames  PASS/FAIL
```

Only the first stage has an opinion, and it is deliberately the smallest one: a
part is a name, a box, a parent and a pivot — four things a vision model can be
held to and a human can correct in ten seconds by editing one line of JSON.
Everything a model is bad at stays out. Masks come from the pixels. Angles and
timing come from a keyframe table you can read and argue with.

### Two rigging backends

| Backend | Needs | Use it when |
|---|---|---|
| `--backend template` | nothing at all | The default silhouette read. Finds the neck at the last narrow row before the shoulders and the hips where the outline parts and stays parted. Right more often than not on a standing character |
| `--backend claude` | a `claude` CLI on PATH; **no API key** | The silhouette will lie: a staff held across the body, a cape, a mount, a robot, a 3/4 view |

`claude -p` runs with the session's own credentials, so the vision path costs
nothing beyond the Claude subscription you already have. The whole test suite
runs against the template backend, so CI needs no model and no network.

## What it makes

**Sixteen character animations** — idle, walk, run, dash, climb, fly, crouch,
jump, land, attack, block, cast, throw, hurt, die, sleep. Frame counts, rates and loop
points are tuned per animation and all three are overridable (`--frames`,
`--fps`, `--loop-start`/`--loop-end`). Presets: `basic`, `platformer`,
`topdown`, `action`, `full`, `everything`.

**A build that checks and repairs its own pictures** — every other check here
proves something about bookkeeping, and all of them pass on frames that are
visibly wrong, because mass is conserved when parts are merely scrambled. So the
build also measures what a viewer sees, and acts on it:

- A clip measured to be coming apart has the responsible swing — and only that
  one — reduced until it holds together, and the report says which part, on
  which frame, and by how much. When damping does not help it says so and
  changes nothing, because that is a rig problem and quietly shipping a quieter
  broken clip would hide it.
- A transform is not allowed to break something the artist drew in one piece. A
  flask squashed to 40% loses its two-pixel neck before its five-pixel rim, so
  the cork comes off with nothing having rotated; the renderer threads it back
  with the colour that block would have had.
- A clip that claims a foot is on the floor has the root corrected until it is,
  because a rigid leg rotated about the hip lifts its own foot. The walk's body
  bob then comes out of the leg geometry rather than being authored.

**A vision critic** — `--critic claude` shows a rendered clip to a vision model
and asks what is wrong with the *motion* -- or with the RIG, which it is also
shown, so it can answer "this rig is wrong for this character" rather than
tuning a limb the character does not have -- then folds the answer back into the
keyframes. It is the only thing here that judges whether a cycle reads, which no
measurement in this plugin can. Every round is re-measured, and one that makes
the character come apart is thrown away — so the model can improve how the
motion looks and can never break the character to do it.

**Custom animations** — a JSON keyframe table, validated and rendered by the
same path as the built-ins. This is how a plain-language request ("make the walk
look tired") becomes motion: write the keyframes, render, watch, adjust.

A keyframe carries a whole pose, which is compact and has one hard limit: every
channel of a part shares one set of instants, and a key that omits a channel is
asserting that channel is at rest. "The stretch peaks two frames after the punch
lands" is therefore unsayable — adding the late `sx` key drags the angle back to
zero with it. So a track may also carry **lanes**: one channel, on its own
timeline, with its own easing.

```json
"arm_near": {
  "keys":  [{"t": 0.0, "angle": -25}, {"t": 0.35, "angle": 75, "easing": "ease_out"}],
  "lanes": {"sx": [{"t": 0.45, "v": 1.2}, {"t": 0.8, "v": 1.0}]}
}
```

A lane replaces one channel and leaves every other one alone, so the sixteen
built-in clips — none of which uses a lane — sample exactly as they did. This is
the mechanism behind overlapping action and follow-through, which is most of
what separates motion that reads as animation from motion that reads as parts
moving.

**Eight-direction movement** — with every direction labelled `drawn`,
`mirrored`, `foreshortened` or `substituted`, so nothing claims to be a view it
is not. `--reference-front` and `--reference-back` turn the cardinals into
drawn ones, and each is rigged **face-on** rather than with the side view's
facing: both limbs of a pair in front of the torso, named left and right, and
every clip trading its sideways swing for a lift. A leg walking towards the
camera foreshortens; it does not sweep across the picture. `--facing front` does
the same for a single sprite drawn that way.

**Anything that is not a character** — two kinds of clip, and they are not the
same kind of thing. `bob`, `spin`, `tumble`, `pulse` and `swing` move the sprite
as one piece, which for a coin is not a lesser path but the right answer. The
rest are addressed by **what a part is** rather than by a name from a
thirteen-word humanoid vocabulary:

| Clip | Addressed at | Which is |
|---|---|---|
| `turn` | `trait:spinner` | sails, a waterwheel, a cog, a fan |
| `sway` | `trait:stalk` `trait:surface` | a canopy, a cape, a flag, a field of wheat |
| `gust` | `trait:stalk` `trait:crown` | the same, hit once by the wind and settling |
| `ripple` | `trait:surface` | water, a banner, a curtain |
| `creak` | `trait:socket` | a shutter, a sign, a lantern hung on a building |

A trait is a property a role implies (every `accessory` is a `stalk`, every leg
is a `support`) plus anything the rig tags a part with, so a windmill's sails
keep whatever role they were given and are tagged `spinner`. `gust` was written
for trees and drives a hero's cape, because "fixed at its base, free at its tip"
is true of both and `tail` is true of neither.

A clip may name several parts at once and give each one a **spread** — the same
curve, played a little later by each in turn. That single field is a travelling
wave across a wheat field, a chain of segments following the one before it, and
a canopy lagging its trunk.

Nothing here ships a row of identical frames: a clip addressed at a trait the
subject does not have is dropped, and the build says which trait was missing.

A prop with no such part still rigs as one piece, which is never wrong, only
plain — and the vision prompt says so, because it had been splitting a glass
flask into bowl, neck and cork, none of which is a joint.

**Two ZIPs** — `<name>-frames.zip` is every frame as a loose PNG;
`<name>-animations.zip` is one folder per animation with its own strip, atlas and
numbered frames, which is what an importer taking one animation at a time
wants.

**Outfitting** — `--attach hand=sword.png`. A sword drawn once ends up in the
right hand of a character it has never met, in front of the arm, and swings
through every clip. Sockets — `hand`, `off_hand`, `head`, `waist`, `chest` — are
**derived from the rig rather than declared**, which is what makes "works with
every character" true rather than aspirational: a hand is the free end of the
near arm, and every humanoid rig has one whether or not its author thought about
outfitting. A rig with no far arm has no off-hand and says so, instead of putting
a shield in the middle of the torso.

The item is composited into the source art *before anything else runs*, and the
composed image is written out as `<name>.source.png`. That is what makes it cost
nothing: the item is a rig part parented to the arm, so forward kinematics
carries it and there is no second pipeline to keep in step — and every check
still means what it meant. REST still proves the parts reassemble into the
source exactly, because the composed art **is** the source. PALETTE still proves
every output colour came from the input, because the input now contains the
sword's colours. Nothing was relaxed to let an item in.

The limitation, stated rather than discovered: an item goes **in front of** the
part it hangs on. Compositing at rest cannot record pixels hidden at rest, so a
scabbard behind the body would lose whatever the body covers.

**Outfit and skin variants** — recoloured by shading RAMP rather than by colour,
so the shading survives. Ramps are found by hue *and by adjacency*: two shades
belong to one material only if they touch somewhere in the art, which is what
separates brown boots from tan skin when hue alone cannot.

## Usage

```bash
/autosprite hero.png --game platformer
```

Or the scripts directly:

```bash
# rig, and look at the overlay before anything else
python3 scripts/rig.py --input hero.png --out out/ --backend claude --preview

# build
python3 scripts/build.py --input hero.png --out out/ \
    --animations platformer --directions 4 --backend claude

# fix a line of the rig -- tag the sails `spinner` -- and build with that rig
python3 scripts/build.py --input mill.png --out out/ \
    --rig out/mill.rig.json --animations building

# put a sword in their hand; @27,27 says where it is held
python3 scripts/build.py --input hero.png --out out/ \
    --attach hand=sword.png@27,27 --attach head=hat.png

# iterate on one cycle without rebuilding the sheet
python3 scripts/animate.py --input hero.png --rig out/hero.rig.json \
    --animation walk --custom my-walk.json --out look/

# recolour by ramp
python3 scripts/variants.py --input hero.png --out var/ --describe
python3 scripts/variants.py --input hero.png --out var/ \
    --name 0=skin,1=cloak,2=boots \
    --variant '{"cloak": {"hue": 0}}' --variant-name red

# prove an output directory
python3 scripts/verify.py --dir out/ --reference hero.png --rig out/hero.rig.json
```

## The verification gate

Every failure mode of a sprite-sheet generator is silent. A rect off by one row
looks perfect and animates with a one-pixel jitter. A pivot flipped in the Unity
meta puts every sprite underground. An engine file that disagrees with the atlas
works in Phaser and not in Godot. So each check compares two artefacts produced
independently, and the exit status is the answer:

| Check | What it proves |
|---|---|
| `RECT` | Every atlas rect lies inside the sheet and has content in it |
| `ZIP` | Every frame in the ZIP is byte-identical to its crop from the sheet |
| `ANIMZIP` | Every frame in the per-animation ZIP is byte-identical to its master crop and to its own strip |
| `PALETTE` | Every colour in the sheet came from the source art |
| `ENGINES` | Every engine file's rects, counts and animation names match the atlas |
| `ANCHOR` | Every frame of a clip shares one anchor |
| `REST` | The rig's parts reassemble into the source image **exactly** |

`REST` is the one that checks the cut rather than an export: it proves that
splitting the art into parts lost and duplicated nothing. It earned its place —
it caught a real bug where every pixel outside the rig's declared boxes (115 of
them on the first real sprite this was run against) was assigned to the root and
then silently dropped, producing a sheet that built fine and was missing part of
the art.

It does not check whether the parts are *named* right. A rig that calls the head
a leg reassembles perfectly, because reassembly is about which pixels went where,
not what they were called. Only watching the preview GIF answers that.

## Input handling

Real files are not clean, and three things go wrong silently:

- **An opaque background.** Flooded from the border, comparing against each
  seed's own colour so a gradient stops the flood instead of eating into the
  character. Art that already has alpha is believed and left alone.
- **Art that is an upscale.** A 32×32 sprite exported at 512×512 is 16×16 blocks
  of flat colour; rigging it at 512 shears every block into staircases on the
  first rotation. The block size is detected and the whole pipeline runs at
  native resolution.
- **Anti-aliased art.** The palette guarantee still holds, but it stops meaning
  much at 900 colours. The ingest report says so rather than quietly posterising
  your art.

## Layout

`grid` (default) gives uniform cells, one row per clip, **every frame aligned by
its anchor** — not centred, because centring a jump's apex frame in its cell puts
the character's feet back on the floor and deletes the jump. `packed` shelf-packs
tightly and is typically half the texture. Padding and extrude both default to 1
and exist for the same reason: the GPU samples slightly outside a rect whenever a
sprite is drawn at a non-integer position, and extrude puts the character's own
colour there instead of a transparent halo.

## Tests

```bash
pip install -r requirements-test.txt
python3 -m pytest tests -q
```

526 tests, no network, no model, well under a minute. Fixtures are generated rather
than checked in — `tests/make_fixture.py` builds parametric sprites so a test can
have the exact property it is about (arms clear of the body or touching, legs
parted or robed) instead of one PNG having to serve every case.

The verification tests are the ones worth reading: each breaks exactly one
artefact of a known-good build and asserts the matching check goes red, because a
verifier that cannot fail is worth nothing.
