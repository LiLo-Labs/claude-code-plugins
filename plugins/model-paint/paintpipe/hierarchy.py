"""Walk the part hierarchy the way a person does: top down, stopping when it looks done.

THE MERGE TREE IS ALREADY A PART HIERARCHY. Every previous approach in this
pipeline flattened it -- into 250 atoms, into 687 persistence objects, into a
list of instances to be voted on -- and then spent enormous effort trying to
recover, statistically, the structure that flattening had just destroyed. A
dorsal ridge became forty spikes that each had to be found, localised,
climbed, confirmed and passed through a consensus gate, and a third of them
were lost on the way.

A person does not do that. A person looks at a dragon and sees head, body,
tail, legs. Asked for the spikes, they say "the ridge along the back" -- ONE
thing that happens to contain forty spikes -- and they only look closer if
they want the spikes to differ from each other. The forty never get
enumerated, because enumerating them was never the task.

So: start at the whole object, split it into the few pieces it is obviously
made of, and ask what they are. Anything that is one nameable part STOPS.
Anything that is a group gets descended into, framed on itself, and asked
again. THE AGENT DECIDES WHERE TO STOP, which is what makes the resolution
emerge from the model instead of from a parameter -- and it is why nothing
here has a threshold, a vote or a share.

Three properties fall out, and each fixes a specific failure:

    Few, large, legible pieces at every step. A node's five children fill the
    frame; 687 objects at once were confetti in which a single spike was split
    across four random colours and no shape could be read at all.

    The camera follows the recursion. Descending into the head FRAMES the
    head, so a part is always judged at a size where its boundary is visible
    -- rather than at four pixels across in a whole-model view.

    Nothing is discarded. There is no gate to fall below, so a part is never
    lost for want of agreement; it is either named, or descended into, or
    folded back into its parent, and all three are decisions somebody made by
    looking.
"""

import json
import os

import numpy as np

from . import rig as rig_module


ASK = """You are looking at ONE part of a 3D model that is being prepared for
multi-colour printing.

The piece as a whole: %(intent)s

This shows %(where)s from %(views)d different directions, laid out left to
right. In each PAIR of images the left one is the plain shaded surface and the
right one is exactly the same view with the pieces coloured and numbered.

THE NUMBERS MEAN THE SAME PIECE IN EVERY VIEW. A piece may be visible in only
one of them -- something on the far side appears only in the view that faces
it -- so use whichever view shows a given number best. The numbers present are:
%(numbers)s

For each numbered piece, say what it is and whether it is finished:

  "whole"  -- it is ONE nameable thing that would sensibly take ONE colour
              (a horn, an eye, a foot, a smooth flank panel)
  "group"  -- it is several things of the same kind, or a mixture, and would
              need breaking down before it could be coloured sensibly
              (a row of spikes, a field of barnacles, "head plus neck")
  "noise"  -- it is not a real part: a sliver, a shading artefact, or a piece
              of the neighbouring part that got included by accident

Judge the SHAPE in the plain images; the colours only tell you which pixels
belong to which numbered piece. Name what the geometry actually
shows, not what a dragon usually has.

Reply with ONLY a JSON object, no prose:
{"pieces": [{"n": <number>, "name": "<short name>", "kind": "whole|group|noise"}, ...]}
Every number listed above must appear exactly once."""


class Part:
    """One node of the walked hierarchy: what it is, and what it is made of."""

    def __init__(self, node, name, kind, parent=None, depth=0):
        self.node = int(node)
        self.name = name
        self.kind = kind
        self.parent = parent
        self.depth = int(depth)
        self.children = []

    @property
    def path(self):
        """Names from the root down, which is how a person refers to a part."""
        here = self.parent.path + " / " if self.parent else ""
        return here + self.name

    def walk(self):
        yield self
        for child in self.children:
            for item in child.walk():
                yield item

    def as_dict(self):
        return {"node": self.node, "name": self.name, "kind": self.kind,
                "depth": self.depth, "path": self.path,
                "children": [c.as_dict() for c in self.children]}


