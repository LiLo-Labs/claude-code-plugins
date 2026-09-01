"""End to end: a character image in, a verified sprite sheet out.

The order below is not arbitrary. Two constraints fix most of it:

**Stabilisation is global, not per clip.** Every frame of every animation in
every direction is cropped to ONE box, so the anchor sits in the same place in
all of them. Stabilising per clip gives each animation its own box, and the
character then jumps when the game switches from idle to walk -- which is the
bug that looks like a physics problem and is not.

**The palette is enforced after the direction transform, not before.** The
foreshortening squash is the last thing that touches pixels, so it is the last
place a colour could escape, and enforcing before it would prove nothing.
"""

import os

from . import atlas as atlas_module
from . import cutout as cutout_module
from . import directions as directions_module
from . import image as img
from . import ingest as ingest_module
from . import motion as motion_module
from . import pack as pack_module
from . import palette as palette_module
from . import preview as preview_module
from . import quality as quality_module
from . import render as render_module
from . import repair as repair_module
from . import rig as rig_module
from . import skeleton as skeleton_module
from . import verify as verify_module
from . import vision as vision_module


class Build:
    """Everything one run produced, so the caller can report on all of it."""

    def __init__(self):
        self.references = {}
        self.rigs = {}
        self.cutouts = {}
        self.clips = []
        self.sheet = None
        self.written = {}
        self.sources = []
        self.previews = {}
        self.verification = None
        self.report = {"warnings": []}

    def warn(self, message):
        self.report["warnings"].append(message)
        return message


def load_references(paths, tolerance=12, native=True):
    """{view: Reference} for every view the user supplied."""
    references = {}
    for view, path in paths.items():
        if path:
            references[view] = ingest_module.ingest(path, tolerance=tolerance,
                                                    native=native)
    if "side" not in references:
        raise ValueError("a side (or main) reference is required")
    return references


# Which way each supplied view is drawn. The side view takes the user's own
# --facing; the other two are what they say they are.
VIEW_FACING = {"front": "front", "back": "back"}


def build_rigs(references, backend, character_class="auto", facing="right",
               intent="", build=None):
    """Rig every supplied view with the same backend, each facing its own way.

    A front reference is a drawing of a character looking at the camera, and
    rigging it with the side view's facing gives it a sagittal near/far rig on a
    picture with no depth axis -- the exact defect `--facing front` exists to
    fix, reintroduced through the back door for anyone who supplies the extra
    references. The view says which way it faces; the user's `--facing` only
    decides which way the SIDE view is turned.
    """
    rigs, cutouts = {}, {}
    for view, reference in references.items():
        built = backend.rig(reference, character_class=character_class,
                            facing=VIEW_FACING.get(view, facing), intent=intent)
        problems = rig_module.validate(built)
        if problems:
            raise ValueError("the %s rig is not usable: %s"
                             % (view, "; ".join(problems)))
        rigs[view] = built
        cutouts[view] = cutout_module.cut(built, reference.pixels)
        if build is None:
            continue
        if not img.equal(cutouts[view].rest(), reference.pixels):
            build.warn("the %s rig's parts do not reassemble into the source "
                       "image; that is a bug in this plugin, not in the rig" % view)
        strays = cutouts[view].strays
        total = max(1, int(img.alpha_mask(reference.pixels).sum()))
        if strays and strays / total > 0.05:
            build.warn("%d opaque pixels (%.0f%%) of the %s view fall outside "
                       "every part box; the root carries them, so they never "
                       "move independently -- check the overlay if something "
                       "should have been its own part"
                       % (strays, strays / total * 100, view))
    return rigs, cutouts


def outfit_views(references, rigs, attach, tolerance, native, source_path, build):
    """Composite the items onto every view and re-rig from the composed art.

    Only the side view is outfitted: an item drawn from the side is not a
    drawing of that item from the front, and silently pasting it there would be
    inventing a view -- the same thing `directions` refuses to do for the
    character itself. A front reference keeps its own unoutfitted rig and says
    so.
    """
    from . import ingest as ingest_module
    from . import outfit as outfit_module

    items = []
    for entry in attach:
        pixels = ingest_module.ingest(entry["path"], tolerance=tolerance,
                                      native=native).pixels
        items.append({"socket": entry["socket"], "pixels": pixels,
                      "name": entry.get("name") or "%s_%s" % (
                          entry["socket"],
                          os.path.splitext(os.path.basename(entry["path"]))[0]),
                      "grip": entry.get("grip"), "tags": entry.get("tags", ())})

    composed, rig = outfit_module.attach(references["side"].pixels, rigs["side"],
                                         items)
    img.save(composed, source_path)
    references = dict(references)
    references["side"] = ingest_module.ingest(source_path, tolerance=tolerance,
                                              native=False)
    rigs = dict(rigs)
    rigs["side"] = rig
    if len(references) > 1:
        build.warn("only the side view was outfitted; a front or back reference "
                   "keeps its own art, because an item drawn from the side is "
                   "not a drawing of that item from the front")
    problems = rig_module.validate(rig)
    if problems:
        raise ValueError("the outfitted rig is not usable: %s" % "; ".join(problems))
    cutouts = dict()
    for view, reference in references.items():
        cutouts[view] = cutout_module.cut(rigs[view], reference.pixels)
    if not img.equal(cutouts["side"].rest(), references["side"].pixels):
        raise ValueError("the outfitted art does not reassemble from its own "
                         "rig; that is a bug in this plugin")
    return references, rigs, cutouts


