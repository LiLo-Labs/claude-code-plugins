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


def palette(count):
    import colorsys
    return np.array([colorsys.hsv_to_rgb((0.61 * i) % 1.0, 0.58, 0.95)
                     for i in range(max(count, 1))])


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


def apply_fixes(field, tree, poses, geometry, fixes, labels, growth=8.0,
                log=None):
    """Turn pointed-at places into edits of the field.

    A correction lands on one base region, and one region is far too small to
    be a useful edit, so it takes the ancestor a fixed FACTOR larger in area.
    The factor is scale-free -- eight times whatever was clicked -- so the same
    number moves a barnacle-sized chunk when a barnacle was clicked and a
    dome-sized chunk when the dome was clicked, which is the property that
    makes it work on any model at any size.

    It does not have to be right. That is the point of the loop: a part that
    is still short next round gets pointed at somewhere else, and the chunks
    union. Clicking a few places and taking a safe chunk at each is how a
    person fills a large area too.
    """
    from . import index3d

    pixels, _gap = geometry
    base = rig_module.region_of_face(tree)
    areas = np.asarray(tree["area"], dtype=float)
    applied = 0

    for fix in fixes:
        try:
            view = int(fix["view"])
            x, y = int(fix["x"]), int(fix["y"])
            wanted = fix.get("colour")
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= view < len(poses)):
            continue
        # The coordinate is given in the RIGHT-hand (painted) panel, which sits
        # one panel width along; both panels are the same camera, so removing
        # the offset lands it on the same surface.
        local_x = x - pixels if x >= pixels else x
        region = rig_module.point_to_region(poses[view], base, local_x, y)
        if region < 0:
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

        chain = rig_module.ancestors(tree, int(region))
        target = float(areas[int(region)]) * float(growth)
        node = index3d.nearest_by_area(chain, areas, target)
        field[rig_module.face_mask(tree,
                                   rig_module.node_regions(tree, node))] = slot
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