def pieces_of(tree, node, want=6, min_share=0.02):
    """The few pieces a node is obviously made of.

    The merge tree is binary, so its immediate children are two halves and
    usually meaningless -- half a cup plus a sliver of shell. Splitting the
    LARGEST piece repeatedly until there are `want` of them gives the division
    a person would describe instead: the pieces come out comparable in size,
    which is what makes them legible together in one picture.

    A piece below `min_share` of the node is not offered. It cannot be judged
    at this framing and would only crowd the numbering; it stays part of
    whatever it is attached to until a deeper level frames it properly.
    """
    children = tree["children"]
    areas = np.asarray(tree["area"], dtype=float)
    regions = int(tree["regions"])

    total = float(areas[int(node)]) or 1.0

    def worth(piece):
        return float(areas[piece]) / total >= min_share

    # Count only pieces big enough to be JUDGED, not pieces produced. A binary
    # merge tree sheds slivers: splitting the dragon's largest body gave 92.6%
    # plus a 4.6% fragment and four specks, so a loop that stopped at "six
    # pieces" stopped with two usable ones and the model was never divided at
    # all. Keep splitting the biggest until there are `want` substantial
    # pieces, or until nothing substantial can split any further.
    pieces = [int(node)]
    for _step in range(256):
        if sum(1 for p in pieces if worth(p)) >= want:
            break
        splittable = [p for p in pieces
                      if p >= regions and children[p][0] >= 0 and worth(p)]
        if not splittable:
            break
        biggest = max(splittable, key=lambda p: areas[p])
        left, right = (int(v) for v in children[biggest])
        pieces.remove(biggest)
        pieces.extend([left, right])

    kept = [p for p in pieces if worth(p)]
    return sorted(kept or pieces, key=lambda p: -areas[p])[:max(want, 2)]


def forest_roots(tree):
    """Every root of the merge FOREST, largest first.

    A print-in-place model is not one solid. The dragon is 29 interlocking
    bodies, so its merge forest has 29 roots, and a walk that started from the
    single largest would describe one body and silently ignore the other 28 --
    which is the same class of bug that once left 97% of this model
    unclaimed. The top level of the walk is therefore the forest, not a root.
    """
    children = np.asarray(tree["children"])
    claimed = set()
    for left, right in children:
        if left >= 0:
            claimed.add(int(left))
        if right >= 0:
            claimed.add(int(right))
    areas = np.asarray(tree["area"], dtype=float)
    regions = int(tree["regions"])
    roots = [n for n in range(len(children))
             if n not in claimed and (n < regions or children[n][0] >= 0)]
    return sorted(roots, key=lambda n: -areas[n])


def mirror_plane(mesh, samples=3000, accept=0.02, seed=3):
    """The model's own plane of symmetry, or None if it has none.

    A person paints the far horn without walking round the model, because they
    know it is the near horn mirrored. That is not a guess -- it is a fact
    about the geometry, and it is cheap to establish: mirror a sample of the
    surface through a candidate plane and measure how far the mirrored points
    land from the real surface. On a symmetric figurine the answer is
    essentially zero; on an asymmetric one it is not, and then this returns
    None and nothing downstream assumes anything.

    Only planes through the centroid along the frame's own axes are tried.
    The working mesh is already in its intrinsic frame, so a figurine's
    sagittal plane is one of them, and searching arbitrary orientations would
    cost far more for cases this pipeline does not have.
    """
    from scipy.spatial import cKDTree

    points = np.asarray(mesh.triangles, dtype=float).mean(axis=1)
    if len(points) > samples:
        rng = np.random.default_rng(seed)
        points = points[rng.choice(len(points), samples, replace=False)]
    tree_kd = cKDTree(np.asarray(mesh.triangles, dtype=float).mean(axis=1))
    centre = np.asarray(mesh.vertices, dtype=float).mean(axis=0)
    extent = float(np.ptp(mesh.vertices, axis=0).max()) or 1.0

    best = None
    for axis in np.eye(3):
        offset = points - centre
        mirrored = centre + offset - 2.0 * np.outer(offset @ axis, axis)
        distance, _index = tree_kd.query(mirrored)
        score = float(np.mean(distance)) / extent
        if best is None or score < best[0]:
            best = (score, axis)
    score, axis = best
    if score > accept:
        return None
    return {"point": centre, "normal": axis, "score": round(score, 5)}


def mirror_regions(mesh, tree, regions, plane, tolerance=0.015):
    """The base regions that are the mirror image of these, where they match.

    Every mirrored face has to LAND on real surface before its region is
    claimed. Without that test a near-symmetric model would have parts
    reflected into thin air, which is exactly the kind of confident nonsense
    that a claim nobody looked at produces.
    """
    from scipy.spatial import cKDTree

    if plane is None:
        return np.array([], dtype=np.int64)
    faces = np.flatnonzero(rig_module.face_mask(tree, regions))
    if not len(faces):
        return np.array([], dtype=np.int64)
    centres = np.asarray(mesh.triangles, dtype=float).mean(axis=1)
    point, normal = plane["point"], plane["normal"]
    offset = centres[faces] - point
    mirrored = point + offset - 2.0 * np.outer(offset @ normal, normal)
    extent = float(np.ptp(mesh.vertices, axis=0).max()) or 1.0
    distance, index = cKDTree(centres).query(mirrored)
    good = distance <= tolerance * extent
    if not good.any():
        return np.array([], dtype=np.int64)
    base = rig_module.region_of_face(tree)
    return np.unique(base[index[good]]).astype(np.int64)


