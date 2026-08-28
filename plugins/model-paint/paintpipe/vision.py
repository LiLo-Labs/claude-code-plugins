"""Vision backends and mask synthesis for the Region agent (spec §10, §12 vision ops).

A vision model cannot paint a pixel mask, and asking it to is the usual way this goes
wrong. What it can do reliably is LOOK at a render and say what it sees and roughly
where. So the work splits:

    the model   names parts and points at them -- a label and a few pixel coordinates
    this module grows each point into a fuzzy mask through the cue maps

The masks are approximate on purpose. §7 weights every pixel by how well that view
resolved it and §8 fuses across every camera, rig and band, so a seed that lands badly in
one view is outvoted rather than believed. Nothing here has to be right; it has to be
unbiased and to carry its confidence honestly.

LABEL CONSISTENCY IS THE THING THAT MAKES FUSION POSSIBLE. Two views that call the same
feature "barnacle cluster" and "barnacles" produce two regions that never reinforce each
other, and thirty views produce thirty. So the vocabulary is fixed ONCE by the identity
agent on overview renders (§4.2, §10) and every per-view proposal must choose from it.
"""

import base64
import io
import json
import os

import numpy as np

from . import cues as cue_module


# --------------------------------------------------------------------------- masks

def barrier_map(bundle, band):
    """Where the cues see an edge. Shared by every label at this band.

    Computed once per (bundle, band) and handed to every mask. It used to be computed
    inside the flood, so six labels at two bands recomputed the same two maps twelve
    times -- most of the cost of a bundle, spent re-deriving something that does not
    depend on which part is being grown.
    """
    silhouette, _ = cue_module.silhouette(bundle, band.wavelength_mm)
    ridge, _ = cue_module.ridge(bundle, band.wavelength_mm)
    return np.clip(np.nan_to_num(silhouette) + np.nan_to_num(ridge), 0.0, 1.0)


def pixel_graph(bundle, barrier):
    """A 4-neighbour graph over the visible pixels, weighted by boundary strength.

    Built ONCE per (bundle, band) and reused by every label, because the graph is a
    property of the image and not of which part is being grown. Costs are in
    millimetres: one footprint of travel, plus a penalty for crossing an edge the cues
    can see, so a flood's allowance means what it says.
    """
    import scipy.sparse as sparse
    visible = bundle["visible"]
    height, width = visible.shape
    index = np.full(visible.shape, -1, dtype=np.int64)
    index[visible] = np.arange(int(visible.sum()))
    footprint = bundle["camera"].footprint_mm
    weight = footprint * (1.0 + 8.0 * barrier)

    rows, cols, data = [], [], []
    for dy, dx in ((0, 1), (1, 0)):
        here = index[: height - dy, : width - dx]
        there = index[dy:, dx:]
        both = (here >= 0) & (there >= 0)
        if not both.any():
            continue
        a, b = here[both], there[both]
        # Cost of the step is the mean of the two endpoints' local weights, so crossing
        # into a boundary pixel costs the same as crossing out of one.
        cost = 0.5 * (weight[: height - dy, : width - dx][both]
                      + weight[dy:, dx:][both])
        rows.extend((a, b))
        cols.extend((b, a))
        data.extend((cost, cost))
    count = int(visible.sum())
    graph = sparse.coo_matrix(
        (np.concatenate(data), (np.concatenate(rows), np.concatenate(cols))),
        shape=(count, count)).tocsr()
    return graph, index


