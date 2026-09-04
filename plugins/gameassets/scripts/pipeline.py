#!/usr/bin/env python3
"""Maps a pack's file-type mix to what must be DONE to it before it is a game asset.

Every rule states: the tool required, the steps, and a readiness tier.
Tiers:
  ready     - import and use; no conversion
  unpack    - extract/convert with a script we already have
  tool      - needs a specific third-party application
  blocked   - cannot reach Godot without a substantial project
"""

# (key, matcher-extensions, tier, tool, steps, notes)
RULES = [
 ("gltf-ready", {"gltf","glb"}, "ready", None,
  "Drop the .gltf/.glb (and its .bin) into the project. Godot imports natively.",
  "Preferred 3D path. Open format, no converter, materials survive."),

 ("obj-ready", {"obj"}, "ready", None,
  "Drop in the .obj with its .mtl and textures alongside.",
  "Geometry only — no rig, no animation."),

 ("fbx-import", {"fbx"}, "ready", None,
  "Godot 4 imports FBX but converts via FBX2glTF internally.",
  "Prefer the glTF version if the pack ships one. FBX carries rigs/animation; OBJ does not."),

 ("png-ready", {"png","jpg","jpeg","webp"}, "ready", None,
  "Drop into the project. Set Filter=Nearest on pixel art or it blurs.",
  "For sprite sheets without metadata you must set up the AtlasTexture regions yourself."),

 ("audio-ready", {"wav","ogg"}, "ready", None,
  "Import directly. Use OGG for music, WAV for short SFX.",
  "Godot does not import MP3 as reliably; convert MP3 to OGG."),

 ("mp3-convert", {"mp3"}, "unpack", "ffmpeg",
  "ffmpeg -i in.mp3 -c:a libvorbis out.ogg",
  "Godot 4 supports MP3 but OGG is the better fit for looping music."),

 ("unitypackage", {"unitypackage"}, "unpack", "_tools/unpack-unitypackage.sh",
  "Run _tools/unpack-unitypackage.sh <pkg> <outdir>; yields FBX + PNG.",
  "Unity .mat/.prefab/.shadergraph do NOT transfer — you rebuild materials in Godot."),

 ("tiled", {"tmx","tsx"}, "tool", "Tiled (or rebuild in Godot)",
  "Godot 4 has no native Tiled import. Either use a converter plugin, or ignore the "
  ".tmx and build a TileSet from the source PNGs in Godot's TileMap editor.",
  "The PNGs are the payload; the map files are a convenience you can discard."),

 ("aseprite", {"aseprite","ase"}, "tool", "Aseprite",
  "Open in Aseprite and export a sprite sheet + JSON, or use a Godot importer plugin.",
  "The .aseprite is the editable source — keep it, ship the exported PNG."),

 ("photoshop", {"psd","psb"}, "tool", "Photoshop / Krita / GIMP",
  "Open and export layers to PNG.",
  "Usually the editable source next to already-exported PNGs — check before doing work."),

 ("flash", {"fla","swf"}, "tool", "Adobe Animate",
  "Open the .fla in Animate and export frames as PNG sequence or sprite sheet.",
  "Legacy vector animation source. Often a PNG export already exists in the pack."),

 ("vector", {"svg","ai","eps"}, "tool", "Inkscape / Illustrator",
  "Godot imports SVG directly and rasterises at import scale. AI/EPS need conversion.",
  "SVG is resolution-independent — good for UI that must scale."),

 ("kontakt", {"ncw","nki","nkx","nkc"}, "tool", "Kontakt NCW Batch Compressor (free from Native Instruments), or Kontakt in a DAW",
  "Two routes. (a) Bulk decode: Native Instruments' free 'Kontakt NCW Batch Compressor' "
  "converts .ncw losslessly to .wav — the samples are 24-bit/48kHz — giving you "
  "individual sampled notes usable as one-shots. (b) Musical: load the .nki in full "
  "Kontakt inside a DAW, play/compose, and bounce stems to WAV/OGG.",
  "NOT importable into a game engine as-is. Route (a) yields raw multisampled notes "
  "(per-pitch, per-velocity, often with round-robins) — usable as SFX source material "
  "but not as a playable instrument, and the volume is large. Route (b) is what the "
  "library was sold for. Full Kontakt is required for most 8dio libraries; the free "
  "Kontakt Player will not load them. Unverified here: no decoder was run against "
  "these files, the format was identified from the NCW header only."),

 ("unreal", {"uasset","umap"}, "blocked", "Unreal Engine + UEViewer/FModel",
  "Install UE, add the asset to a project, then extract meshes/textures with "
  "UEViewer(umodel) or FModel to FBX/PNG.",
  "Materials, blueprints and shader graphs do not survive. Substantial project, not a download."),

 ("rpgmaker", {"rvdata2","rxdata","rpgproject"}, "tool", "RPG Maker",
  "Assets are usually plain PNG/OGG in subfolders — use those directly and ignore "
  "the project files.",
  "The .rvdata2 is RPG Maker's own database; irrelevant outside RPG Maker."),

 ("godot-native", {"tscn","tres","gd"}, "ready", None,
  "This pack already contains a Godot project — open project.godot directly.",
  "Best case: scenes and scripts already wired up."),

 ("font", {"ttf","otf"}, "ready", None,
  "Drop in; Godot imports fonts natively. Check the OFL/EULA for embedding rights.",
  "Font licences differ from art licences even inside the same pack."),

 ("itch-metadata", {"html","json"}, "metadata", None,
  "itch-dl scrape artefacts (site.html, metadata.json, cover image). Not an asset.",
  "Safe to ignore. Useful only for recovering the original store page URL."),

 ("game-build", {"exe","apk","dmg","app","dll","so","gmz","rvdata2","rpyc","rpy","pyo"},
  "game", None,
  "This is a playable game build, not an asset pack. Run it, don't import it.",
  "Some games ship their art loose in subfolders — check before assuming there is "
  "nothing usable. GameMaker .gmz files are editable project sources."),

 ("nested-archive", {"zip","7z","rar","bz2","gz","tar"}, "unpack", "unzip / 7z / tar",
  "Archive of archives — extract the outer one, then treat each inner archive as its "
  "own pack. INDEX.tsv carries `nested` rows for the inner contents.",
  "Size and file counts on the outer row describe the wrapper, not the payload."),

 ("raster-source", {"tif","tiff","procreate","brushset","abr"}, "tool",
  "Photoshop / Procreate / Krita",
  "Open in the host app and export flattened PNG at the size you need.",
  "Brush and texture sources — for authoring art, not for direct import."),

 ("engine-artefact", {"lighting","meta","asset","bin","bas","cache"}, "metadata", None,
  "Engine-generated sidecar (Unity .meta, baked .lighting, etc). Not source art.",
  "Regenerated automatically by the engine; carries no content of its own."),

 ("notes", {"txt","md","nfo","readme"}, "metadata", None,
  "Plain-text notes, credits or instructions.",
  "Worth reading for attribution requirements."),

 ("rom", {"nes","gb","gba","smc","sfc"}, "game", None,
  "A console ROM — playable in an emulator.",
  "Not an asset pack."),

 ("document", {"pdf","doc","docx","rtf"}, "metadata", None,
  "Documentation, licence or manual. Not an asset.",
  "Worth reading for the licence terms."),

 ("hdr-image", {"exr","hdr","tga","dds","ktx"}, "ready", None,
  "Godot imports EXR/HDR (skyboxes, lightmaps), TGA and DDS directly.",
  "EXR/HDR are high-dynamic-range — use for environment lighting, not UI."),

 ("app-bundle", {"pck","plist","icns","nib","rsrc","appimage","sse","vis","ecm"},
  "game", None,
  "A packaged application. A .pck alongside it is a Godot export — the game's assets "
  "are inside the .pck, not loose.",
  "Not an asset pack. Godot .pck can be unpacked with gdsdecomp if you own the content."),

 ("video", {"mp4","webm","ogv"}, "ready", None,
  "Godot plays .ogv natively; convert MP4 with ffmpeg.",
  "Rarely needed in-game; usually promo material."),
]