def render_pieces(mesh, tree, node, pieces, up, out_dir, tag, pixels=470,
                  context=1.35, frame_on=-1, views=3, min_pixels=60):
    """Every piece shown from a view that can actually SEE it, numbered alike.

    One camera per node was the bug behind two visible failures: a horn on the
    far side of the head was never shown, so the agent described only the near
    one, and pieces round the back came back named with total confidence from
    a view in which they did not appear at all. An unseen piece is not a piece
    the model should be asked about.

    So several complementary directions are rendered, chosen greedily to cover
    the pieces rather than spread evenly -- the second view is whichever one
    shows most of what the first view missed. THE NUMBERING IS SHARED across
    views, which costs nothing here and is the entire payoff of the single
    index: piece 3 is tree node 3 whether it is seen from the front or the
    back, so the agent can name it from whichever panel shows it best.

    Returns (path, {piece slot: pixels seen anywhere}). A piece missing from
    that mapping was invisible in every view offered and must not be asked
    about -- the caller drops it rather than inviting an invented answer.
    """
    from PIL import Image, ImageDraw
    from . import render as render_module

    os.makedirs(out_dir, exist_ok=True)
    if frame_on is None:
        faces = np.arange(len(mesh.faces))
    else:
        target = node if frame_on == -1 else frame_on
        faces = np.flatnonzero(rig_module.face_mask(
            tree, rig_module.node_regions(tree, target)))
    centres_all = mesh.triangles.mean(axis=1)
    centre = centres_all[faces].mean(axis=0)
    spread = float(np.linalg.norm(np.ptp(centres_all[faces], axis=0))) / 2.0
    whole = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0
    radius = float(np.clip(spread * context, whole * 0.03, whole * 1.06))

    piece_of = np.full(len(mesh.faces), -1, dtype=np.int64)
    for slot, piece in enumerate(pieces):
        piece_of[rig_module.face_mask(
            tree, rig_module.node_regions(tree, piece))] = slot

    # Scout cheaply, then take the views that between them show the most
    # pieces. Greedy on unseen pieces, so a part hidden at the back pulls in
    # the view that reveals it instead of being outvoted by the front.
    scouts = render_module.fibonacci_directions(16)
    seen_by = []
    for direction in scouts:
        camera = render_module.Camera(direction, up, centre, radius, 140)
        hit = render_module.geometry_bundle(mesh, camera,
                                            cavity_taps=0)["hit_id"]
        shown = hit[hit >= 0]
        if not len(shown):
            seen_by.append(set())
            continue
        slots, counts = np.unique(piece_of[shown], return_counts=True)
        seen_by.append({int(sl) for sl, c in zip(slots, counts)
                        if sl >= 0 and c >= 4})

    chosen, covered = [], set()
    for _pick in range(int(views)):
        gains = [len(s - covered) for s in seen_by]
        best = int(np.argmax(gains))
        if gains[best] <= 0 and chosen:
            break
        chosen.append(best)
        covered |= seen_by[best]
        seen_by[best] = set()

    panels, visible_px = [], {}
    for which in chosen:
        camera = render_module.Camera(scouts[which], up, centre, radius, pixels)
        geometry = render_module.geometry_bundle(mesh, camera, cavity_taps=0)
        pose = rig_module.Pose("part", camera, geometry)
        shaded = rig_module.light(pose, "studio")
        hit, visible = pose.hit_id, pose.visible

        plain = np.full((pixels, pixels, 3), 0.97)
        plain[visible] = np.clip(shaded, 0, 1)[visible, None]
        divided = plain.copy()
        where = np.full((pixels, pixels), -1, dtype=np.int64)
        where[visible] = piece_of[hit[visible]]
        palette = _palette(len(pieces))
        for slot in range(len(pieces)):
            mask = where == slot
            count = int(mask.sum())
            if not count:
                continue
            visible_px[slot] = visible_px.get(slot, 0) + count
            shade = np.clip(shaded, 0, 1)[mask][:, None]
            divided[mask] = np.clip(palette[slot] * (0.40 + 0.75 * shade),
                                    0, 1)
        edge = np.zeros((pixels, pixels), dtype=bool)
        for dy, dx in ((0, 1), (1, 0)):
            rolled = np.roll(np.roll(where, dy, axis=0), dx, axis=1)
            edge |= visible & (rolled != where)
        divided[edge] *= 0.25
        panels.append((plain, divided, where))

    columns = len(panels)
    gap = 10
    sheet = Image.new("RGB", (columns * (pixels * 2 + gap) + gap,
                              pixels + 2 * gap), (247, 246, 244))
    draw_targets = []
    for index, (plain, divided, where) in enumerate(panels):
        x0 = gap + index * (pixels * 2 + gap)
        sheet.paste(Image.fromarray((plain * 255).astype(np.uint8)), (x0, gap))
        sheet.paste(Image.fromarray((divided * 255).astype(np.uint8)),
                    (x0 + pixels, gap))
        draw_targets.append((x0 + pixels, where))

    draw = ImageDraw.Draw(sheet)
    for x0, where in draw_targets:
        for slot in range(len(pieces)):
            mask = where == slot
            if int(mask.sum()) < min_pixels:
                continue
            ys, xs = np.nonzero(mask)
            x, y = int(np.median(xs)) + x0, int(np.median(ys)) + gap
            label = str(slot + 1)
            box = draw.textbbox((0, 0), label)
            pad = 5
            draw.rectangle([x - pad, y - pad, x + (box[2] - box[0]) + pad,
                            y + (box[3] - box[1]) + pad], fill=(15, 15, 18))
            draw.text((x, y), label, fill=(255, 255, 255))
    path = os.path.join(out_dir, "part-%s.png" % tag)
    sheet.save(path)
    legible = {slot: px for slot, px in visible_px.items() if px >= min_pixels}
    return path, legible