def contest_masks(bundle, band, seeds_by_label, policy, barrier=None, graph=None,
                  spread=None, spread_by_label=None):
    """Every label races for the surface. Returns {label: confidence map}.

    A LABEL'S EXTENT IS SET BY ITS COMPETITORS, NOT BY A LENGTH SOMEBODY CHOSE. For each
    pixel, measure the barrier-weighted geodesic distance to the nearest seed of this
    label (d1) and to the nearest seed of any OTHER label (d2), and take

        confidence = (d2 - d1) / (d2 + d1)

    which is dimensionless, needs no constant, and is 1 deep inside a label's own basin,
    0 on the seam between two labels, and negative beyond it. Where a competitor arrives
    first, this label simply stops -- no reach parameter, no decay length.

    THIS REPLACES AN UNBOUNDED FLOOD, and the flood was the whole defect. It ran one
    multi-source solve per label with `min_only`, which is a UNION: each of a label's
    seeds is an independent chance to leak across a weak barrier, with nothing opposing
    it. Smear therefore scaled with instance count by construction, which is exactly what
    the isolation report measured -- `tail fin` with one instance came back 5 connected
    pieces at 96% in the largest, while `clawed feet` with four came back 447 pieces
    across a quarter of the model. Three successive definitions of `spread` were tried
    and all three failed, because an unopposed flood has no correct length: the constant
    was never the bug, the union was.

    A race has no such asymmetry. Four feet do not reach further than one, because what
    stops each foot is where the leg and body fronts arrive, and that does not grow with
    the number of feet.
    """
    visible = bundle["visible"]
    labels = [label for label, points in seeds_by_label.items() if points]
    if not visible.any() or not labels:
        return {}
    if graph is None:
        if barrier is None:
            barrier = barrier_map(bundle, band)
        graph, index = pixel_graph(bundle, barrier)
    else:
        graph, index = graph

    height, width = visible.shape

    def nodes_for(points):
        out = []
        for x, y in points:
            if 0 <= y < height and 0 <= x < width and index[y, x] >= 0:
                out.append(int(index[y, x]))
        return out

    by_label = {label: nodes_for(seeds_by_label[label]) for label in labels}
    by_label = {label: nodes for label, nodes in by_label.items() if nodes}
    if len(by_label) == 1:
        # Nothing to race against. One label alone owns whatever it can reach, which is
        # the honest answer -- a single label in a view carries no boundary information.
        label = next(iter(by_label))
        confidence = np.zeros(visible.shape)
        confidence[visible] = 1.0
        return {label: confidence}

    from scipy.sparse.csgraph import dijkstra
    out = {}
    for label, nodes in by_label.items():
        others = [n for other, group in by_label.items() if other != label
                  for n in group]
        mine = dijkstra(graph, directed=False, indices=nodes, min_only=True)
        theirs = dijkstra(graph, directed=False, indices=others, min_only=True)
        total = mine + theirs
        margin = np.zeros(len(mine))
        live = np.isfinite(total) & (total > 0)
        margin[live] = (theirs[live] - mine[live]) / total[live]
        # Unreachable for everyone: nobody claims it. Reachable only by this label:
        # it owns it, which is what an infinite competitor distance means.
        only_mine = np.isfinite(mine) & ~np.isfinite(theirs)
        margin[only_mine] = 1.0
        confidence = np.zeros(visible.shape)
        confidence[visible] = np.clip(margin, 0.0, 1.0)
        out[label] = confidence
    return out


# Kept as the name the rest of the package calls; the mechanism is the race above.
synthesise_masks = contest_masks


def synthesise_mask(bundle, band, seeds, policy, spread=None, barrier=None, graph=None):
    """Single-label convenience wrapper. With no competitor there is no contest."""
    found = contest_masks(bundle, band, {"_": list(seeds)}, policy, barrier, graph)
    return found.get("_", np.zeros(bundle["visible"].shape))


# ------------------------------------------------------------------------ backends

class VisionBackend:
    """Contract: overviews -> vocabulary; one bundle -> named seeds."""

    actor = "deterministic:vision@0.2.0"

    def vocabulary(self, overviews, intent):
        raise NotImplementedError

    def seeds(self, image_png, vocabulary, intent, view_note=""):
        raise NotImplementedError


class CueBackend(VisionBackend):
    """The null backend: no model, cue channels as labels.

    Kept because it is the honest floor of what the pipeline does with nothing attached,
    and because every other backend must beat it to justify its cost. It records itself
    as deterministic so no downstream stage can mistake it for a model's opinion.
    """

    actor = "deterministic:cue-backend@0.2.0"

    def vocabulary(self, overviews, intent):
        return [{"label": "recess", "note": "where shade collects"},
                {"label": "relief", "note": "edges that catch light"},
                {"label": "field", "note": "continuous surface"}]

    def seeds(self, image_png, vocabulary, intent, view_note=""):
        return []


SEED_SCHEMA = {
    "type": "object",
    "properties": {
        "regions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "points": {
                        "type": "array",
                        "items": {"type": "array",
                                  "items": {"type": "integer"},
                                  "minItems": 2, "maxItems": 2},
                    },
                    "confidence": {"type": "number"},
                },
                "required": ["label", "points", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["regions"],
    "additionalProperties": False,
}

