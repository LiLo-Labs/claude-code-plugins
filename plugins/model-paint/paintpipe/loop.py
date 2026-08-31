"""Paint it, look at it, fix it. Repeat. That is the whole method.

Everything before this asked QUESTIONS: what parts does this have, where is
each one, is this candidate the right size. Three separate interrogations,
sixty-nine calls on one shell, and not one of them ever showed the agent a
painted model. A person does not work that way. A person paints, looks at what
they painted, and fixes what is wrong -- and the consequence of every action is
visible immediately, which is what makes the next action easy.

So there is ONE question here, asked of one picture, over and over:

    here is the model painted -- what is each colour, and what is wrong?

The answer does two things at once. It NAMES the colours, which is the
identification step, free. And it lists corrections as places -- "the rock at
this spot should be colour 3", "colour 2 has spilled onto the shell here" --
which are edits, applied directly to the field. Then it is painted again and
shown again.

Three properties follow, and each removes machinery rather than adding it:

    The first painting needs no vision at all. Cut the merge tree into a
    handful of big nodes by area; that is a partition of the whole surface
    with nothing left over. It will be wrong, and being wrong is fine, because
    round two sees it and says so.

    Nothing is ever unclaimed. Every face starts in some part, so there is no
    "18.8% of the surface was found" -- the question is only whether the
    boundaries are in the right places, which is exactly what looking at the
    render answers.

    There is no sizing question. "How big is this part" is never asked in the
    abstract; it is answered by looking at whether the colour covers the thing
    in the picture, which is the same way a person answers it.

That last property took three tries to actually honour, because "paint here"
still had to mean SOME amount of surface, and every fixed answer was wrong:

    the ancestor at 8x the clicked area gave one colour 82% of the shell;
    the persistence object -- median 0.0005% of the surface -- left every
    part a few percent and the base coat holding 83.7%.

Both picked an extent in the abstract, which is the very thing the loop was
supposed to stop doing. So a click is no longer a patch at all. It is a CLAIM,
and `claim()` hands every base region on the model to whichever claim it is
most continuous with, measured by the border strength at which the two finally
merge in the model's own tree. A part's extent is then decided by where the
OTHER parts were pointed at -- the shell reaches exactly as far as the nearest
barnacle click lets it -- which is how a person decides it too, and it needs no
constant, no size, and no question about how big anything is.
"""

import json
import os

import numpy as np

from . import rig as rig_module


DISTINCT = [(0.85, 0.33, 0.20), (0.20, 0.45, 0.80), (0.95, 0.76, 0.16),
            (0.25, 0.62, 0.35), (0.62, 0.34, 0.68), (0.40, 0.78, 0.80),
            (0.90, 0.55, 0.75), (0.45, 0.35, 0.22), (0.60, 0.80, 0.30),
            (0.15, 0.28, 0.45), (0.98, 0.62, 0.35), (0.55, 0.58, 0.62)]


def palette(count):
    out = []
    for index in range(max(count, 1)):
        base = np.asarray(DISTINCT[index % len(DISTINCT)])
        # Past twelve, darken then lighten rather than repeat a colour exactly.
        wrap = index // len(DISTINCT)
        if wrap:
            base = np.clip(base * (0.68 if wrap % 2 else 1.28), 0.05, 1.0)
        out.append(base)
    return np.asarray(out)


def look_from(mesh, tree, up, views=3, pixels=520, log=None):
    """The directions to work from: chosen by what they see, not by an orbit.

    An orbit at a fixed elevation looks wherever the model happens to be
    pointing. On the shell that spent an entire view of three on the flat open
    top -- a face with nothing on it -- and never once showed the back, so a
    third of every picture was blank and a third of the model was painted
    without ever being seen. No amount of looking harder at the right-hand
    image recovers a surface no camera was aimed at.

    plan_poses scouts cheaply from many directions and greedily takes the one
    that most reduces the surface still short of looks. It stops when the
    model is covered, so a plain model buys few views and a self-occluding one
    buys more -- which is what a person does when they turn a thing over.
    """
    directions, _covered, _areas = rig_module.plan_poses(
        mesh, tree, up, pixels=pixels, target_views=2,
        budget=max(2, int(views)), log=log)
    if not directions:                      # a scout that saw nothing at all
        from . import preview
        directions = preview.orbit(max(2, int(views)), 26.0, up=up)
    return list(directions)


