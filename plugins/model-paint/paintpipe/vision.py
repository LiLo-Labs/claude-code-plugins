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


def synthesise_masks(bundle, band, seeds_by_label, policy, spread=None, barrier=None,
                     graph=None):
    """Grow every label's seeds at once. Returns {label: confidence map}.

    Geodesic distance in the image, over a graph whose edge costs are the local boundary
    strength, so a seed spreads across a smooth face and stops at the edge of the feature
    it sits in without anyone choosing a threshold. Confidence falls exponentially with
    that distance over the band's own wavelength.

    Solved with scipy's Dijkstra rather than by relaxation sweeps. An isotropic sweep
    moves information one pixel at a time, so reaching across a feature fifty pixels wide
    took fifty passes over the whole image -- and that was repeated for each of twelve
    label-band pairs, which was most of what a bundle cost.

    Labels share the graph but keep INDEPENDENT masks rather than partitioning the image:
    §10 says the region agent is never forced to partition, and a watershed would force
    exactly that, discarding the overlap §8.4 exists to measure.
    """
    visible = bundle["visible"]
    labels = [label for label, points in seeds_by_label.items() if points]
    if not visible.any() or not labels:
        return {}

    spread_mm = float(spread if spread is not None else band.wavelength_mm)
    if graph is None:
        if barrier is None:
            barrier = barrier_map(bundle, band)
        graph, index = pixel_graph(bundle, barrier)
    else:
        graph, index = graph

    from scipy.sparse.csgraph import dijkstra
    height, width = visible.shape
    out = {}
    for label in labels:
        sources = []
        for x, y in seeds_by_label[label]:
            if 0 <= y < height and 0 <= x < width and index[y, x] >= 0:
                sources.append(int(index[y, x]))
        if not sources:
            continue
        # A mask expresses ONE part, and a part's extent is the band it lives at. The
        # confidence is exp(-d / spread), so past about two and a half spreads it is
        # under a percent and adds nothing but reach.
        #
        # This was 6x when the flood was first ported to Dijkstra, and it was a real
        # regression: the relaxation it replaced had capped travel at spread/footprint
        # sweeps, roughly one wavelength, while 6x let every seed on the shell flood
        # 49.6mm across a 110mm object. Eighty views then produced flat claims that
        # ignored the surface entirely -- worse than the twelve-view run had been. Speed
        # is not worth a quantity changing behind a rewrite.
        distance = dijkstra(graph, directed=False, indices=sources, min_only=True,
                            limit=spread_mm * 2.5)
        confidence = np.zeros(visible.shape)
        reached = np.isfinite(distance)
        if reached.any():
            values = np.zeros(len(distance))
            values[reached] = np.exp(-distance[reached] / max(spread_mm, 1e-9))
            confidence[visible] = values
        out[label] = confidence
    return out


def synthesise_mask(bundle, band, seeds, policy, spread=None, barrier=None):
    """Single-label convenience wrapper over `synthesise_masks`."""
    found = synthesise_masks(bundle, band, {"_": list(seeds)}, policy, spread, barrier)
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
- `parent` is another label from your own list, or "" for a top-level part."""

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
            return None
        self.calls += 1
        if finished.returncode != 0:
            self.failures += 1
            return None
        try:
            envelope = json.loads(finished.stdout.decode("utf-8", "replace"))
        except ValueError:
            self.failures += 1
            return None
        self.cost_usd += float(envelope.get("total_cost_usd", 0.0) or 0.0)
        answer = _loads_lenient(envelope.get("result", ""))
        if answer is None:
            self.failures += 1
            return None
        with open(cached, "w") as handle:
            json.dump(answer, handle)
        return answer

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
                   '"parent": str}]}')
        answer = self._run(paths, prompt, "vocabulary")
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