def _palette(count):
    """Distinct, evenly spread hues. Not random: two pieces of one part came
    back in unrelated colours under a random palette, and no shape survived."""
    import colorsys
    return np.array([colorsys.hsv_to_rgb((0.61 * i) % 1.0, 0.62, 0.98)
                     for i in range(max(count, 1))])


def walk(backend, mesh, tree, up, intent, out_dir, root=None, want=6,
         max_depth=4, min_faces=80, views=3, symmetry=True, log=print):
    """Top down from the whole object, stopping wherever the agent says whole.

    Returns the root `Part`. Cost is one look per node descended, and the
    recursion is shallow because it stops as soon as a piece is nameable --
    which is the entire point: the resolution comes from the model saying
    "that is one horn" rather than from anybody choosing a level.
    """
    os.makedirs(out_dir, exist_ok=True)
    areas = np.asarray(tree["area"], dtype=float)
    roots = forest_roots(tree) if root is None else [int(root)]

    plane = mirror_plane(mesh) if symmetry else None
    if plane is not None:
        log("  symmetry plane found (residual %.4f of model size); parts named "
            "on one side will be mirrored to the other" % plane["score"])
    elif symmetry:
        log("  no symmetry plane: nothing will be mirrored")

    # The top level is the FOREST, and it needs no picture to be chosen: the
    # bodies of a print-in-place model are given by the geometry, not by a
    # judgement. What needs a picture is what each one IS, so they are
    # rendered together and asked about together, exactly like any other level.
    top = Part(int(roots[0]), "the whole piece", "group", None, 0)
    top._forest = roots if len(roots) > 1 else None
    queue = [top]
    looked = 0
    while queue:
        current = queue.pop(0)
        if current.depth >= max_depth:
            continue
        forest = getattr(current, "_forest", None)
        pieces = forest if forest else pieces_of(tree, current.node, want=want)
        if len(pieces) < 2:
            continue
        faces_each = [int(rig_module.face_mask(
            tree, rig_module.node_regions(tree, p)).sum()) for p in pieces]
        if max(faces_each) < min_faces:
            continue

        tag = "%d-%d" % (current.depth, current.node)
        # A forest level is framed on the whole model, not on one of its bodies.
        frame_on = None if forest else current.node
        path, listed = render_pieces(mesh, tree, current.node, pieces, up,
                                     out_dir, tag, frame_on=frame_on,
                                     views=views)
        if not listed:
            continue
        views_used = min(views, max(1, len(listed)))
        # A piece nothing could see is not offered. Asking about it invites a
        # confident answer about a surface the agent never saw, which is how
        # the far-side horns came back named from a view they were not in.
        hidden = [sl for sl in range(len(pieces)) if sl not in listed]
        if hidden:
            log("    %d piece(s) invisible in every view; not asked about"
                % len(hidden))
        where = ("the whole piece" if current.parent is None
                 else "the part called '%s'" % current.path)
        prompt = ASK % {"intent": intent or "a 3D printed model",
                        "where": where, "views": views_used,
                        "numbers": ", ".join(str(sl + 1)
                                             for sl in sorted(listed))}
        answer = backend._run([path], prompt,
                              "walk-%s" % rig_module.digest(
                                  os.path.basename(path), prompt))
        looked += 1
        if not answer:
            continue
        for entry in answer.get("pieces", []) or []:
            try:
                slot = int(entry["n"]) - 1
                kind = str(entry.get("kind", "")).strip().lower()
                name = str(entry.get("name", "")).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if not (0 <= slot < len(pieces)) or not name:
                continue
            if slot not in listed:
                continue
            if kind == "noise":
                # Folded back into its parent rather than deleted: it is
                # surface, and every face has to end up somewhere.
                continue
            child = Part(pieces[slot], name, kind or "whole", current,
                         current.depth + 1)
            current.children.append(child)
            if kind == "group":
                queue.append(child)
        log("  %s -> %s" % (where, ", ".join(
            "%s[%s]" % (c.name, c.kind) for c in current.children) or "nothing"))

    if plane is not None:
        mirrored = complete_by_symmetry(mesh, tree, top, plane, log=log)
        log("  symmetry completed %d part(s)" % mirrored)

    with open(os.path.join(out_dir, "hierarchy.json"), "w") as handle:
        json.dump(top.as_dict(), handle, indent=2)
    log("  walked %d node(s); %d parts named"
        % (looked, sum(1 for p in top.walk()) - 1))
    return top


