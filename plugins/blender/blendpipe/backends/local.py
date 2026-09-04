"""Your own hardware, behind a small HTTP endpoint.

This is the backend the paid ones are meant to be replaced by. It is not a stub:
it speaks a deliberately tiny contract that any of the open-weight generators
(Hunyuan3D, TRELLIS, TripoSR, whatever comes next) can be wrapped in with about
thirty lines of FastAPI, so the choice of model stays yours and does not become
another thing this plugin has an opinion about.

The contract
------------
    POST $BLENDPIPE_LOCAL_URL/generate   {"prompt": str, "options": {...}}

and reply with any one of:

    {"path": "/abs/path/on/this/machine.glb"}   # cheapest — no bytes move
    {"url":  "http://host/result.glb"}          # fetched
    {"job":  "abc123"}                          # polled at /status/abc123
                                                #   until {"done": true, ...}

`path` is the good one when the server shares a filesystem with Claude Code,
which is the usual case for a GPU box you run yourself. There is no auth in the
contract on purpose: this is expected to be bound to localhost or a private
network, and inventing a token scheme here would be security theatre.
"""

import os
import shutil

from .base import BackendError, GenerationResult, MeshBackend, download, http_json, poll


class LocalBackend(MeshBackend):
    name = "local"
    kind = "your hardware"
    cost_hint = 0.0

    def __init__(self):
        self.url = (os.environ.get("BLENDPIPE_LOCAL_URL") or "").rstrip("/")

    def available(self):
        return bool(self.url)

    def why_unavailable(self):
        return (
            "set BLENDPIPE_LOCAL_URL to your own generator, e.g. http://127.0.0.1:8000 "
            "(see docs/local-backend.md for the endpoint contract)"
        )

    def generate(self, prompt, out_dir, image=None, options=None):
        options = dict(options or {})
        if image:
            options["image"] = image

        reply = http_json(
            "%s/generate" % self.url,
            method="POST",
            payload={"prompt": prompt, "options": options},
            timeout=int(options.get("submit_timeout", 120)),
        )

        if reply.get("job"):
            reply = poll(
                lambda: self._check(reply["job"]),
                timeout=int(options.get("timeout", 1800)),
                interval=3,
                label="local generation",
            )

        return GenerationResult(self._materialise(reply, out_dir), self.name, {"prompt": prompt})

    def _check(self, job):
        state = http_json("%s/status/%s" % (self.url, job), timeout=30)
        if state.get("error"):
            raise BackendError("local generator failed: %s" % state["error"])
        return state if state.get("done") else None

    def _materialise(self, reply, out_dir):
        """Get the result onto local disk however the server offered it."""
        os.makedirs(out_dir, exist_ok=True)
        if reply.get("path"):
            source = os.path.expanduser(reply["path"])
            if not os.path.isfile(source):
                raise BackendError(
                    "local generator reported %s but nothing is there — it is probably "
                    "on a different machine, return a 'url' instead" % source
                )
            target = os.path.join(out_dir, os.path.basename(source))
            # Copied rather than referenced: everything downstream assumes the
            # mesh sits in the run directory beside its renders and its report.
            if os.path.abspath(source) != os.path.abspath(target):
                shutil.copy2(source, target)
            return target
        if reply.get("url"):
            name = os.path.basename(reply["url"].split("?", 1)[0]) or "local.glb"
            return download(reply["url"], os.path.join(out_dir, name))
        raise BackendError("local generator replied with neither 'path' nor 'url': %r" % reply)
