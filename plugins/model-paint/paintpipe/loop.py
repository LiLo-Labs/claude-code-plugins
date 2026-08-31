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


ASK = """The LEFT image is a 3D model plainly shaded. The RIGHT image is the SAME
views with the current colouring painted on. Colours are listed below.

The piece: %(intent)s

Current colours:
%(legend)s

Two things:

1. NAME each colour -- what part of the model is it actually covering? If a
   colour covers several unrelated things, say so and name the biggest.

2. List what is WRONG, as places. For each, give the view number and a pixel
   coordinate IN THE RIGHT-HAND image of that view, and which colour that
   spot should be:
     - a place painted the wrong colour
     - a place that should be its own part (say "new" as the colour)

Give at most %(budget)d corrections, the most important first. Corrections
should be places you can point at, not descriptions.

Reply with ONLY a JSON object, no prose:
{"names": {"<colour number>": "<what it is>"},
 "fixes": [{"view": <int>, "x": <int>, "y": <int>, "colour": <int or "new">,
            "why": "<short>"}, ...]}
An empty "fixes" list means the colouring matches what you see."""


def bifurcate(tree, node, min_share=0.18, budget=4000):
    """The most balanced real split available inside a node.

    This is the operation that breaks a chain, and without it nothing here
    works. The top of an agglomerative merge tree is not a balanced tree: the
    last merges absorb one small region at a time, so splitting the biggest
    piece into its two children peels a speck and leaves the giant. Seven
    splits of the shell's root gave 100.0000% + 0.0000%, seven times over --
    and the SHIPPED atom cut has the same shape, returning 250 atoms of which
    one holds 82.1% of the surface and 248 hold under 0.1% each. On the dragon
    the same code gives a largest atom of 3.3%, which is why it went unnoticed.

    SEARCHING BEATS WALKING, and the difference is the whole fix. Following the
    big side down the chain misses balanced splits that sit on a branch it
    never enters: the shell has nine of them among nodes over 5% of the model,
    and a walk found none. So look over the node's substantial descendants and
    take the split whose smaller half is largest.

    Everything shed on the way to that split is returned too, because it is
    real surface and a partition that drops it is not a partition.
    """
    children = tree["children"]
    areas = np.asarray(tree["area"], dtype=float)
    root_area = float(areas[int(node)])
    if children[int(node)][0] < 0:
        return [int(node)], []

    best, frontier, seen = None, [int(node)], 0
    while frontier and seen < budget:
        current = frontier.pop(0)
        seen += 1
        left, right = (int(v) for v in children[current])
        if left < 0:
            continue
        smaller = min(float(areas[left]), float(areas[right]))
        if best is None or smaller > best[0]:
            best = (smaller, current, left, right)
        for side in (left, right):
            if children[side][0] >= 0 and areas[side] >= min_share * root_area:
                frontier.append(side)

    if best is None:
        return [int(node)], []
    _smaller, where, left, right = best

    # Everything under `node` that is not under `where` is shed: it is the
    # material peeled off on the way down, and it still has to go somewhere.
    inside = set(int(r) for r in rig_module.node_regions(tree, where))
    shed_regions = [int(r) for r in rig_module.node_regions(tree, int(node))
                    if r not in inside]
    return [left, right], shed_regions


