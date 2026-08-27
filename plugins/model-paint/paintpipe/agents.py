"""Agent contracts (spec §10).

Each agent has a typed contract and an `actor` id that appears on everything it
produces. Agents share NO hidden state; everything crosses through the field or the
evidence store. That is not a style preference -- it is what makes I5 enforceable, since
a belief that arrived through a side channel has no provenance to carry.

Two of the seven are deterministic and contain no model call at all: Fusion is §7 and §8,
and the Limiter is §11. They are agents in the sense that they have a contract and an
actor id, not in the sense that they reason.

The LLM agents are defined here by their contracts and by a deterministic stand-in each.
A stand-in is NOT a simulation of judgement: it is the honest floor of what the pipeline
does with no model attached, so that the machinery can be run, measured and tested
without pretending a model was consulted. Every stand-in records `actor` as
`deterministic:...`, so nothing downstream can mistake it for a model's opinion.
"""

import numpy as np

from . import cues as cue_module


class Agent:
    """Typed contract plus an actor id stamped on everything the agent produces."""

    kind = "deterministic"
    name = "agent"

    def __init__(self, actor=None):
        self.actor = actor or "%s:%s@0.2.0" % (self.kind, self.name)


class Planner(Agent):
    """profile, brief, hardware -> run policy.

    Decides how much of the ladder deserves semantic attention, and RECORDS WHY. A run
    that attends to every band on a model whose fine band is below what the painter can
    resolve has spent its budget describing detail nobody can paint.
    """

    name = "planner"

    def plan(self, bands, profile, intent, policy):
        tip = profile.finest_tip()
        attended, skipped = [], []
        for band in bands:
            if tip is not None and band.wavelength_mm < tip.tip_radius_mm:
                skipped.append((band, "finer than the finest brush tip can express"))
            else:
                attended.append(band)
        if not attended:
            attended, skipped = list(bands[:1]), skipped[1:]
        return {"attend": attended, "skip": skipped,
                "reason": "attending %d of %d bands" % (len(attended), len(bands))}


class Identity(Agent):
    """overviews -> class, size estimate, frame names, part tree.

    The tree is SPECULATIVE BY DESIGN. A part that is hypothesised and never found
    expires with a recorded negative, which is information: "this object has no visor"
    is an answer, and a pipeline that silently drops unmatched hypotheses cannot give it.
    """

    name = "identity"

    def read(self, overviews, frame):
        # Deterministic stand-in: name the axes from the frame's own extents. The long
        # axis is front-to-back and the shortest is up for a based model. A model agent
        # replaces this by LOOKING, which is the point of §4.2 step 2.
        order = np.argsort(frame.extent_mm)[::-1]
        names = {"front": np.eye(3)[order[0]], "right": np.eye(3)[order[1]],
                 "up": np.eye(3)[order[2]]}
        return {"class": None, "axis_names": names, "parts": [],
                "note": "axis names from extents; no model consulted"}


class Region(Agent):
    """one bundle + cues + tree -> overlapping fuzzy masks.

    Never forced to partition, and never told about other views. Both constraints are
    load-bearing: a partition would make the agent resolve ambiguity it cannot see, and
    knowledge of other views would let one camera's mistake propagate as though it were
    independent evidence.

    Masks do not have to be right. They are weighted by §7 and fused by §8 across every
    camera, rig and band, so a mask that is wrong in one view is outvoted rather than
    believed. That is the whole reason this agent is allowed to be uncertain.
    """

    name = "region"

    def propose(self, bundle, band, tree=None):
        """Yield (label, confidence map). Continuous confidence, never binary."""
        cavity, cavity_ok = cue_module.cavity(bundle, band.wavelength_mm)
        ridge, ridge_ok = cue_module.ridge(bundle, band.wavelength_mm)
        plane, plane_ok = cue_module.plane(bundle, band.wavelength_mm)
        yield ("recess", np.where(cavity_ok, np.nan_to_num(cavity), 0.0))
        yield ("relief", np.where(ridge_ok, np.nan_to_num(ridge), 0.0))
        # A field is what is left when neither edge cue is firing: the surface a painter
        # would give one flat colour.
        field = np.where(plane_ok, np.nan_to_num(plane), 0.0)
        field = field * (1.0 - np.clip(np.nan_to_num(cavity) + np.nan_to_num(ridge),
                                       0.0, 1.0))
        yield ("field", field)