VOCAB_SCHEMA = {
    "type": "object",
    "properties": {
        "object": {"type": "string"},
        "parts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "note": {"type": "string"},
                    "parent": {"type": "string"},
                },
                "required": ["label", "note", "parent"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["object", "parts"],
    "additionalProperties": False,
}

DESCRIBE_PROMPT = """You are studying orthographic renders of one 3D model, shown \
upright from several angles, before anyone names its parts. Work out what this \
object actually IS -- not a guess from one view, but a reading that survives all \
of them.

Report:
- identity: two to four sentences on what the object is, its overall form, and \
which direction it faces.
- landmarks: the distinct anatomical or structural features you are SURE of, \
each with where it sits on the object.
- cautions: look-alike traps on THIS model -- surface folds that mimic a face, \
sockets that mimic eyes, anything a labeller in a hurry would get wrong, and \
what each such region really is.

If the person's own description (below) conflicts with what the renders show, \
trust the renders and say so in cautions.

Reply with ONLY a JSON object, no prose, no code fences:
{"identity": str, "landmarks": [{"what": str, "where": str}], "cautions": str}"""


VOCAB_PROMPT = """You are looking at orthographic renders of one 3D model from several \
directions, lit from above as it would be primed for painting.

Name the parts a MINIATURE PAINTER would treat separately -- the areas they would give \
different colours, shades or highlights. Use the words a painter would use, not \
geometric ones: "barnacle colonies", "rock base", "shell ribs", not "convex region A".

Rules that matter:
- Name a part only if you would paint it differently from what surrounds it.
- Prefer few, real parts over many speculative ones. A part you name here must be \
findable in individual views later; one that is never found is recorded as absent.
- Include parts that appear in only some views.
- `parent` is another label from your own list, or "" for a top-level part.
- `material` names what the part is made of on the depicted thing -- skin, horn, \
bone, eye, teeth, cloth, rock, shell, scale. Parts sharing a material are normally \
PAINTED ALIKE: a bald crown is the same skin as the cheeks, and a recess in skin is \
still skin (shadow does the separating, not pigment). Reserve distinct materials for \
parts that genuinely differ in substance.
- `expected_count` is how many separate instances of this part the OBJECT has -- 2 \
for paired eyes or horns, 4 for a quadruped's hooves, a number for repeated studs or \
segments you can count, null when genuinely unknowable. This is anatomy, not a guess \
quota: it lets later stages notice a missing second eye or a part shattered far \
beyond its real count."""

SEED_PROMPT = """You are looking at ONE orthographic render of a 3D model, lit as it \
would be primed for painting. The image is {size} by {size} pixels.

For each part from the vocabulary that is VISIBLE in this view, give a few pixel \
coordinates that land clearly INSIDE it -- on the part itself, not on its edge and not \
on its neighbour. Three or four well-placed points beat twenty scattered ones.

Rules that matter:
- Use ONLY labels from the vocabulary, spelled exactly as given.
- Omit any part you cannot see in this view. Omitting is correct and costs nothing; \
guessing pollutes the evidence.
- `confidence` is how sure you are that this part is present here, from 0 to 1. Say 0.4 \
when you half-see it; do not round yourself up.
- Coordinates are [x, y] with [0, 0] at the TOP-LEFT."""


class AnthropicBackend(VisionBackend):
    """Claude with vision, via the Anthropic SDK.

    Structured outputs are used rather than prose parsing, so a malformed answer is a
    validation error at the API boundary instead of a silent mis-parse thirty views
    later. Adaptive thinking is on because placing a point inside a small part in a
    cluttered render is exactly the kind of judgement that benefits from it.
    """

    def __init__(self, model="claude-opus-5", client=None, effort="high"):
        self.model = model
        self.effort = effort
        self._client = client
        self.actor = "llm:%s@vision" % model

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def _ask(self, images, prompt, schema, max_tokens=16000):
        content = []
        for image in images:
            content.append({"type": "image",
                            "source": {"type": "base64", "media_type": "image/png",
                                       "data": base64.standard_b64encode(image)
                                       .decode("utf-8")}})
        content.append({"type": "text", "text": prompt})
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort,
                           "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": content}],
        )
        if response.stop_reason == "refusal":
            return None
        text = next(block.text for block in response.content if block.type == "text")
        return json.loads(text)

    def vocabulary(self, overviews, intent):
        prompt = VOCAB_PROMPT
        if intent:
            prompt += "\n\nWhat the painter said they want: %s" % intent
        answer = self._ask(overviews, prompt, VOCAB_SCHEMA)
        return [] if answer is None else answer["parts"]

    def seeds(self, image_png, vocabulary, intent, view_note=""):
        size = 0
        try:
            from PIL import Image
            size = Image.open(io.BytesIO(image_png)).size[0]
        except Exception:
            size = 0
        prompt = SEED_PROMPT.format(size=size)
        prompt += "\n\nVocabulary:\n" + "\n".join(
            "- %s: %s" % (part["label"], part.get("note", "")) for part in vocabulary)
        if view_note:
            prompt += "\n\n%s" % view_note
        answer = self._ask([image_png], prompt, SEED_SCHEMA)
        return [] if answer is None else answer["regions"]