def first_painting(mesh, tree, count=8):
    """A partition of the WHOLE surface, from geometry alone. No vision.

    Split the biggest piece -- through `bifurcate`, so a split is a real
    division rather than a peel -- until there are `count` of them. It will be
    a poor division; the point is that it is a COMPLETE one, so the first
    render shows something to correct instead of a mostly grey model with a
    question attached.
    """
    areas = np.asarray(tree["area"], dtype=float)
    children = tree["children"]
    regions = int(tree["regions"])

    claimed = set()
    for node in range(len(children)):
        for side in children[node]:
            if side >= 0:
                claimed.add(int(side))
    pieces = [n for n in range(len(children))
              if n not in claimed and (n < regions or children[n][0] >= 0)]
    crumbs = []

    while len(pieces) < count:
        splittable = [p for p in pieces if children[p][0] >= 0]
        if not splittable:
            break
        biggest = max(splittable, key=lambda p: areas[p])
        parts, shed = bifurcate(tree, biggest)
        if len(parts) < 2:
            break
        pieces.remove(biggest)
        pieces.extend(parts)
        crumbs.extend(shed)

    pieces = sorted(pieces, key=lambda p: -areas[p])
    field = np.full(len(mesh.faces), 0, dtype=np.int64)
    # Crumbs first, so a real piece always wins the faces it shares with one.
    if crumbs:
        field[rig_module.face_mask(tree, crumbs)] = 0
    for slot, piece in enumerate(pieces):
        field[rig_module.face_mask(
            tree, rig_module.node_regions(tree, piece))] = slot
    return field, ["colour %d" % (i + 1) for i in range(len(pieces))]


# Twelve colours chosen to stay apart in hue AND in lightness. Generating them
# as hue = 0.61 * i put colour 2 at 0.61 and colour 7 at 0.66 -- two blues five
# hundredths apart, which made the shell body and the large barnacles the same
# colour in the render. The agent is asked to judge one colour against another
# in that picture, so two colours it cannot tell apart is not a cosmetic fault.
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


def show(mesh, up, field, labels, out_dir, tag, views=3, pixels=520):
    """Plain beside painted, same views, numbered. The only picture ever asked about."""
    from PIL import Image, ImageDraw
    from . import preview

    os.makedirs(out_dir, exist_ok=True)
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

    gap = 8
    sheet = Image.new("RGB", (len(panels) * (2 * pixels + gap) + gap,
                              pixels + 2 * gap + 18), (247, 246, 244))
    draw = ImageDraw.Draw(sheet)
    for index, (plain, painted) in enumerate(panels):
        x0 = gap + index * (2 * pixels + gap)
        sheet.paste(Image.fromarray((plain * 255).astype(np.uint8)), (x0, gap))
        sheet.paste(Image.fromarray((painted * 255).astype(np.uint8)),
                    (x0 + pixels, gap))
        draw.text((x0 + 4, pixels + gap + 3), "view %d" % index,
                  fill=(20, 20, 20))
    path = os.path.join(out_dir, "state-%s.png" % tag)
    sheet.save(path)
    return path, poses, (pixels, gap)


def paint_units(tree):
    """The unit a single click paints: a persistence object, cached on the tree.

    NOT an ancestor at some multiple of the clicked region's area. That
    assumed the ancestor chain contains a node of roughly the size wanted, and
    in an agglomerative tree it does not: a region's parent is already the
    accumulated giant, so every click resolved to either one tiny region or a
    huge blob with nothing in between. It is the same chain pathology that
    broke the sizing ladder and the first painting, showing up a third time --
    "barnacle clusters" took 28.2% of the shell and overwrote the shell body
    to 0.0%.

    Persistence objects are the unit this repo already validated: nodes that
    survive a long way up the tree before being absorbed, so each is a thing
    rather than an arbitrary cut. On the shell the largest is 5.1% of the
    surface against the 82.1% of the area-based cut, which is the difference
    between a click that paints a barnacle and a click that paints the model.
    """
    cached = tree.get("_units")
    if cached is not None:
        return cached
    regions_total = int(tree["regions"])
    if "birth" not in tree or "used" not in tree:
        # A tree built before persistence was kept, or a synthetic one. Fall
        # back to the base region itself: finer than ideal, but a click still
        # lands somewhere real and the loop can still add to it. Crashing
        # because an old cache lacks a field is not an option a run can take.
        owner = np.arange(regions_total, dtype=np.int64)
        tree["_units"] = owner
        return owner
    from . import segment3d  # noqa: F401  (puts scripts/ on sys.path)
    import index_persist

    # Persistence is measured as a log ratio against `floor`, so a floor of
    # zero divides by zero. Real weights are positive, but a mesh with one
    # zero-weight border would take the whole run down for it, so the floor is
    # nudged off zero here rather than left to chance.
    floor = float(tree.get("floor", 0.0))
    ceiling = float(tree.get("ceiling", 1.0))
    if not np.isfinite(floor) or floor <= 0:
        floor = 1e-9
    if not np.isfinite(ceiling) or ceiling <= floor:
        ceiling = floor * 1e6
    chosen = index_persist.select(tree["children"], tree["birth"],
                                  tree["death"], tree["area"],
                                  int(tree["used"]), floor, ceiling)
    owner = np.arange(regions_total, dtype=np.int64)
    for node in chosen:
        for leaf in rig_module.node_regions(tree, int(node)):
            owner[int(leaf)] = int(node)
    tree["_units"] = owner
    return owner