class VisionRegion(Region):
    """The Region agent of §10, backed by a vision model.

    The model names parts and points at them; `vision.synthesise_mask` grows each point
    into a fuzzy mask through the cue maps. Neither half could do this alone: the model
    cannot paint pixels, and the cues cannot say which blob is a barnacle colony.

    ONE CALL PER CAMERA, not per bundle. §5.2 makes the zenithal rig the reference for
    shade and highlight reasoning, so that is the render the agent looks at, and its
    proposals are then admitted separately under every rig and band of that camera. The
    alternative -- asking the model the same question about the same geometry under three
    lights -- triples the cost to gather three answers that are correlated anyway, which
    is the opposite of what independent evidence means.

    Seed confidence is carried through as `mask_confidence` into §7's weight, so a part
    the agent half-saw contributes half as much. It is never rounded up to a decision.
    """

    name = "vision_region"

    def __init__(self, backend, vocabulary=None, intent="", policy=None, store=None,
                 actor=None):
        super().__init__(actor or backend.actor)
        self.backend = backend
        self.vocabulary = vocabulary or []
        self.intent = intent
        self.policy = policy
        self.store = store
        self._seeds = {}
        self._graph = None
        self._graph_key = None
        self.misses = 0

    def learn_vocabulary(self, overviews):
        self.vocabulary = self.backend.vocabulary(overviews, self.intent)
        return self.vocabulary

    @staticmethod
    def _key(camera):
        return (tuple(np.round(camera.forward, 6)), round(camera.radius_mm, 4),
                tuple(np.round(camera.centre, 4)))

    def _reference_png(self, camera):
        from . import render as render_module
        from . import vision as vision_module
        return vision_module.render_png(render_module.render_bundle(
            self._mesh, camera, "zenithal", self._frame))

    def prefetch(self, cameras, workers=6):
        """Look at a whole round's cameras at once.

        Each call is a separate subprocess taking about twenty seconds, so serially a
        forty-view round spends thirteen minutes doing nothing but waiting. The calls are
        independent by construction -- §10 says the region agent is never told about
        other views -- so running them concurrently changes the wall clock and nothing
        else about the evidence.
        """
        from concurrent.futures import ThreadPoolExecutor
        wanted = [camera for camera in cameras if self._key(camera) not in self._seeds]
        if not wanted:
            return 0
        images = [(self._key(camera), self._reference_png(camera))
                  for camera in wanted]

        def fetch(item):
            key, png = item
            return key, self.backend.seeds(png, self.vocabulary, self.intent)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for key, found in pool.map(fetch, images):
                self._seeds[key] = found
        return len(wanted)

    def seeds_for(self, bundle):
        """Cached per camera, so every rig and band of one camera shares one look."""
        camera = bundle["camera"]
        key = self._key(camera)
        if key not in self._seeds:
            from . import vision as vision_module
            reference = bundle if bundle["rig"] == "zenithal" \
                else None
            png = vision_module.render_png(reference) if reference is not None \
                else self._reference_png(camera)
            self._seeds[key] = self.backend.seeds(png, self.vocabulary, self.intent)
        return self._seeds[key]

    def bind(self, mesh, frame):
        """The mesh and frame needed to re-render the reference rig on demand."""
        self._mesh, self._frame = mesh, frame
        return self

    def propose(self, bundle, band, tree=None):
        from . import vision as vision_module
        known = {part["label"] for part in self.vocabulary}
        seeds, confidence = {}, {}
        for entry in self.seeds_for(bundle):
            label = entry.get("label", "")
            if label not in known:
                # A label outside the vocabulary cannot be fused with anything, because
                # no other view will produce it. Dropping it is recorded rather than
                # silent -- a vocabulary that keeps getting ignored is a finding.
                self.misses += 1
                if self.store is not None:
                    self.store.reject("proposal",
                                      "label %r is not in the vocabulary" % label,
                                      count=1)
                continue
            points = [(int(p[0]), int(p[1])) for p in entry.get("points", [])
                      if len(p) >= 2]
            if not points:
                continue
            seeds[label] = points
            confidence[label] = float(entry.get("confidence", 0.5))
        if not seeds:
            return
        spreads = {label: vision_module.seed_extent_mm(bundle, points)
                   for label, points in seeds.items()}
        # The barrier map and the pixel graph depend on the bundle and the band, not on
        # which part is being grown, so every label at this band shares one of each.
        graph = self._graph_for(bundle, band)
        masks = vision_module.synthesise_masks(bundle, band, seeds, self.policy,
                                               graph=graph, spread_by_label=spreads)
        for label, mask in masks.items():
            if mask.max() <= 0:
                continue
            yield (label, mask * confidence[label])

    def _graph_for(self, bundle, band):
        from . import vision as vision_module
        key = (self._key(bundle["camera"]), band.index)
        if key != self._graph_key:
            barrier = vision_module.barrier_map(bundle, band)
            self._graph = vision_module.pixel_graph(bundle, barrier)
            self._graph_key = key
        return self._graph