class SessionBackend(VisionBackend):
    """Ask whichever agent is running the session to do the looking.

    There is not always an API key, and in a Claude Code session there is something
    better: an agent that can open a PNG and read it. This backend writes each render
    and its question to disk and reads the answer back from a JSON file beside it. The
    loop is resumable, every answer is cached by the bundle's own digest, and the
    prompts are the same ones the API backend sends -- so the two are comparable rather
    than merely both present.
    """

    actor = "agent:session@vision"

    def __init__(self, directory, on_missing="skip"):
        self.directory = directory
        self.on_missing = on_missing
        os.makedirs(directory, exist_ok=True)
        self.pending = []

    def _slot(self, key):
        return (os.path.join(self.directory, "%s.png" % key),
                os.path.join(self.directory, "%s.request.txt" % key),
                os.path.join(self.directory, "%s.answer.json" % key))

    def _answer(self, key, images, prompt, empty):
        image_path, request_path, answer_path = self._slot(key)
        if os.path.exists(answer_path):
            with open(answer_path) as handle:
                return json.load(handle)
        for index, image in enumerate(images):
            path = image_path if len(images) == 1 else image_path.replace(
                ".png", "-%d.png" % index)
            with open(path, "wb") as handle:
                handle.write(image)
        with open(request_path, "w") as handle:
            handle.write(prompt)
        self.pending.append(key)
        if self.on_missing == "raise":
            raise LookupError("no answer yet for %s; look at %s and write %s"
                              % (key, image_path, answer_path))
        return empty

    def vocabulary(self, overviews, intent):
        prompt = VOCAB_PROMPT
        if intent:
            prompt += "\n\nWhat the painter said they want: %s" % intent
        answer = self._answer("vocabulary", overviews, prompt, {"parts": []})
        return answer.get("parts", [])

    def seeds(self, image_png, vocabulary, intent, view_note=""):
        from . import entities as entities_module
        key = "view-%s" % entities_module.digest_of(image_png)[7:19]
        prompt = SEED_PROMPT.format(size=0)
        prompt += "\n\nVocabulary:\n" + "\n".join(
            "- %s: %s" % (part["label"], part.get("note", "")) for part in vocabulary)
        if view_note:
            prompt += "\n\n%s" % view_note
        answer = self._answer(key, [image_png], prompt, {"regions": []})
        return answer.get("regions", [])