def _plain(selector):
    """A selector as something to say out loud in a build report."""
    if selector.startswith("trait:"):
        return "anything that is a %s" % selector[len("trait:"):]
    if selector.startswith("name:"):
        return "the part called %r" % selector[len("name:"):]
    return "the %s" % selector


def union_palette(references):
    """One palette across every view, so all directions share the guarantee."""
    import numpy as np
    stacked = np.concatenate([reference.palette for reference in references.values()])
    return np.unique(stacked, axis=0) if stacked.size else stacked


def make_clips(references, rigs, cutouts, animations, direction_plans, locked,
               build=None, repair=True):
    """Render every animation in every direction. Frames are not yet stabilised."""
    margin = max(render_module.suggest_margin(rig) for rig in rigs.values())
    clips, raw, repairs = [], [], []

    for plan in direction_plans:
        view = plan.source if plan.source in cutouts else "side"
        if plan.source not in cutouts and plan.source != "side":
            build and build.warn("direction %s wanted the %s view, which was not "
                                 "supplied; using the side view"
                                 % (plan.name, plan.source))
        rig = rigs[view]
        cut = cutouts[view]
        height = rig.size[1]

        # Operators run here and nowhere else, and the position is load-bearing.
        # AFTER --frames, because most of them bake an explicit key at every
        # frame time -- exact at the count they were baked at, and only that
        # count, so a baked table must never then be resampled. BEFORE
        # `fronted`, because a face-on rewrite trades a swing for a lift and an
        # operator should be reasoning about the swing the author wrote.
        prepared = [clip.applied(rig) for clip in animations]

        # A character drawn face-on has no depth axis to swing limbs across, so
        # the clips trade their swing for a lift before they are scaled.
        chosen = ([clip.fronted() for clip in prepared]
                  if rig.facing in vision_module.FACE_ON else prepared)
        ground = cut.ground_points()
        for animation in motion_module.scale_motion(chosen, height):
            poses = skeleton_module.posed(rig, animation, ground)
            drawn = [render_module.render_pose(cut, pose, margin=margin)
                     for pose in poses]
            if animation.planted:
                drawn = render_module.level_to_floor(cut, poses, drawn, margin)
            if repair:
                animation, drawn, note = repair_module.repair(
                    cut, rig, animation, drawn, references[view].pixels,
                    margin, render_module)
                if note:
                    build and build.warn(note)
                    repairs.append(note)
            # Anything this has to snap is a pixel the pipeline invented, so it
            # is reported rather than quietly corrected: silently fixing it is
            # what would let a future operation break the guarantee and still
            # show a green PALETTE.
            escaped = []
            frames = [palette_module.enforce(plan.apply(frame), locked, escaped)
                      for frame in drawn]
            if escaped:
                build and build.warn(
                    "%s %s: %d colour%s were not in the source art and were "
                    "snapped to the nearest that is (%s) -- every transform "
                    "here is nearest-neighbour, so this should be impossible "
                    "and is a bug in this plugin"
                    % (view, animation.name, len(escaped),
                       "" if len(escaped) == 1 else "s", escaped[:3]))
            anchor = rig_module.anchor_of(rig)
            clip = pack_module.Clip(
                animation.name, frames, animation.fps, animation.loop,
                direction=plan.name if len(direction_plans) > 1 else None,
                loop_start=animation.loop_start, loop_end=animation.loop_end,
                anchor=(anchor[0] + margin, anchor[1] + margin),
                fidelity=plan.fidelity, note=animation.note)
            clips.append(clip)
            raw.append(frames)
    return clips, margin, repairs