class Critic(Agent):
    """field rendered back + region stats -> tree edits.

    Asks the only two questions that matter: would a PERSON name this, and would a
    person PAINT IT SEPARATELY. A region that fails both is a measurement, not a part.
    """

    name = "critic"

    def review(self, field, radius_mm, policy):
        edits = []
        posterior = field.posterior(radius_mm)
        for index, node_id in enumerate(field.labels):
            share = posterior[index]
            mass = float(np.sum(share * field.vertex_area))
            fraction = mass / max(field.total_area_mm2, 1e-9)
            peak = float(share.max()) if share.size else 0.0
            if peak < policy.posterior_floor:
                edits.append((node_id, "drop",
                              "never reaches the posterior floor anywhere"))
            elif fraction < 1e-4:
                edits.append((node_id, "merge", "too little area to name"))
        # Containment: a child should be a near-subset of its parent (§8.4).
        return {"edits": edits, "checked": len(field.labels)}


class Painter(Agent):
    """regions + brief + cues -> Lab colour + paint role.

    Works in CONTINUOUS colour; the palette does not exist to it. Handing the painter a
    palette makes it solve two problems at once -- what should this look like, and what
    can I buy -- and the second one is the limiter's job (§11), which can do it with
    contrast constraints the painter has no way to check.
    """

    name = "painter"

    ROLES = ("base", "shade", "highlight", "accent")

    def colour(self, field, labels, radius_mm, intent=""):
        scheme = []
        for order, node_id in enumerate(labels):
            role = self._role_for(node_id, order)
            scheme.append({"region": node_id, "role": role,
                           "lab": self._lab_for(role, order),
                           "actor": self.actor})
        return scheme

    def _role_for(self, node_id, order):
        if "recess" in node_id:
            return "shade"
        if "relief" in node_id:
            return "highlight"
        return "base" if order == 0 else "accent"

    def _lab_for(self, role, order):
        # Continuous Lab, spread by role. A model agent replaces this with a reading of
        # the brief; the structure -- lightness carries role -- is what §11 relies on.
        lightness = {"shade": 28.0, "base": 62.0, "highlight": 88.0, "accent": 52.0}
        return (lightness[role], 0.0 + 6.0 * ((order % 3) - 1), 0.0)