def panel_point(geometry, views, view, x, y):
    """A coordinate given on the sheet -> the pixel inside that view's panel.

    The sheet lays out `views` pairs side by side, so the right-hand panel of
    view v starts at gap + v*(2*pixels+gap) + pixels. Subtracting one panel
    width is right for view 0 and wrong for every view after it, which once
    threw away half of every round's corrections in silence; a coordinate
    given in the plain panel, or already panel-local, is recovered instead of
    being lost.
    """
    pixels, gap = geometry
    if not (0 <= view < views):
        return None
    stride = 2 * pixels + gap
    origin = gap + view * stride + pixels
    local_x, local_y = x - origin, y - gap
    if not (0 <= local_x < pixels):
        plain = gap + view * stride
        local_x = x - plain if 0 <= x - plain < pixels else x % pixels
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


def outline_regions(tree, poses, geometry, shapes, share=0.5):
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
    pixels, _gap = geometry
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
        visible = pose.visible
        if not visible.any():
            continue
        here = base[pose.hit_id[visible]]
        seen += np.bincount(here, minlength=regions)
        if view not in by_view:
            continue
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
    keep = (seen > 0) & (inside >= share * seen)
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

def resolve_point(tree, poses, geometry, view, x, y, growth=8.0):
    """A pointed-at place -> the faces it means. Shared by adding and removing.

    Both operations have to agree about what a point covers. When they did not
    -- add painted a node, remove restored every face of the whole part -- a
    single "this has spread too far" wiped the entire colour, and four of the
    shell's parts came back at 0.0% having been painted correctly first.

    The coordinate arrives in SHEET space, whose right-hand panel for view v
    starts at gap + v*(2*pixels+gap) + pixels. Subtracting one panel width is
    right for view 0 and wrong for every view after it, which silently threw
    away half of every round's corrections; a point given in the plain panel or
    already panel-local is recovered rather than lost.
    """
    pixels, gap = geometry
    if not (0 <= view < len(poses)):
        return None
    stride = 2 * pixels + gap
    origin = gap + view * stride + pixels
    local_x, local_y = x - origin, y - gap
    if not (0 <= local_x < pixels):
        plain = gap + view * stride
        local_x = x - plain if 0 <= x - plain < pixels else x % pixels
    if not (0 <= local_y < pixels):
        local_y = y % pixels

    base = rig_module.region_of_face(tree)
    region = rig_module.point_to_region(poses[view], base, local_x, local_y)
    if region < 0:
        return None
    node = int(paint_units(tree)[int(region)])
    return rig_module.face_mask(tree, rig_module.node_regions(tree, node))


