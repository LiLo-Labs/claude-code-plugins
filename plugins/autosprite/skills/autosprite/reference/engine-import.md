# What gets written, and how each engine reads it

Every build writes the sheet, the native atlas, a rig, two ZIPs, GIF
previews and one file per requested engine. `--engines` takes a comma list,
`all`, or `web`.

| File | Who reads it |
|---|---|
| `<name>.png` | the texture; everything else points into it |
| `<name>.autosprite.json` | this pipeline. Complete: clips, fps, loop, per-frame rects, anchors, direction fidelity, the source's own report |
| `<name>.rig.json` | `animate.py` and `rig.py`, for iterating |
| `<name>-frames.zip` | one PNG per frame, cut back out of the finished sheet |
| `<name>-animations.zip` | one folder per animation: `<anim>/spritesheet.png`, `<anim>/atlas.json`, `<anim>/frames/01.png…` |
| `preview/*.gif`, `preview/contact-sheet.png` | you and the user |

## Phaser 3 / PixiJS

`<name>.phaser.json` (TexturePacker JSON hash). Frame names are
`<clip>_<index>.png`, e.g. `walk_003.png`; with directions, `walk_SE_003.png`.

```js
this.load.atlas('hero', 'hero.png', 'hero.phaser.json');
// ...
this.anims.create({
  key: 'walk',
  frames: this.anims.generateFrameNames('hero', {
    prefix: 'walk_', suffix: '.png', start: 0, end: 7, zeroPad: 3 }),
  frameRate: 10, repeat: -1     // frameRate and repeat come from the atlas's clip
});
```

`repeat: -1` for a clip whose `loop` is true, `repeat: 0` otherwise. The frame
rate is in `<name>.autosprite.json` under each clip's `fps`; Phaser will not read
it out of the atlas for you.

`<name>.texturepacker-array.json` is the same data in array form, for PixiJS and
anything else that wants it.

## Unity

`<name>.png.meta` next to `<name>.png`. Drop both into `Assets/` and Unity
imports the sheet already sliced: `spriteMode: 2` (Multiple), one sprite per
frame, `alignment: 9` (Custom) with each frame's pivot, `filterMode: 0` (Point)
so pixel art stays crisp, and `spriteExtrude` matching the sheet's own extrude.

Sprite names match the atlas frame names. Build an animation by selecting a
clip's sprites in order and dragging them into the scene, or read the fps from
`<name>.autosprite.json` and set the AnimationClip's sample rate to it.

The GUID is derived from the sheet name, so re-exporting the same sheet keeps
every reference in the project intact. Renaming the sheet does not.

## Godot 4

`<name>.tres`, a `SpriteFrames` resource. Put it and the PNG under `res://` and
assign it to an `AnimatedSprite2D`. Each clip is one animation with its own
`speed` (fps) and `loop` flag; every frame is an `AtlasTexture` region into the
sheet.

The resource points at `res://<name>.png`. If the texture lives in a
subdirectory, fix that one `ext_resource` path.

Set the texture's import filter to **Nearest** in Godot's import dock, or the
sheet will be smoothed and the extrude will be the only thing keeping the frames
from bleeding into each other.

## Unreal Engine

`<name>.unreal-paper2d.json` — Unreal's `PaperJsonImporter` reads TexturePacker
JSON (array form) and dispatches on `meta.app`, so this is that format under a
name that says what it is for. Import the PNG first, then the JSON, and Paper2D
creates one sprite per frame. Build a flipbook from a clip's sprites and set its
frame rate from that clip's `fps` in `<name>.autosprite.json`.

## GameMaker

`<name>.gamemaker.json` is a manifest, not a project file: GameMaker has no
sprite-atlas importer, and a JSON claiming to be one would import as nothing.

- **Grid layout**: use *Import Strip* with the `strip` block's `cellWidth`,
  `cellHeight`, `offsetX`, `offsetY`, `columns` and `rows`. One row per clip.
- **Packed layout**: import `<name>-frames.zip` as loose frames.
- **One animation at a time**: use `<name>-animations.zip`. Each folder is
  self-contained -- a horizontal strip, its own atlas with that clip's fps and
  loop flag, and the individual frames numbered from 01. Every frame in it is
  byte-identical to the master sheet's own crop, and the ANIMZIP check proves
  that on every build.

Set each sprite's playback speed from the clip's `fps` and its origin from the
clip's `origin`.

## RPG Maker MV / MZ

`$<name>.png`. RPG Maker does not read an atlas — a character file is a fixed
grid of 3 columns by 4 rows, in the order **down, left, right, up**, and the
engine derives the cell size by dividing the image. The leading `$` tells it the
file holds one character rather than an eight-character page; keep it.

This needs the walk animation in all four cardinals, so build with
`--directions 4`. Without them the build says so and writes nothing rather than
writing a sheet that imports wrong.

The three columns are one **stride**, not one cycle: MV plays them 0,1,2,1, so
they are sampled across half the loop and the middle column is the passing pose.

## Aseprite and everything else

`<name>.aseprite.json` is Aseprite's export format, with `meta.frameTags` naming
each clip and its frame range. Most sprite tooling that is not an engine reads
this.

## Layout, padding and extrude

`--layout grid` gives uniform cells, one row per clip, every frame aligned by
its anchor. Larger, and the only layout several importers can read without an
atlas at all. Default.

`--layout packed` shelf-packs tightly. Smaller, and unusable without the atlas
JSON.

`--layout strip` unrolls the grid into one horizontal row. The oldest sheet
layout there is, and still what GameMaker's *Import Strip* and anything that
slices by dividing the width by a frame count expect. Same cells and the same
anchor alignment as the grid.

`--compress` rewrites the sheet as an **indexed PNG**, and here that is
*lossless* rather than quantised: the sheet's palette is provably a subset of
the source art's, so there is nothing to throw away. Across the test corpus it
is about 47% smaller. It is not always a win -- a 256-entry palette table is a
fixed cost that a four-colour sheet loses on -- so both are written, the smaller
is kept, and the build says which happened.

`--padding` is a transparent gutter and `--extrude` repeats each frame's edge
pixels into it. Both default to 1 and both are there for the same reason: the
GPU samples slightly outside a rect whenever the sprite is drawn at a
non-integer position or scale. Padding alone gives a transparent halo; extrude
gives the character's own colour. Neither costs anything at runtime.

`--scale N` upscales the finished sheet nearest-neighbour, for engines or
pipelines that want the art at a fixed size. The gutter is not scaled — one
pixel of gutter is one pixel of gutter whatever the art is scaled to.

`--power-of-two` grows the texture to the next power of two in each dimension
without moving a single frame.
