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

This view shows %(where)s. The LEFT image is the plain shaded surface. The
RIGHT image is exactly the same view, with the %(count)d pieces this part
divides into shown in different colours and numbered.

For each numbered piece, say what it is and whether it is finished:

  "whole"  -- it is ONE nameable thing that would sensibly take ONE colour
              (a horn, an eye, a foot, a smooth flank panel)
  "group"  -- it is several things of the same kind, or a mixture, and would
              need breaking down before it could be coloured sensibly
              (a row of spikes, a field of barnacles, "head plus neck")
  "noise"  -- it is not a real part: a sliver, a shading artefact, or a piece
              of the neighbouring part that got included by accident

Judge the SHAPE in the left image; the colours on the right only tell you
which pixels belong to which numbered piece. Name what the geometry actually
shows, not what a dragon usually has.

Reply with ONLY a JSON object, no prose:
{"pieces": [{"n": <number>, "name": "<short name>", "kind": "whole|group|noise"}, ...]}
Every numbered piece must appear exactly once."""


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


def render_pieces(mesh, tree, node, pieces, up, out_dir, tag, pixels=560,
                  context=1.35, frame_on=-1):
    """Plain shading beside the same view divided and numbered.

    BOTH panels, always. The shape is what identifies a part -- a spike is a
    spike because of how it catches the light -- and a render that replaces
    shading with flat category colour throws exactly that away. Showing the
    two side by side lets the agent read the shape on the left and say which
    numbered piece it means on the right.
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
    centres = mesh.triangles[faces].mean(axis=1)
    centre = centres.mean(axis=0)
    spread = float(np.linalg.norm(np.ptp(centres, axis=0))) / 2.0
    whole = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0
    radius = float(np.clip(spread * context, whole * 0.03, whole * 1.06))

    # Look from where this part is actually visible, not from a fixed front.
    scouts = render_module.fibonacci_directions(12)
    best, seen = None, -1
    inside = np.zeros(len(mesh.faces), dtype=bool)
    inside[faces] = True
    for direction in scouts:
        camera = render_module.Camera(direction, up, centre, radius, 128)
        hit = render_module.geometry_bundle(mesh, camera,
                                            cavity_taps=0)["hit_id"]
        shown = hit[hit >= 0]
        here = int(inside[shown].sum()) if len(shown) else 0
        if here > seen:
            best, seen = direction, here
    camera = render_module.Camera(best, up, centre, radius, pixels)
    geometry = render_module.geometry_bundle(mesh, camera, cavity_taps=0)
    pose = rig_module.Pose("part", camera, geometry)
    shaded = rig_module.light(pose, "studio")

    piece_of = np.full(len(mesh.faces), -1, dtype=np.int64)
    for slot, piece in enumerate(pieces):
        piece_of[rig_module.face_mask(
            tree, rig_module.node_regions(tree, piece))] = slot

    hit = pose.hit_id
    visible = pose.visible
    plain = np.full((pixels, pixels, 3), 0.97)
    plain[visible] = np.clip(shaded, 0, 1)[visible, None]

    divided = plain.copy()
    where = np.full((pixels, pixels), -1, dtype=np.int64)
    where[visible] = piece_of[hit[visible]]
    palette = _palette(len(pieces))
    for slot in range(len(pieces)):
        mask = where == slot
        if not mask.any():
            continue
        tint = palette[slot]
        shade = np.clip(shaded, 0, 1)[mask][:, None]
        divided[mask] = np.clip(tint * (0.40 + 0.75 * shade), 0, 1)
    edge = np.zeros((pixels, pixels), dtype=bool)
    for dy, dx in ((0, 1), (1, 0)):
        rolled = np.roll(np.roll(where, dy, axis=0), dx, axis=1)
        edge |= visible & (rolled != where)
    divided[edge] *= 0.25

    sheet = Image.new("RGB", (pixels * 2 + 24, pixels + 16), (247, 246, 244))
    sheet.paste(Image.fromarray((plain * 255).astype(np.uint8)), (8, 8))
    sheet.paste(Image.fromarray((divided * 255).astype(np.uint8)),
                (pixels + 16, 8))
    draw = ImageDraw.Draw(sheet)
    listed = []
    for slot in range(len(pieces)):
        mask = where == slot
        if int(mask.sum()) < 40:
            continue
        ys, xs = np.nonzero(mask)
        x, y = int(np.median(xs)) + pixels + 16, int(np.median(ys)) + 8
        label = str(slot + 1)
        box = draw.textbbox((0, 0), label)
        pad = 5
        draw.rectangle([x - pad, y - pad, x + (box[2] - box[0]) + pad,
                        y + (box[3] - box[1]) + pad], fill=(15, 15, 18))
        draw.text((x, y), label, fill=(255, 255, 255))
        listed.append(slot)
    path = os.path.join(out_dir, "part-%s.png" % tag)
    sheet.save(path)
    return path, listed


def _palette(count):
    """Distinct, evenly spread hues. Not random: two pieces of one part came
    back in unrelated colours under a random palette, and no shape survived."""
    import colorsys
    return np.array([colorsys.hsv_to_rgb((0.61 * i) % 1.0, 0.62, 0.98)
                     for i in range(max(count, 1))])


def walk(backend, mesh, tree, up, intent, out_dir, root=None, want=6,
         max_depth=4, min_faces=80, log=print):
    """Top down from the whole object, stopping wherever the agent says whole.

    Returns the root `Part`. Cost is one look per node descended, and the
    recursion is shallow because it stops as soon as a piece is nameable --
    which is the entire point: the resolution comes from the model saying
    "that is one horn" rather than from anybody choosing a level.
    """
    os.makedirs(out_dir, exist_ok=True)
    areas = np.asarray(tree["area"], dtype=float)
    roots = forest_roots(tree) if root is None else [int(root)]

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
                                     out_dir, tag, frame_on=frame_on)
        if not listed:
            continue
        where = ("the whole piece" if current.parent is None
                 else "the part called '%s'" % current.path)
        prompt = ASK % {"intent": intent or "a 3D printed model",
                        "where": where, "count": len(pieces)}
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

    with open(os.path.join(out_dir, "hierarchy.json"), "w") as handle:
        json.dump(top.as_dict(), handle, indent=2)
    log("  walked %d node(s); %d parts named"
        % (looked, sum(1 for p in top.walk()) - 1))
    return top


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
        mask = rig_module.face_mask(tree, rig_module.node_regions(tree,
                                                                  part.node))
        out[mask] = len(labels)
        labels.append(part.path)
    return out, labels