class VisionPainter(Painter):
    """The Painter of §10, backed by a vision model that has looked at the object.

    IT WORKS IN CONTINUOUS COLOUR AND THE PALETTE DOES NOT EXIST TO IT. That is §10's
    rule and it is load-bearing: handing the painter the four filaments makes it solve
    two problems at once -- what should this look like, and what can I actually lay down
    -- and the second is the limiter's job (§11), under contrast constraints at a viewing
    distance the painter has no way to check.

    An earlier version of this class did tell the painter the printer had four inks,
    reasoning that four fixed points is a medium rather than a catalogue. That was wrong
    twice over: it collapsed the two decisions the spec deliberately separates, and it
    threw away the thing that makes the limiter's output judgeable -- an unconstrained
    scheme to compare it against. Colour beautifully, then constrain, and keep both.
    """

    name = "vision_painter"

    def __init__(self, backend, actor=None):
        super().__init__(actor or backend.actor)
        self.backend = backend

    def colour(self, field, labels, radius_mm, intent="", vocabulary=None,
               overviews=None):
        if not hasattr(self.backend, "_run"):
            return super().colour(field, labels, radius_mm, intent)
        notes = {part["label"]: part.get("note", "") for part in (vocabulary or [])}
        lines = "\n".join("- %s: %s" % (label, notes.get(label, "")) for label in labels)
        prompt = (
            "You are choosing the paint scheme for a display piece, working in FULL "
            "COLOUR with no restrictions. Ignore what any printer or paint range can "
            "do -- that is somebody else's problem later. Choose the colours this object "
            "should be.\n\n"
            "The regions found on the model, with what each one is:\n%s\n\n"
            "What the piece is: %s\n\n"
            "Give each region a colour that makes the finished piece look like the real "
            "thing, and beautiful. Think like a painter:\n"
            "- Let the material speak. Wet weed is not the same green as dry weed; "
            "old shell is not white, it is a dozen warm off-whites.\n"
            "- Put the strongest saturation where it earns attention, and keep the rest "
            "restrained so it reads.\n"
            "- Neighbouring regions need enough separation in value, not just in hue, "
            "or the form flattens out.\n"
            "- `role` is one of base, shade, highlight, accent.\n\n"
            'Reply with ONLY a JSON object, no prose and no code fences:\n'
            '{"regions": [{"label": str, "hex": "#RRGGBB", "role": str, "why": str}]}'
            % (lines, intent or "not stated"))
        paths = []
        if overviews:
            import os
            for index, image in enumerate(overviews):
                path = os.path.join(self.backend.directory, "painter-%d.png" % index)
                with open(path, "wb") as handle:
                    handle.write(image)
                paths.append(path)
        answer = self.backend._run(paths, prompt, "painter-scheme")
        if not answer:
            return super().colour(field, labels, radius_mm, intent)
        chosen = {entry["label"]: entry for entry in answer.get("regions", [])}
        scheme = []
        for order, label in enumerate(labels):
            entry = chosen.get(label) or {}
            lab = _hex_to_lab(entry.get("hex", "#808080"))
            scheme.append({"region": label, "role": entry.get("role", "base"),
                           "lab": lab, "hex": entry.get("hex", "#808080"),
                           "why": entry.get("why", ""), "actor": self.actor})
        return scheme


def _hex_to_lab(value):
    from colour import sRGB_to_XYZ, XYZ_to_Lab
    value = (value or "").strip().lstrip("#")
    if len(value) != 6:
        value = "808080"
    try:
        rgb = np.array([int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4)])
    except ValueError:
        rgb = np.array([0.5, 0.5, 0.5])
    return tuple(float(v) for v in XYZ_to_Lab(sRGB_to_XYZ(rgb)))


DEFAULT_AGENTS = {"planner": Planner(), "identity": Identity(), "region": Region(),
                  "critic": Critic(), "painter": Painter()}