def complete_by_symmetry(mesh, tree, top, plane, coarser=3.0, log=print):
    """Give every named part its mirror image, where the surface agrees.

    This is what fixes a part that exists on both sides but was only ever
    LOOKED at on one -- the second horn that stayed inside the skull piece
    because no view showed it, and the far side that no camera reached. It
    adds no vision calls: the mirror of a surface that was seen is not a
    guess, it is the same geometry.

    A mirror may take regions that are unclaimed, and regions held by a part
    much COARSER than itself. That second case is the one that matters and it
    was nearly got wrong. On the dragon's head the split offered one horn as
    its own piece and left the other inside the 144-region skull, so the horn
    was named and its twin was not; a rule that simply refused to overwrite
    any existing claim would decline the mirror and preserve the exact defect
    it exists to repair. A 14-region horn mirrored onto 8 regions sitting
    inside a 144-region skull is not overwriting a peer -- it is refining a
    container that was never split there.

    Against a claimant of comparable size the mirror is declined, because then
    the far side really is a different thing (a scar on one cheek), and an
    inference must never overwrite an observation of equal standing.
    """
    named = [p for p in top.walk() if p.parent is not None]
    claimed = {}
    for part in named:
        for region in rig_module.node_regions(tree, part.node):
            claimed.setdefault(int(region), part)

    added = 0
    for part in list(named):
        own = rig_module.node_regions(tree, part.node)
        twin = mirror_regions(mesh, tree, own, plane)
        if not len(twin):
            continue
        own_size = len(own)
        free = []
        for region in twin:
            holder = claimed.get(int(region))
            if holder is None:
                free.append(int(region))
            elif holder is not part and holder.kind != "whole":
                continue
            elif (holder is not part
                  and len(rig_module.node_regions(tree, holder.node))
                  >= coarser * own_size):
                free.append(int(region))
        if not free:
            continue
        part.mirrored = np.asarray(sorted(free), dtype=np.int64)
        for region in free:
            claimed[region] = part
        added += 1
        if log:
            log("    %s: mirrored onto %d unclaimed region(s)"
                % (part.name, len(free)))
    return added


def regions_of(tree, part):
    """Everything a part covers: its own node, plus its mirror if it has one."""
    own = np.asarray(rig_module.node_regions(tree, part.node), dtype=np.int64)
    extra = getattr(part, "mirrored", None)
    if extra is None or not len(extra):
        return own
    return np.unique(np.concatenate([own, extra]))


def leaves(part):
    """The parts a person would actually pick colours for."""
    return [p for p in part.walk()
            if p.kind == "whole" or (p.kind == "group" and not p.children)]


def field(tree, parts, face_count):
    """A per-face label field from chosen parts, deepest claim winning.

    Deepest wins because a child is a more specific statement about the same
    surface than its parent: if the walk called something "head" and then
    called part of it "eye", the eye is the better answer for those faces.
    """
    out = np.full(face_count, -1, dtype=np.int64)
    labels = []
    for part in sorted(parts, key=lambda p: p.depth):
        mask = rig_module.face_mask(tree, regions_of(tree, part))
        out[mask] = len(labels)
        labels.append(part.path)
    return out, labels