class HeadlessBackend(VisionBackend):
    """Claude Code in headless mode (`claude -p`), which needs no API key.

    The session already holds credentials, and `claude -p --allowed-tools Read` will
    open a PNG and answer about it. That makes the vision agent available wherever the
    pipeline runs inside Claude Code, which is where it runs.

    Two things are not optional, both learned by getting them wrong:

    **The model must be named.** The default is Sonnet, and on a grey shaded render of a
    shell it confidently returned "tattered cloak/fringe edge", "main robe/drapery
    folds" and "face/mask area" -- a robed figure that is not there. Opus 5 on the same
    image returns the ribbed shell wall, the barnacle clusters and the rock base.

    **The painter's intent must be passed.** An untextured grey render is genuinely
    ambiguous, and the brief is the cheapest disambiguation available. It is the user's
    own words, so using them costs nothing and anchors every later view.

    Answers are cached on disk by the image's own digest, so a re-run costs nothing and
    a crashed run resumes.
    """

    actor = "llm:claude-opus-5@headless"

    def __init__(self, directory, model="claude-opus-5", timeout=600,
                 executable="claude"):
        self.directory = directory
        self.model = model
        self.timeout = timeout
        self.executable = executable
        self.actor = "llm:%s@headless" % model
        self.calls = 0
        self.failures = 0
        self.cost_usd = 0.0
        os.makedirs(directory, exist_ok=True)

    def _run(self, image_paths, prompt, cache_key):
        import subprocess
        from . import entities as entities_module
        cached = os.path.join(self.directory, "%s.json" % cache_key)
        if os.path.exists(cached):
            with open(cached) as handle:
                return json.load(handle)
        full = "%s\n\nImages to read:\n%s" % (prompt, "\n".join(image_paths))
        command = [self.executable, "-p", full, "--allowed-tools", "Read",
                   "--model", self.model, "--output-format", "json"]
        try:
            finished = subprocess.run(command, capture_output=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self.failures += 1
            self._log_failure(cache_key, "timeout after %ss" % self.timeout)
            return None
        self.calls += 1
        if finished.returncode != 0:
            self.failures += 1
            self._log_failure(cache_key, "exit %d\nstderr: %s\nstdout: %s"
                              % (finished.returncode,
                                 finished.stderr.decode("utf-8", "replace")[:2000],
                                 finished.stdout.decode("utf-8", "replace")[:500]))
            return None
        try:
            envelope = json.loads(finished.stdout.decode("utf-8", "replace"))
        except ValueError:
            self.failures += 1
            self._log_failure(cache_key, "unparseable stdout: %s"
                              % finished.stdout.decode("utf-8", "replace")[:2000])
            return None
        self.cost_usd += float(envelope.get("total_cost_usd", 0.0) or 0.0)
        answer = _loads_lenient(envelope.get("result", ""))
        if answer is None:
            self.failures += 1
            return None
        with open(cached, "w") as handle:
            json.dump(answer, handle)
        return answer

    def _log_failure(self, cache_key, text):
        """A failed call leaves a note instead of silence. Silence cost a debugging
        round: fifteen views came back with zero votes and nothing said why."""
        with open(os.path.join(self.directory, "%s.failed.txt" % cache_key), "w") as f:
            f.write(text)

    def describe(self, overviews, intent):
        """The identity dossier: what the object IS, studied before any part
        is named, with explicit cautions about this model's look-alike traps.
        Its text is folded into every downstream ask."""
        from . import entities as entities_module
        paths = []
        for index, image in enumerate(overviews):
            path = os.path.join(self.directory, "study-%d.png" % index)
            with open(path, "wb") as handle:
                handle.write(image)
            paths.append(path)
        prompt = DESCRIBE_PROMPT
        if intent:
            prompt += "\n\nWhat the person said about the piece: %s" % intent
        key = "describe-%s" % entities_module.digest_of(
            prompt.encode("utf-8") + b"".join(overviews))[7:19]
        answer = self._run(paths, prompt, key)
        return answer or {}

    def vocabulary(self, overviews, intent):
        from . import entities as entities_module
        paths = []
        for index, image in enumerate(overviews):
            path = os.path.join(self.directory, "overview-%d.png" % index)
            with open(path, "wb") as handle:
                handle.write(image)
            paths.append(path)
        prompt = VOCAB_PROMPT
        if intent:
            prompt += "\n\nWhat the painter said they want: %s" % intent
        prompt += ("\n\nReply with ONLY a JSON object, no prose and no code fences:\n"
                   '{"object": str, "parts": [{"label": str, "note": str, '
                   '"parent": str, "material": str, '
                   '"expected_count": int or null}]}')
        # Keyed by the question: a changed intent or changed overviews must
        # re-ask, not replay the first vocabulary this directory ever saw.
        key = "vocabulary-%s" % entities_module.digest_of(
            prompt.encode("utf-8") + b"".join(overviews))[7:19]
        answer = self._run(paths, prompt, key)
        return [] if answer is None else answer.get("parts", [])

    def seeds(self, image_png, vocabulary, intent, view_note=""):
        from . import entities as entities_module
        key = "view-%s" % entities_module.digest_of(image_png)[7:19]
        path = os.path.join(self.directory, "%s.png" % key)
        if not os.path.exists(path):
            with open(path, "wb") as handle:
                handle.write(image_png)
        size = 0
        try:
            from PIL import Image
            size = Image.open(io.BytesIO(image_png)).size[0]
        except Exception:
            pass
        prompt = SEED_PROMPT.format(size=size)
        if intent:
            prompt += "\n\nWhat the painter said they want: %s" % intent
        prompt += "\n\nVocabulary:\n" + "\n".join(
            "- %s: %s" % (part["label"], part.get("note", "")) for part in vocabulary)
        if view_note:
            prompt += "\n\n%s" % view_note
        prompt += ("\n\nReply with ONLY a JSON object, no prose and no code fences:\n"
                   '{"regions": [{"label": str, "points": [[x, y]], '
                   '"confidence": float}]}')
        answer = self._run([path], prompt, key)
        return [] if answer is None else answer.get("regions", [])


def _loads_lenient(text):
    """Parse JSON that may arrive wrapped in prose or a code fence.

    The API backend uses structured outputs and needs none of this. Headless mode has no
    such guarantee, and a run that dies on a stray code fence after forty views has
    thrown away real work.
    """
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except ValueError:
        return None


def render_png(bundle, background=1.0):
    """The lit render as PNG bytes -- what the vision model actually looks at."""
    from PIL import Image
    lit = np.where(bundle["visible"], np.clip(bundle["rgb_lit"], 0.0, 1.0), background)
    image = Image.fromarray((lit * 255).astype(np.uint8)).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