def analyse(ext_counts):
    """ext_counts: {'png': 400, 'fbx': 20, ...} -> (tier, matched rules)

    The tier reflects what the pack MOSTLY is, weighted by file count — not the
    best path available. A Kontakt library holding 18,650 .ncw samples and one
    .png cover image is "blocked", not "ready"; taking the best matching tier
    reports the cover art as though it were the product.
    """
    counts = {e.lower(): n for e, n in ext_counts.items()}

    # Disqualifying markers: a shipped game's art is not an asset pack, however
    # many PNGs it contains. Count-weighting alone gets this backwards — a Ren'Py
    # build is 3,648 PNGs and 1,174 .pyc, and "mostly images" is the wrong read.
    GAME_MARKERS = {"pyc","rpy","rpyc","exe","gmz","rvdata2","pck","apk","dll","so","appimage","nes"}
    if set(counts) & GAME_MARKERS:
        return "game", [r for r in RULES if set(counts) & r[1]]
    present = set(counts)
    matched = [r for r in RULES if present & r[1]]
    if not matched:
        return "unknown", []

    # how many files does each tier account for?
    weight = {}
    for r in matched:
        weight[r[2]] = weight.get(r[2], 0) + sum(counts.get(e, 0) for e in (r[1] & present))
    total = sum(weight.values()) or 1

    # a tier holding the majority of files decides the pack
    dominant = max(weight, key=weight.get)
    if weight[dominant] / total >= 0.5:
        tier = dominant
    else:
        order = {"ready": 0, "unpack": 1, "tool": 2, "game": 3, "metadata": 4, "blocked": 5}
        tier = min(weight, key=lambda t: order[t])
    return tier, matched