def apply_fixes(field, tree, poses, geometry, fixes, labels, growth=8.0,
                log=None):
    """Turn pointed-at places into edits of the field.

    A correction lands on one base region, and one region is far too small to
    be a useful edit, so it takes the ancestor a fixed FACTOR larger in area.
    The factor is scale-free -- eight times whatever was clicked -- so the same
    number moves a barnacle-sized chunk when a barnacle was clicked and a
    dome-sized chunk when the dome was clicked, which is what lets it work on
    any model at any size.

    It does not have to be right. That is the point of the loop: a part still
    short next round gets pointed at somewhere else and the chunks union, which
    is how a person fills a large area too.
    """
    applied = 0
    for fix in fixes:
        try:
            view = int(fix["view"])
            x, y = int(fix["x"]), int(fix["y"])
            wanted = fix.get("colour")
        except (KeyError, TypeError, ValueError):
            continue
        if wanted == "new" or wanted is None:
            slot = len(labels)
            labels.append("colour %d" % (slot + 1))
        else:
            try:
                slot = int(wanted) - 1
            except (TypeError, ValueError):
                continue
            if not (0 <= slot < len(labels)):
                continue
        mask = resolve_point(tree, poses, geometry, view, x, y, growth=growth)
        if mask is None:
            continue
        field[mask] = slot
        applied += 1
    if log:
        log("    applied %d/%d correction(s)" % (applied, len(fixes)))
    return field, labels, applied


def run(backend, mesh, tree, up, intent, out_dir, rounds=4, start=8, views=3,
        budget=8, log=print):
    """paint -> look -> fix -> repeat. Returns the field and what each colour is."""
    os.makedirs(out_dir, exist_ok=True)
    field, labels = first_painting(mesh, tree, count=start)
    names = {}

    for step in range(rounds):
        path, poses, geometry = show(mesh, up, field, labels, out_dir,
                                     str(step), views=views)
        legend = "\n".join("  %d: %s" % (i + 1, names.get(i, "unnamed"))
                           for i in range(len(labels)))
        prompt = ASK % {"intent": intent or "a 3D printed model",
                        "legend": legend, "budget": budget}
        with open(path, "rb") as handle:
            key = "loop-%s" % rig_module.digest(handle.read(), prompt)
        answer = backend._run([path], prompt, key)
        if not answer:
            log("  round %d: no answer" % step)
            break
        for slot, name in (answer.get("names") or {}).items():
            try:
                names[int(slot) - 1] = str(name)[:60]
            except (TypeError, ValueError):
                continue
        fixes = answer.get("fixes") or []
        log("  round %d: %d colour(s) named, %d correction(s)"
            % (step, len(names), len(fixes)))
        for fix in fixes[:budget]:
            log("      %s -> colour %s (%s)"
                % (str(fix.get("why", ""))[:44], fix.get("colour"),
                   "view %s" % fix.get("view")))
        if not fixes:
            log("  round %d: nothing wrong; stopping" % step)
            break
        field, labels, applied = apply_fixes(field, tree, poses, geometry,
                                             fixes[:budget], labels, log=log)
        if not applied:
            break

    final = [names.get(i, labels[i]) for i in range(len(labels))]
    with open(os.path.join(out_dir, "loop.json"), "w") as handle:
        json.dump({"colours": final}, handle, indent=2)
    return field, final


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


WHERE = """The LEFT image is a 3D model plainly shaded, %(count)d views. The RIGHT
image of each pair is the painting so far.

The piece: %(intent)s

I am about to paint: %(name)s -- %(where)s

DRAW ROUND IT, in the RIGHT-HAND image of each view that shows it.

Give one closed outline per separate piece of it -- a list of pixel corners
that goes round the piece and back to the start. Follow the shape: a long
piece wants corners along both of its sides, not a box round it. On a field of
many small things (a row of spikes, a patch of barnacles), draw round each
patch, or round each thing if they are far apart -- as many outlines as it
takes.

Trace just INSIDE the edge rather than just outside. A surface is only taken
when most of it falls within an outline, so cutting a little short costs
nothing while spilling over paints the neighbour.

Also drop %(want)d or more points ON the part per view, as a check on the
outlines: on the same pieces, spread over them.

If a view does not show it, give nothing for that view.

Reply with ONLY a JSON object, no prose:
{"shapes": [{"view": <int>, "points": [{"x": <int>, "y": <int>}, ...]}, ...],
 "points": [{"view": <int>, "x": <int>, "y": <int>}, ...]}"""