def show(mesh, up, field, labels, out_dir, tag, views=3, pixels=520,
         directions=None):
    """Plain beside painted, same views, numbered. The only picture ever asked about.

    `directions` must be the SAME on every call of a run: the agent points at
    pixels, and a pixel only means a place while the camera stays put.
    """
    from PIL import Image, ImageDraw
    from . import preview

    os.makedirs(out_dir, exist_ok=True)
    if directions is None:
        directions = preview.orbit(views, 26.0, up=up)
    poses = rig_module.poses_from(mesh, directions, up, pixels=pixels)
    colours = palette(len(labels))

    panels = []
    for pose in poses:
        shaded = rig_module.light(pose, "studio")
        visible, hit = pose.visible, pose.hit_id
        plain = np.full((pixels, pixels, 3), 0.97)
        plain[visible] = np.clip(shaded, 0, 1)[visible, None]
        painted = plain.copy()
        who = np.full((pixels, pixels), -1, dtype=np.int64)
        who[visible] = field[hit[visible]]
        for slot in range(len(labels)):
            mask = who == slot
            if not mask.any():
                continue
            shade = np.clip(shaded, 0, 1)[mask][:, None]
            painted[mask] = np.clip(colours[slot] * (0.42 + 0.72 * shade), 0, 1)
        panels.append((plain, painted))

    # WRAP INTO ROWS. Six views in a line is a 6296 x 554 strip, and a picture
    # with an aspect ratio of eleven to one is not a picture anyone can read --
    # every panel arrives a few dozen pixels tall once it is fitted to a page.
    # Covering the model properly needs six looks, so the sheet has to be a
    # sheet.
    gap, caption = 8, 18
    columns = max(1, min(len(panels), 3))
    rows = (len(panels) + columns - 1) // columns
    cell = 2 * pixels + gap
    sheet = Image.new("RGB", (columns * cell + gap,
                              rows * (pixels + caption + gap) + gap),
                      (247, 246, 244))
    draw = ImageDraw.Draw(sheet)
    for index, (plain, painted) in enumerate(panels):
        x0 = gap + (index % columns) * cell
        y0 = gap + (index // columns) * (pixels + caption + gap)
        sheet.paste(Image.fromarray((plain * 255).astype(np.uint8)), (x0, y0))
        sheet.paste(Image.fromarray((painted * 255).astype(np.uint8)),
                    (x0 + pixels, y0))
        draw.text((x0 + 4, y0 + pixels + 3), "view %d" % index,
                  fill=(20, 20, 20))
    path = os.path.join(out_dir, "state-%s.png" % tag)
    sheet.save(path)
    return path, poses, (pixels, gap, columns)


def panel_point(geometry, views, view, x, y):
    """A coordinate given on the sheet -> the pixel inside that view's panel.

    The sheet lays pairs out in a grid, so view v sits at column v%columns and
    row v//columns, and its painted panel starts one panel width into the
    cell. Subtracting one panel width and nothing else is right for view 0 and
    wrong for every view after it, which once threw away half of every round's
    corrections in silence; a coordinate given in the plain panel, or already
    panel-local, is recovered here instead of being lost.
    """
    pixels, gap = geometry[0], geometry[1]
    columns = geometry[2] if len(geometry) > 2 else max(1, views)
    if not (0 <= view < views):
        return None
    cell = 2 * pixels + gap
    left = gap + (view % max(1, columns)) * cell
    top = gap + (view // max(1, columns)) * (pixels + 18 + gap)
    local_x, local_y = x - (left + pixels), y - top
    if not (0 <= local_x < pixels):
        local_x = x - left if 0 <= x - left < pixels else x % pixels
    if not (0 <= local_y < pixels):
        local_y = y % pixels
    return int(local_x), int(local_y)


def seed_regions(tree, poses, geometry, points):
    """Pointed-at places -> base regions. One click is one region, nothing grown."""
    base = rig_module.region_of_face(tree)
    out = []
    for point in points:
        try:
            view = int(point["view"])
            x, y = int(point["x"]), int(point["y"])
        except (KeyError, TypeError, ValueError):
            continue
        local = panel_point(geometry, len(poses), view, x, y)
        if local is None:
            continue
        region = rig_module.point_to_region(poses[view], base, local[0],
                                            local[1])
        if region >= 0:
            out.append(int(region))
    return out


def stroke_regions(tree, poses, geometry, shapes, width=1, agree=False):
    """A line drawn ALONG a part -> the base regions it actually runs over.

    For a crack, a rib cord, a weed strand or a scattered crust, an outline is
    the wrong instrument. A crack is a few pixels wide, so any loop that can be
    drawn around a set of fracture lines is mostly the smooth shell between
    them -- and a majority rule then takes all of it. Measured on the shell,
    "cracks and chips" and "broken shell edges" drawn as outlines took large
    blotches out of the middle of the shell body.

    A stroke takes only what it runs over. The substrate was refined until a
    crack has base regions of its own, so a line down the crack picks up those
    regions and stops; the width is in PIXELS of the render, a brush thickness
    rather than a fact about the model, and the region boundaries decide the
    actual edge as always.

    One pixel wide, not three. A crack region is narrow and the smooth shell
    either side of it is one big region, so a brush reaching a pixel past the
    line takes that whole neighbour -- a fine instrument has to actually be
    fine, or it is the outline again with extra steps.
    """
    base = rig_module.region_of_face(tree)
    regions = int(tree["regions"])
    reach = max(0, int(width) // 2)
    marked = {}                        # region -> the views that marked it
    drawn_views = set()
    visible_cache = {}

    def seen_in(view, region):
        """Can this view see this region at all? Cached; only drawn views are
        ever asked, so the cost is one pass per view the agent drew on."""
        table = visible_cache.get(view)
        if table is None:
            pose = poses[view]
            table = np.zeros(regions, dtype=bool)
            if pose.visible.any():
                found, counts = np.unique(base[pose.hit_id[pose.visible]],
                                          return_counts=True)
                table[found[counts >= 4]] = True
            visible_cache[view] = table
        return bool(table[region])

    for shape in shapes or []:
        try:
            view = int(shape["view"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= view < len(poses)):
            continue
        corners = []
        for point in shape.get("points") or []:
            try:
                local = panel_point(geometry, len(poses), view,
                                    int(point["x"]), int(point["y"]))
            except (KeyError, TypeError, ValueError):
                continue
            if local is not None:
                corners.append(local)
        # A LINE IS NOT A LOOP. Wrapping the last corner back to the first
        # adds a closing segment running from the end of the stroke straight
        # back to its start, painting a chord across everything between --
        # which is how a brush drawn along a crack streaked over the middle of
        # the shell. An open stroke stops where it stops. The segments between
        # the given corners are still walked, because a stroke is a line and
        # not a row of dots.
        here = set()
        for index in range(max(1, len(corners) - 1)):
            x0, y0 = corners[index]
            x1, y1 = corners[index + 1] if index + 1 < len(corners) \
                else (x0, y0)
            steps = max(abs(x1 - x0), abs(y1 - y0), 1)
            for tick in range(steps + 1):
                x = int(round(x0 + (x1 - x0) * tick / steps))
                y = int(round(y0 + (y1 - y0) * tick / steps))
                for dy in range(-reach, reach + 1):
                    for dx in range(-reach, reach + 1):
                        region = rig_module.point_to_region(poses[view], base,
                                                            x + dx, y + dy)
                        if region >= 0:
                            here.add(int(region))
        drawn_views.add(view)
        for region in here:
            marked.setdefault(region, set()).add(view)

    # CORROBORATION IS OFF BY DEFAULT HERE, and that is a measurement rather
    # than a preference. Demanding that a second view mark the SAME base
    # region tests whether two lines drawn from different angles land on the
    # same few pixels of surface, which is a far harder thing than being
    # right: on the shell it left 28 strokes along the ribs holding 43
    # regions, and the fine brush stopped painting anything.
    #
    # The check belongs where a mistake is large and corroboration is cheap,
    # which is an outline -- it claims an area, so a second view has plenty of
    # surface to agree about. A stroke is one pixel wide and stops at the
    # region boundaries it crosses, so it is self-limiting; its real failure
    # was the closing segment that ran back across the model, and that is
    # fixed. What multiple views buy a stroke is COVERAGE of the part from
    # every side, not a veto.
    if not agree:
        return np.asarray(sorted(marked), dtype=np.int64)
    out = []
    for region, views_hit in marked.items():
        if len(views_hit) >= 2:
            out.append(region)
            continue
        elsewhere = sum(1 for view in drawn_views
                        if view not in views_hit and seen_in(view, region))
        if elsewhere == 0:
            out.append(region)
    return np.asarray(sorted(out), dtype=np.int64)


def outline_regions(tree, poses, geometry, shapes, share=0.5, min_pixels=4):
    """An outline drawn round a part in the picture -> the base regions it means.

    This is the one source of the part's extent that nothing has used. The
    merge tree does not contain the part -- measured on the shell, the chain
    above a rib seed goes 0.132% to 33.989% of the surface with nothing in
    between, so the ribs are not a node and no way of choosing among nodes can
    produce them. Nor does any rule for filling between scribble marks: every
    one tried drew bands or confetti, because between the marks it is guessing.

    The render is not guessing. A rib is a continuous shape in the picture,
    and the depth buffer already says which face each pixel belongs to. So the
    agent draws round the part, and a base region joins it when most of the
    region's visible pixels -- counted across every view that can see it, not
    just the one drawn on -- fall inside. Vision decides WHICH surface;
    the region boundaries decide where the edge actually falls, so the result
    can only ever have edges the geometry itself drew.
    """
    from PIL import Image, ImageDraw

    base = rig_module.region_of_face(tree)
    regions = int(tree["regions"])
    pixels = geometry[0]
    inside = np.zeros(regions, dtype=np.int64)
    seen = np.zeros(regions, dtype=np.int64)

    by_view = {}
    for shape in shapes or []:
        try:
            view = int(shape["view"])
        except (KeyError, TypeError, ValueError):
            continue
        corners = []
        for point in shape.get("points") or []:
            try:
                local = panel_point(geometry, len(poses), view,
                                    int(point["x"]), int(point["y"]))
            except (KeyError, TypeError, ValueError):
                continue
            if local is not None:
                corners.append(local)
        if len(corners) >= 3:
            by_view.setdefault(view, []).append(corners)

    for view, pose in enumerate(poses):
        # ONLY THE VIEWS DRAWN ON. Counting a region's visible pixels across
        # every view, while counting "inside" only where an outline exists,
        # judges the drawing against views the agent never drew on: with six
        # views a region outlined in one reaches a sixth and can never make a
        # majority. The question is whether most of what was VISIBLE TO THE
        # DRAWING fell inside it.
        if view not in by_view:
            continue
        visible = pose.visible
        if not visible.any():
            continue
        here = base[pose.hit_id[visible]]
        seen += np.bincount(here, minlength=regions)
        canvas = Image.new("L", (pixels, pixels), 0)
        draw = ImageDraw.Draw(canvas)
        for corners in by_view[view]:
            draw.polygon(corners, fill=1)
        drawn = np.asarray(canvas, dtype=bool) & visible
        if not drawn.any():
            continue
        inside += np.bincount(base[pose.hit_id[drawn]], minlength=regions)

    # A region only clipped by the edge of an outline is not in the part. The
    # share is a majority of what the cameras can see of it, which is a
    # statement about the drawing rather than a size or a scale.
    #
    # But a majority of THREE PIXELS is not evidence. A region turned almost
    # edge-on, or tucked behind something, shows a handful of pixels in the
    # drawn views, and if the outline happens to cover them it is claimed on
    # nothing at all -- measured, the shell's spiral eye went from 742 regions
    # to 3555 in one round while barely changing on screen, because the extra
    # three thousand were surfaces the drawing could hardly see. A region has
    # to be properly visible somewhere before a drawing gets to decide it.
    #
    # FOUR PIXELS, which is the number rig.coverage already uses to decide
    # whether a pose sees a region at all -- one calibrated constant for that
    # judgement rather than two. Measured on the shell across six views: the
    # median region gets 42 pixels and a floor of four rejects 3.5% of them.
    # The count here is only over the views DRAWN ON, though, so with two
    # views drawn the same median is nearer fourteen and a floor of twelve
    # threw away about half of what the agent could plainly see.
    keep = (seen >= int(min_pixels)) & (inside >= share * seen)
    return np.flatnonzero(keep).astype(np.int64)


def settle(tree, seeds, count, fallback=0):
    """What each part was given, laid down in paint order. No guessing.

    Every earlier version of this filled the gaps between what the agent
    marked -- by climbing the tree, by shortest path over the borders, by
    matching the surface signature, by letting each part reach as far as its
    own marks are apart. All four drew bands or confetti, for one reason: in
    the gap they were guessing, and the guess had to come from somewhere the
    part's identity does not live. So nothing fills gaps any more. A part gets
    the surface it was drawn round, later parts land on top of earlier ones
    because that is what paint order means, and whatever nobody claimed stays
    the base coat, where it is visible in the render and can be drawn round
    next round.
    """
    regions = int(tree["regions"])
    owner = np.full(regions, -1, dtype=np.int64)
    for label in sorted(seeds):
        if not (0 <= int(label) < count):
            continue
        want = np.asarray(seeds[label], dtype=np.int64).ravel()
        want = want[(want >= 0) & (want < regions)]
        owner[want] = int(label)
    if fallback is not None:
        owner[owner < 0] = int(fallback)
    return owner


def field_of(tree, owner, face_count):
    """Base-region owners -> per-face labels."""
    base = rig_module.region_of_face(tree)
    field = np.full(face_count, -1, dtype=np.int64)
    inside = base < len(owner)
    field[inside] = owner[base[inside]]
    return field

def survey_views(mesh, up, out_dir, directions, pixels=760, log=None):
    """Plain shaded views of the whole piece, as ONE sheet.

    Handing the agent N separate files makes it open N files, and measured
    here that turned a question answering in a couple of minutes into one that
    had not returned in fifteen. The views are the same views; they just
    arrive as a single picture.
    """
    os.makedirs(out_dir, exist_ok=True)
    poses = rig_module.poses_from(mesh, directions, up, pixels=pixels)
    paths, images = [], []
    for index, pose in enumerate(poses):
        image = rig_module.light(pose, "studio")
        path = os.path.join(out_dir, "look-%d.png" % index)
        rig_module.write_png(image, pose.visible, path)
        paths.append(path)
        canvas = np.full(image.shape, 0.97)
        canvas[pose.visible] = image[pose.visible]
        images.append(canvas)
    sheet = os.path.join(out_dir, "views.png")
    rig_module.sheet(images, ["view %d" % i for i in range(len(images))],
                     sheet, columns=min(len(images), 3))
    if log:
        log("  %d plain views for identification, as one sheet" % len(paths))
    return sheet, paths, poses


SEE = """This picture shows %(count)d views of the same 3D model, plainly shaded.

The piece: %(intent)s

Answer as a painter about to paint it:

1. WHAT PARTS do you see? Name the things you would give their own colour.

2. HOW MUCH DETAIL does each part have? Say "flat" if the whole part takes one
   colour, or "detailed" if it is really many separate things of the same kind
   (a field of barnacles, a row of spikes) that might want picking out.

3. IN WHAT ORDER would you paint them? Background and large areas first,
   details and small things last, because later coats go ON TOP of earlier
   ones. Number them from 1.

Overlap is expected and is handled by that order, so do not worry about parts
touching or sitting on each other -- just say which goes on first.

Reply with ONLY a JSON object, no prose:
{"parts": [{"name": "<short name>", "detail": "flat|detailed",
            "order": <int>, "where": "<where it sits>"}, ...]}"""


BRUSH = """The LEFT image of each pair is a 3D model plainly shaded, %(count)d views.
The RIGHT image of each pair is the painting as it stands right now.

The piece: %(intent)s

You are painting ONE thing: %(name)s -- %(where)s
It is %(swatch)s. %(state)s

The views are six looks at the SAME object from different sides, so a piece of
it usually appears in several of them. Where those views agree is where the
part really is on the object; a mark made in only one view is a guess about
everything the other views can see.

Look at the right-hand images and answer for that colour only:

1. WHAT IS STILL MISSING. Take %(bite)s -- not every piece at once -- and for
   each one you take, MARK IT IN EVERY VIEW THAT SHOWS IT, before moving on.
   The same piece of the object, marked from each side that can see it.

   %(how)s

2. WHAT SHOULD NOT BE THIS COLOUR. Give the colour back wherever it has gone
   somewhere it should not be. A single spot can be a point; a whole area that
   was taken wrongly should be drawn round, the same way you drew it on. It
   all goes back to whatever it was before.

You will see the result and be asked again, many times, so take a little and
take it accurately. Doing a few pieces properly from every side beats doing
all of them from one. If the colour now covers this part and nothing else,
reply with both lists empty. That is how this finishes.

Reply with ONLY a JSON object, no prose:
{"add": [{"view": <int>, "points": [{"x": <int>, "y": <int>}, ...]}, ...],
 "remove": [{"view": <int>, "x": <int>, "y": <int>}, ...
            or {"view": <int>, "points": [{"x": <int>, "y": <int>}, ...]}]}"""


# A broad brush fills an area; a fine one lines in a detail. Which instrument
# the agent is handed is the one thing the SEE step's "flat or detailed"
# answer decides, and it is the difference between a crack being a crack and a
# crack taking the shell it runs across.
FILL = """Draw round each piece of this part that has not got the colour
   yet -- a closed outline, a list of pixel corners going round the piece and
   back to the start, in the RIGHT-HAND image of a view that shows it. Follow
   the shape: a long piece wants corners down both its sides, not a box round
   it.

   Trace just INSIDE the edge. A surface is taken only when most of the views
   you drew on agree it is inside, so cutting a little short costs nothing,
   while spilling over paints the neighbour -- and a piece drawn in three
   views is held to what those three agree on."""

LINE = """Draw a LINE ALONG each piece of this part that has not got the
   colour yet -- a run of pixel corners following it from one end to the
   other, in the RIGHT-HAND image of a view that shows it. This is a fine
   brush: only what the line runs over is painted, so stay on the thing
   itself. For a field of many small things, one short line on each of them.

   Do NOT draw a loop enclosing several of them. A crack is a few pixels wide,
   so anything drawn around a set of cracks is mostly the surface between
   them, and that surface would be painted too."""


def see(backend, mesh, up, intent, out_dir, views=4, pixels=700,
        directions=None, log=print):
    """What parts, how much detail each, and in what order to paint them."""
    from . import preview
    if directions is None:
        directions = preview.orbit(views, 28.0, up=up)
    sheet, paths, poses = survey_views(mesh, up, out_dir, directions,
                                       pixels=pixels, log=None)
    prompt = SEE % {"count": len(paths), "intent": intent or "a 3D model"}
    with open(sheet, "rb") as handle:
        key = "see-%s" % rig_module.digest(handle.read(), prompt)
    answer = backend._run([sheet], prompt, key)
    parts = []
    for entry in (answer or {}).get("parts", []) or []:
        name = str(entry.get("name", "")).strip()
        if not name:
            continue
        try:
            order = int(entry.get("order", 99))
        except (TypeError, ValueError):
            order = 99
        parts.append({"name": name, "where": str(entry.get("where", "")),
                      "detail": str(entry.get("detail", "flat")).lower(),
                      "order": order})
    parts.sort(key=lambda p: p["order"])
    if log:
        for part in parts:
            log("    %2d. %-32s [%s] %s" % (part["order"], part["name"],
                                            part["detail"],
                                            part["where"][:44]))
    return parts


def add_part(backend, mesh, tree, up, seeds, labels, part, intent, out_dir,
             tag, rounds=6, views=3, directions=None, log=print):
    """Paint ONE colour, looking after every stroke, until that colour is right.

    The looking is not an audit at the end. It happens after each application,
    on the one colour being laid, and that is what makes the application itself
    unimportant: a stroke that covered half the part is seen to have covered
    half the part, and the next one covers the rest. Nothing has to land
    correctly the first time.

    Which is why there is no longer any machinery trying to make it land
    correctly. Four rules for deciding how far one mark should spread were
    built and measured -- climbing the merge tree, shortest path over the
    border graph, matching the surface signature, and letting a part reach as
    far as its own marks are apart -- and all four drew bands or confetti,
    because each was guessing in the gap between marks. The gap does not need
    guessing at. It needs another look.

    So one question is asked over and over of one colour: what has it not
    covered yet, and what is it covering that it should not? An empty answer
    to both is the finish.

    Returns (seeds, labels, field, rounds_used).
    """
    slot = len(labels)
    labels.append(part["name"])
    count = len(labels)
    # What the surface was before this colour existed, so "remove" can put a
    # patch back where it came from rather than handing it to colour 1 -- on
    # the shell that was the rock base, so "this has spread onto the shell"
    # turned shell into rock.
    before = settle(tree, seeds, count) if seeds else None
    seeds.setdefault(slot, [])

    used = 0
    for step in range(max(1, int(rounds))):
        # NO BASE COAT WHILE WORKING. Filling the unclaimed surface with the
        # first colour makes that colour cover the whole model from the very
        # first look, so the agent cannot tell what it has actually painted
        # from what merely defaulted -- and its corrections then point at
        # surface no stroke ever claimed, which retraction cannot touch.
        # Measured: 25 removals on the rocky base changed nothing at all.
        # Unclaimed has to LOOK unclaimed, or the feedback is not feedback.
        owner = settle(tree, seeds, count, fallback=None)
        field = field_of(tree, owner, len(mesh.faces))
        path, poses, geometry = show(mesh, up, field, labels, out_dir,
                                     "%s-%d" % (tag, step), views=views,
                                     directions=directions)
        state = ("Nothing has that colour yet." if not seeds[slot] else
                 "What has it so far is shown in that colour.")
        fine = str(part.get("detail", "flat")).lower() == "detailed"
        prompt = BRUSH % {"count": len(poses), "name": part["name"],
                          "where": part["where"], "state": state,
                          "how": LINE if fine else FILL,
                          "bite": ("three or four of them" if fine
                                   else "one or two pieces"),
                          "swatch": "colour %d" % (slot + 1),
                          "intent": intent or "a 3D model"}
        with open(path, "rb") as handle:
            key = "brush-%s" % rig_module.digest(handle.read(),
                                                 "%s|%d" % (part["name"], step))
        answer = backend._run([path], prompt, key)
        if answer is None:
            break
        used += 1

        add = answer.get("add") or []
        remove = answer.get("remove") or []
        if fine:
            drawn = set(int(r) for r in
                        stroke_regions(tree, poses, geometry, add))
        else:
            drawn = set(int(r) for r in
                        outline_regions(tree, poses, geometry, add))
            # A loop drawn so thin it encloses a majority of nothing still
            # says where the part is, so its own corners count as marks.
            # `len(...) == 0`, never `not drawn`: on a numpy array that raises
            # for more than one element, and for exactly one it tests whether
            # that element is ZERO -- so a part whose only claim was region 0
            # would quietly get the fine brush run over it as well.
            if add and len(drawn) == 0:
                drawn = set(int(r) for r in
                            stroke_regions(tree, poses, geometry, add))
        if drawn:
            seeds[slot] = sorted(set(seeds[slot]) | drawn)
        # UNDO HAS TO BE AS STRONG AS THE STROKE. One outline can take
        # thousands of regions in a gesture, and a removal used to be a single
        # point: on the shell the agent saw its spiral-eye colour cover the
        # whole coil, asked for seventeen removals, and took back six regions
        # of three thousand. Seeing the mistake is worthless if the correction
        # cannot reach it, so a removal may be drawn round exactly as the
        # paint was.
        taken = set(seed_regions(tree, poses, geometry,
                                 [f for f in remove if "x" in f]))
        areas = [f for f in remove if f.get("points")]
        if areas:
            taken |= set(int(r) for r in
                         outline_regions(tree, poses, geometry, areas))
            taken |= set(int(r) for r in
                         stroke_regions(tree, poses, geometry, areas))
        for region in taken:
            # RETRACT FIRST. Re-asserting the displaced claim while this
            # part's own mark is still there is not undo: both hold the
            # region and the later one wins, so nothing changes.
            seeds[slot] = [r for r in seeds[slot] if r != region]
            prior = int(before[region]) if before is not None else -1
            if prior >= 0 and prior != slot:
                seeds[prior] = sorted(set(seeds.get(prior, [])) | {region})
        if log:
            log("    %-30s round %d: %d outline(s), %d removal(s) -> %d region(s)"
                % (part["name"], step, len(add), len(remove),
                   len(seeds[slot])))
        if not add and not remove:
            break

    if not seeds[slot]:
        if log:
            log("    %s: never found; no colour spent on it" % part["name"])
        seeds.pop(slot, None)
        labels.pop()
        count = len(labels)
    owner = settle(tree, seeds, count, fallback=None)
    return seeds, labels, field_of(tree, owner, len(mesh.faces)), used



REVIEW = """The LEFT image of each pair is a 3D model plainly shaded, %(count)d views.
The RIGHT image of each pair is the finished painting.

The piece: %(intent)s

The colours are:
%(legend)s

Every colour was painted on its own, one at a time, and nobody has yet looked
at the whole thing. Do that now. Stand back and say what is WRONG with the
painting as a painting -- a colour that has spread across something it should
not, two things that ought to be different colours and are not, an area that
belongs to a part but ended up another colour because a later coat took it.

Give the fixes as places, and say which colour each place SHOULD be. Draw
round an area the same way it was painted: a closed outline for a patch, a
line along a thin thing, or a single point for a spot.

Take the worst few. You will be asked again after these are applied.

Reply with ONLY a JSON object, no prose:
{"fixes": [{"colour": <the colour number it should be>,
            "view": <int>,
            "points": [{"x": <int>, "y": <int>}, ...] or "x"/"y" for a point,
            "why": "<short>"}, ...]}
An empty list means the painting is right."""


def review(backend, mesh, tree, up, seeds, labels, intent, out_dir,
           directions, rounds=3, views=3, log=print):
    """Look at the WHOLE painting and fix it. The question nobody was asked.

    Every part is painted on its own, and each of those calls can be perfectly
    right about its own colour while the picture goes to pieces -- because it
    is asked "what is missing from THIS colour", never "is this any good".
    Worse, a part's turn ends and never comes back, so when a later coat eats
    into an earlier one there is no one left who is allowed to say so: by the
    time the ribs are being painted, the body's turn is three parts gone.

    This is that missing pass. It sees the finished thing, it may move any
    surface to any colour, and it runs until it says the painting is right.
    """
    for step in range(max(1, int(rounds))):
        owner = settle(tree, seeds, len(labels), fallback=0)
        field = field_of(tree, owner, len(mesh.faces))
        path, poses, geometry = show(mesh, up, field, labels, out_dir,
                                     "review-%d" % step, views=views,
                                     directions=directions)
        legend = "\n".join("  %d: %s" % (i + 1, name)
                            for i, name in enumerate(labels))
        prompt = REVIEW % {"count": len(poses), "legend": legend,
                           "intent": intent or "a 3D model"}
        with open(path, "rb") as handle:
            key = "review-%s" % rig_module.digest(handle.read(), str(step))
        answer = backend._run([path], prompt, key)
        if answer is None:
            break
        fixes = answer.get("fixes") or []
        moved = 0
        for fix in fixes:
            try:
                slot = int(fix["colour"]) - 1
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= slot < len(labels)):
                continue
            if fix.get("points"):
                want = set(int(r) for r in
                           outline_regions(tree, poses, geometry, [fix]))
                want |= set(int(r) for r in
                            stroke_regions(tree, poses, geometry, [fix]))
            else:
                want = set(seed_regions(tree, poses, geometry, [fix]))
            if not want:
                continue
            # A surface can only belong to one part, so giving it to this
            # colour means taking it off whoever holds it. That is the whole
            # point: the earlier colour's turn is over and cannot defend
            # itself, and this pass is what stands in for it.
            for other in list(seeds):
                if other != slot and seeds[other]:
                    seeds[other] = [r for r in seeds[other] if r not in want]
            seeds[slot] = sorted(set(seeds.get(slot, [])) | want)
            moved += len(want)
        if log:
            log("    review %d: %d fix(es), %d region(s) moved"
                % (step, len(fixes), moved))
        if not fixes:
            break
    owner = settle(tree, seeds, len(labels), fallback=0)
    return seeds, field_of(tree, owner, len(mesh.faces))



CHOOSE = """The LEFT image of each pair is a 3D model plainly shaded, %(count)d views.
The RIGHT image of each pair is it painted, one colour per part.

The piece: %(intent)s

The parts, by the colour they are painted in that picture:
%(legend)s

The printer has these filaments loaded, and no others:
%(filaments)s

Say which filament each part should be printed in. Several parts may share a
filament -- that is normal and often right, and a part whose real colour you
have not got is better in the nearest sensible one than in a wrong one.

Judge it as the finished object: what the thing IS, what would read well at
arm's length, and what a painter would do with this many colours. Say briefly
why for each.

Reply with ONLY a JSON object, no prose:
{"choices": [{"part": "<part name, exactly as listed>",
              "filament": "<filament name, exactly as listed>",
              "why": "<short>"}, ...]}"""


def choose_filaments(backend, mesh, up, field, labels, filaments, intent,
                     out_dir, directions, views=3, log=print):
    """Which filament each part is printed in. Asked, not optimised.

    This was a solver that minimised colour distance in Lab against the loaded
    palette. That is the wrong shape of question: which filament a barnacle
    should be is a judgement about the object -- what it is, what reads at
    arm's length, what a painter would do with four colours -- and the nearest
    Lab match to a grey render carries none of it. The agent has just spent
    the whole run looking at this model; it is the thing that knows.

    Returns {part name: filament name}, and falls back to the last filament
    for any part the answer did not cover, because a printer needs an answer
    for every part.
    """
    path, poses, _geometry = show(mesh, up, field, labels, out_dir, "choose",
                                  views=views, directions=directions)
    legend = "\n".join("  colour %d: %s" % (i + 1, name)
                        for i, name in enumerate(labels))
    listing = "\n".join("  %s" % name for name in filaments)
    prompt = CHOOSE % {"count": len(poses), "legend": legend,
                       "filaments": listing, "intent": intent or "a 3D model"}
    with open(path, "rb") as handle:
        key = "choose-%s" % rig_module.digest(handle.read(), listing)
    answer = backend._run([path], prompt, key) or {}

    known = {name.lower(): name for name in filaments}
    chosen = {}
    for entry in answer.get("choices") or []:
        part = str(entry.get("part", "")).strip()
        want = known.get(str(entry.get("filament", "")).strip().lower())
        if part in labels and want:
            chosen[part] = want
            if log:
                log("    %-32s -> %-16s %s"
                    % (part, want, str(entry.get("why", ""))[:40]))
    for name in labels:
        chosen.setdefault(name, filaments[-1])
    return chosen


def paint(backend, mesh, tree, up, intent, out_dir, views=3, rounds=6,
          max_parts=8, log=print):
    """The whole method, in the order a person works.

    See what parts there are and how much detail each has; paint them in the
    order given, background first so later coats land on top; and stay on each
    colour, looking after every stroke, until that colour is right.

    The looking is what makes this work, and it is why there is no cleverness
    anywhere about how far a stroke should spread. A person laying one colour
    sees immediately whether they have covered the thing, and covers the rest
    if they have not. Four different rules for spreading a mark were built and
    measured before that was taken seriously; all four guessed, and all four
    drew bands or confetti. Nothing guesses now. The gap between two strokes
    is not filled in, it is looked at.

    Nothing anywhere sets a size either. A part is whatever surface was drawn
    round in the picture, so the same procedure paints a 4mm barnacle and a
    190mm shell without being told which is which -- the only way it can work
    on a model nobody has seen.
    """
    os.makedirs(out_dir, exist_ok=True)
    # WHERE TO STAND, before anything else. Every later question is asked of
    # these pictures and answered in their pixels, so they are chosen once,
    # by what they can see, and never change for the rest of the run.
    directions = look_from(mesh, tree, up, views=views, log=log)
    parts = see(backend, mesh, up, intent, out_dir, views=len(directions),
                directions=directions, log=log)
    if not parts:
        return None, []

    seeds, labels = {}, []
    field = np.full(len(mesh.faces), -1, dtype=np.int64)
    for index, part in enumerate(parts[:max_parts]):
        seeds, labels, field, _n = add_part(
            backend, mesh, tree, up, seeds, labels, part, intent, out_dir,
            str(index), rounds=rounds, views=len(directions),
            directions=directions, log=log)
    # NOW LOOK AT THE WHOLE THING. Until this pass nobody has: every call was
    # about one colour, asked before the later colours existed, and allowed to
    # change only that colour. A part whose turn has passed cannot complain
    # that a later coat took its surface, so this is where that gets said.
    if labels:
        seeds, field = review(backend, mesh, tree, up, seeds, labels, intent,
                              out_dir, directions, rounds=max(2, rounds // 2),
                              views=len(directions), log=log)
    # THE BASE COAT LAST. Anything nobody drew round is the first part -- a
    # printer cannot lay "no colour" -- but that is a decision about the
    # finished piece, not something to show while there is still painting to
    # do and looking to be done.
    field = field_of(tree, settle(tree, seeds, len(labels), fallback=0),
                     len(mesh.faces))
    show(mesh, up, field, labels, out_dir, "final",
         views=len(directions), directions=directions)
    if log:
        areas = mesh.area_faces
        total = float(areas.sum()) or 1.0
        for slot, name in enumerate(labels):
            log("  %-32s %5.1f%%"
                % (name, 100.0 * float(areas[field == slot].sum()) / total))
        left = 100.0 * float(areas[field < 0].sum()) / total
        if left > 0.05:
            log("  %-32s %5.1f%%" % ("(unclaimed)", left))
    # THE RECORD OF THE RUN. Without the field on disk the only artefact is
    # the 3MF, so re-exporting against different filaments -- or looking at
    # what was actually painted -- means paying for the whole thing again.
    np.save(os.path.join(out_dir, "field.npy"), field)
    with open(os.path.join(out_dir, "painted.json"), "w") as handle:
        json.dump({"parts": parts, "colours": labels,
                   "seeds": {str(k): [int(r) for r in v]
                             for k, v in seeds.items()}}, handle, indent=2)
    return field, labels
