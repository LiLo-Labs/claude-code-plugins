"""The agent, and the one way this asks it anything.

Answers are cached on the image's own digest, so a re-run costs nothing and a
crashed run resumes where it stopped. That the key is the CONTENT and not the
filename matters: keying on the path replayed a stale refusal about a picture
that had since changed.
"""

import json
import os

class VisionBackend:
    """Contract: overviews -> vocabulary; one bundle -> named seeds."""

    actor = "deterministic:vision@0.2.0"

    def vocabulary(self, overviews, intent):
        raise NotImplementedError

    def seeds(self, image_png, vocabulary, intent, view_note=""):
        raise NotImplementedError


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