def stabilise_clips(clips, padding=0):
    """Crop each clip's frames to that clip's own box, keeping the anchor exact.

    Per clip rather than across the whole sheet. Cropping every animation to one
    box would make the idle frames as large as the death rotation, which on a
    small character more than doubles the texture for nothing.

    What must NOT vary is the anchor, and it does not: every clip is rendered on
    the same margined canvas from the same rig, so the anchor starts at the same
    place in all of them, and each clip's crop simply records where that point
    ended up. The packer then aligns the cells by anchor rather than by edge, so
    the character does not jump when the game switches animations -- which is the
    property the shared box was there to protect.
    """
    from . import stabilize as stabilize_module

    report = {"clips": {}, "holds": {}}
    for clip in clips:
        frames, box, anchor, clip_report = stabilize_module.stabilise(
            clip.frames, clip.anchor, padding=padding)
        clip.frames = frames
        clip.anchor = anchor
        report["clips"][clip.key] = clip_report
        runs = stabilize_module.duplicate_runs(frames)
        if runs:
            report["holds"][clip.key] = runs
        distinct = stabilize_module.distinct_frames(frames, clip.loop)
        report["clips"][clip.key]["distinct"] = distinct
        wanted = len(frames) - (0 if clip.loop else 1)
        if wanted > 1 and distinct < wanted:
            report.setdefault("repeats", {})[clip.key] = [distinct, len(frames)]
    return report