CHECK = """The LEFT image of each pair is the model plainly shaded. The RIGHT is the
painting so far. I have just painted %(name)s in the colour shown as %(swatch)s.

The piece: %(intent)s

Look only at that colour. Is it on the right surface?

Give corrections as places, at most %(budget)d, most important first:
  - "add"    the part is there but unpainted -- point at it
  - "remove" the colour has spread somewhere it should not be -- point at it

Reply with ONLY a JSON object, no prose:
{"fixes": [{"kind": "add|remove", "view": <int>, "x": <int>, "y": <int>,
            "why": "<short>"}, ...]}
An empty list means that colour is right."""


def see(backend, mesh, up, intent, out_dir, views=4, pixels=700, log=print):
    """What parts, how much detail each, and in what order to paint them."""
    from . import discover
    sheet, paths, poses = discover.survey_views(mesh, up, out_dir,
                                                pixels=pixels, count=views,
                                                log=None)
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
             tag, budget=6, views=3, log=print):
    """Paint ONE part, look at it, fix it, and re-settle the whole surface.

    A person does not paint everything and then audit everything; they lay one
    colour, check that colour, fix it, and move on. Checking one colour against
    a picture is a far easier question than checking eight.

    What changed is what "lay a colour" means. It used to stamp a fixed-size
    chunk at each point, which is why the same loop first ran away (28% of the
    shell called barnacles) and then under-filled (every part a few percent,
    the base coat 83.7%). Now a point is a claim, every region on the model is
    re-awarded to its most continuous claim, and the extent of this part comes
    from where the OTHER parts were pointed at. So the picture changes globally
    after every correction, which is the point: a fix to the shell moves the
    barnacle border too, exactly as it does on a real model.

    Returns (seeds, labels, field, points_made).
    """
    slot = len(labels)
    labels.append(part["name"])
    count = len(labels)

    before = settle(tree, seeds, count) if seeds else None
    field = (field_of(tree, before, len(mesh.faces)) if before is not None
             else np.full(len(mesh.faces), -1, dtype=np.int64))
    path, poses, geometry = show(mesh, up, field, labels, out_dir,
                                 "%s-before" % tag, views=views)
    # A large flat part wants covering; a scattered detail wants examples on
    # many of its members. Both are "more points than a click", which is the
    # measured lesson: from 5-11 seeds on 11876 regions, every way of spreading
    # a claim -- the merge tree, shortest path over the borders, and matching
    # the surface signature -- drew distance bands instead of parts, because
    # sparse seeds make any of them a Voronoi diagram.
    prompt = WHERE % {"count": len(poses), "intent": intent or "a 3D model",
                      "name": part["name"], "where": part["where"],
                      "want": 30 if part.get("detail") == "detailed" else 20}
    with open(path, "rb") as handle:
        key = "where-%s" % rig_module.digest(handle.read(), part["name"])
    answer = backend._run([path], prompt, key) or {}
    # THE OUTLINE IS THE EXTENT; the points only confirm it. Neither the tree
    # nor any rule for filling between marks can say how far a part goes --
    # measured, the chain above a rib seed jumps 0.132% to 33.989% of the
    # surface, and every fill rule tried drew bands or confetti. The picture
    # says, so the picture is asked.
    drawn = outline_regions(tree, poses, geometry, answer.get("shapes") or [])
    points = seed_regions(tree, poses, geometry, answer.get("points") or [])
    claimed = sorted(set(int(r) for r in drawn) | set(points))
    if not claimed:
        if log:
            log("    %s: not found in any view" % part["name"])
        labels.pop()
        return seeds, labels, field, 0
    seeds[slot] = claimed

    owner = settle(tree, seeds, count)
    field = field_of(tree, owner, len(mesh.faces))
    path, poses, geometry = show(mesh, up, field, labels, out_dir,
                                 "%s-after" % tag, views=views)
    prompt = CHECK % {"name": part["name"], "swatch": "colour %d" % (slot + 1),
                      "intent": intent or "a 3D model", "budget": budget}
    with open(path, "rb") as handle:
        key = "check-%s" % rig_module.digest(handle.read(), part["name"])
    answer = backend._run([path], prompt, key) or {}
    adds, removes = [], []
    for fix in (answer.get("fixes") or [])[:budget]:
        if str(fix.get("kind", "add")).lower() == "remove":
            removes.append(fix)
        else:
            adds.append(fix)

    grown = set(seed_regions(tree, poses, geometry, adds))
    grown |= set(int(r) for r in
                 outline_regions(tree, poses, geometry,
                                 [f for f in adds if f.get("points")]))
    if grown:
        seeds[slot] = sorted(set(seeds[slot]) | grown)
    # "remove" RESTORES WHAT WAS UNDERNEATH. Sending it to colour 1 handed
    # every over-painted patch to whichever part was painted first -- on the
    # shell the rock base -- so "this barnacle colour has spread onto the
    # shell" turned that shell surface into rock. Undo has to be undo, and
    # here undo is re-asserting the claim this part took the ground from.
    for region in seed_regions(tree, poses, geometry, removes):
        # RETRACT FIRST. Re-asserting the old claim while leaving this part's
        # own click in place is not undo: both parts then hold the region, and
        # ties go to the later one, so the correction changed nothing at all.
        seeds[slot] = [r for r in seeds.get(slot, []) if r != region]
        prior = int(before[region]) if before is not None else -1
        if prior < 0 or prior == slot:
            continue
        seeds[prior] = sorted(set(seeds.get(prior, [])) | {region})

    owner = settle(tree, seeds, count)
    field = field_of(tree, owner, len(mesh.faces))
    if log:
        log("    %-32s %d point(s), %d add, %d remove"
            % (part["name"], len(points), len(adds), len(removes)))
    return seeds, labels, field, len(points)