def build_sheet(reference_path, outdir, animations=("full",), direction_set="1",
                backend="template", model="claude-opus-5", character_class="auto",
                facing="right", intent="", name=None, layout="grid", padding=1,
                extrude=1, scale=1, power_of_two=False, engines=("all",),
                front=None, back=None, tolerance=12, native=True,
                custom_animations=None, preview_scale=None, kind="character",
                compress=False, repair=True, frames=None,
                frame_size=None, fps=None, loop_start=None, loop_end=None,
                attach=None):
    """The whole pipeline. Returns a Build."""
    build = Build()
    os.makedirs(outdir, exist_ok=True)
    name = name or os.path.splitext(os.path.basename(reference_path))[0]

    build.references = load_references(
        {"side": reference_path, "front": front, "back": back},
        tolerance=tolerance, native=native)
    # Every image a pixel of this sheet is allowed to have come from, recorded
    # with the parameters it was actually read at. `--tolerance 2` keys a
    # different set of pixels than the default and therefore locks a different
    # palette, so a verifier that re-ingests at the default is checking against
    # a palette this build never used.
    build.sources = [
        {"view": view, "path": os.path.abspath(path),
         "sha256": atlas_module.digest(path),
         "tolerance": int(tolerance), "native": bool(native)}
        for view, path in (("side", reference_path), ("front", front),
                           ("back", back)) if path]
    build.report["references"] = {view: reference.summary()
                                  for view, reference in build.references.items()}

    engine = (backend if not isinstance(backend, str)
              else vision_module.make_backend(backend, os.path.join(outdir, ".work"),
                                              model=model))
    if kind == "prop" and character_class == "auto":
        character_class = "prop"
    build.rigs, build.cutouts = build_rigs(
        build.references, engine, character_class, facing, intent, build)
    if attach:
        outfit_source = os.path.join(outdir, "%s.source.png" % name)
        build.references, build.rigs, build.cutouts = outfit_views(
            build.references, build.rigs, attach, tolerance, native,
            outfit_source, build)
        build.written["source"] = outfit_source
        # Everything downstream -- the palette lock, the REST check, the
        # verifier's reference -- now means the composed art, which is the
        # art that was actually rigged and is the honest thing to check. The
        # items keep their own entries: the composed image contains their
        # colours, but naming them says where those colours came from.
        reference_path = outfit_source
        build.sources = [entry for entry in build.sources if entry["view"] != "side"]
        build.sources.insert(0, {"view": "side", "path": os.path.abspath(outfit_source),
                                 "sha256": atlas_module.digest(outfit_source),
                                 "tolerance": int(tolerance), "native": False})
        for entry in attach:
            build.sources.append(
                {"view": "item", "path": os.path.abspath(entry["path"]),
                 "sha256": atlas_module.digest(entry["path"]),
                 "tolerance": int(tolerance), "native": bool(native)})
    build.report["rig"] = {view: rig.to_dict() for view, rig in build.rigs.items()}
    build.report["rig_actor"] = engine.actor

    if kind == "prop":
        from . import props as props_module
        chosen = props_module.resolve(animations)
    else:
        chosen = motion_module.resolve(animations)
    if custom_animations:
        chosen = list(chosen) + list(custom_animations)
    if not chosen:
        raise ValueError("no animations selected")
    if frames:
        if not 2 <= int(frames) <= 64:
            raise ValueError("--frames must be between 2 and 64, not %r" % frames)
        chosen = [animation.resampled(frames) for animation in chosen]
    if fps or loop_start is not None or loop_end is not None:
        import copy as _copy
        retimed = []
        for animation in chosen:
            clone = _copy.deepcopy(animation)
            if fps:
                if not 0 < float(fps) <= 120:
                    raise ValueError("--fps must be above 0 and at most 120, "
                                     "not %r" % fps)
                clone.fps = float(fps)
            if loop_start is not None:
                clone.loop_start = int(loop_start)
            if loop_end is not None:
                clone.loop_end = int(loop_end)
            problems = motion_module.validate_animation(clone.to_dict())
            if problems:
                raise ValueError("%s: %s" % (clone.name, "; ".join(problems)))
            retimed.append(clone)
        chosen = retimed

    # Advisory, not fatal: these clips build and ship. Every one of them was
    # found in this plugin's own library first, which is the argument for
    # saying them out loud rather than trusting the author.
    for animation in chosen:
        for note in motion_module.cautions(animation.to_dict()):
            build.warn("%s: %s" % (animation.name, note))

    side_rig = build.rigs["side"]
    drivable = [animation for animation in chosen if animation.drives(side_rig)]
    for animation in chosen:
        if animation not in drivable:
            build.warn("%s was not written: it moves %s, and this subject has "
                       "no such part. Tag one in the rig file, or pick a "
                       "different animation"
                       % (animation.name,
                          " or ".join(_plain(selector)
                                      for selector in animation.missing(side_rig))))
    if not drivable:
        raise ValueError(
            "none of the chosen animations moves anything on this rig: %s"
            % ", ".join(animation.name for animation in chosen))
    chosen = drivable

    plans = directions_module.plan(direction_set, build.references)
    build.report["directions"] = [plan.to_dict() for plan in plans]
    note = directions_module.advice(plans)
    if note:
        build.warn(note)

    locked = union_palette(build.references)
    build.clips, margin, repairs = make_clips(
        build.references, build.rigs, build.cutouts, chosen, plans, locked,
        build, repair=repair)
    build.report["repairs"] = repairs
    build.report["margin"] = margin
    build.report["stabilise"] = stabilise_clips(build.clips)
    from . import stabilize as stabilize_module
    if frame_size:
        if not 8 <= int(frame_size) <= 512:
            raise ValueError("--frame-size must be between 8 and 512, not %r"
                             % frame_size)
        for clip in build.clips:
            clip.frames, clip.anchor = stabilize_module.fit_to_cell(
                clip.frames, clip.anchor, frame_size)
        build.report["frame_size"] = int(frame_size)
    for key, runs in build.report["stabilise"].get("holds", {}).items():
        longest = max(count for _, count in runs)
        if longest >= 3:
            build.warn("%s holds the same frame for %d frames running; the motion "
                       "may be too small for a character this size" % (key, longest))
    shading_only = {animation.name for animation in chosen if animation.palette_only()}
    for key, (distinct, total) in build.report["stabilise"].get("repeats", {}).items():
        if key.split(":")[0] in shading_only:
            continue
        build.warn("%s is %d frames but only %d different pictures; either the "
                   "motion is too small for a character this size, or the cycle "
                   "retraces itself and needs a keyframe the two halves do not "
                   "share" % (key, total, distinct))

    reference_pixels = build.references["side"].pixels
    build.report["shed"] = {}
    for clip in build.clips:
        worst, index = quality_module.shed(clip.frames, reference_pixels)
        build.report["shed"][clip.key] = {"worst": round(worst, 4), "frame": index}
        if worst >= 0.05:
            build.warn("%s frame %d sheds %.0f%% of the character into pixels "
                       "detached from its body; the motion is more than this "
                       "drawing can take at its size"
                       % (clip.key, index, worst * 100))

    build.sheet = pack_module.pack(build.clips, layout=layout, padding=padding,
                                   extrude=extrude, power_of_two=power_of_two,
                                   scale=scale)
    build.written = atlas_module.write(
        build.sheet, outdir, name, engines=engines, clips=build.sheet.clips,
        reference_report=build.report["references"]["side"], compress=compress,
        sources=build.sources)

    rig_path = os.path.join(outdir, "%s.rig.json" % name)
    build.rigs["side"].save(rig_path)
    build.written["rig"] = rig_path
    if attach:
        # `atlas.write` returns a fresh dict, so the composed source has to be
        # put back. It is worth reporting: it is the art that was actually
        # rigged, and the art the verifier checks the palette against.
        build.written["source"] = outfit_source

    build.previews = preview_module.write_all(
        build.sheet.clips, os.path.join(outdir, "preview"),
        scale=preview_scale or max(1, min(6, 96 // max(1, build.sheet.cell[1]
                                                       if build.sheet.cell else 32))))
    build.verification = verify_module.verify_directory(
        outdir, name=name, reference_path=reference_path, rig_path=rig_path)
    build.report["name"] = name
    build.report["sheet"] = {"size": list(build.sheet.size),
                             "layout": layout,
                             "cell": list(build.sheet.cell) if build.sheet.cell else None,
                             "clips": len(build.clips),
                             "frames": len(build.sheet.placements)}
    return build