def paint(backend, mesh, tree, up, intent, out_dir, views=3, budget=6,
          max_parts=8, log=print):
    """The whole method, in the order a person works.

    See what parts there are and how much detail each has; paint them in the
    order given, background first so later coats land on top; and after each
    colour, look at that colour and fix it before starting the next.

    Nothing anywhere sets a size. Every part's extent is settled by the
    competition between the places the parts were pointed at, so the same
    procedure sizes a 4mm barnacle and a 190mm shell without being told which
    is which -- which is the only way it can work on a model nobody has seen.
    """
    os.makedirs(out_dir, exist_ok=True)
    parts = see(backend, mesh, up, intent, out_dir, views=views, log=log)
    if not parts:
        return None, []

    seeds, labels = {}, []
    field = np.full(len(mesh.faces), -1, dtype=np.int64)
    for index, part in enumerate(parts[:max_parts]):
        seeds, labels, field, _n = add_part(
            backend, mesh, tree, up, seeds, labels, part, intent, out_dir,
            str(index), budget=budget, views=views, log=log)
    show(mesh, up, field, labels, out_dir, "final", views=views)
    if log:
        areas = mesh.area_faces
        total = float(areas.sum()) or 1.0
        for slot, name in enumerate(labels):
            log("  %-32s %5.1f%%"
                % (name, 100.0 * float(areas[field == slot].sum()) / total))
        left = 100.0 * float(areas[field < 0].sum()) / total
        if left > 0.05:
            log("  %-32s %5.1f%%" % ("(unclaimed)", left))
    with open(os.path.join(out_dir, "painted.json"), "w") as handle:
        json.dump({"parts": parts, "colours": labels}, handle, indent=2)
    return field, labels
