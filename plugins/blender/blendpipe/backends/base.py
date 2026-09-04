"""The contract every mesh-generation backend implements.

The whole point of this file is that the paid APIs and a future local model are
interchangeable. Nothing above this layer — not the MCP server, not the skill —
may know which one is in use. When the GPU arrives, `local.py` gets filled in and
one environment variable moves; no other file changes.

So the interface is deliberately narrow: text (and optionally an image) goes in,
a mesh file on disk comes out. Anything a specific provider does beyond that —
PBR texturing, quad remesh, style presets — is passed through `options` and
reported back in `meta`, never promoted into the interface, because the moment a
provider-specific concept becomes a required argument the abstraction is dead.
"""

import json
import os
import time
import urllib.error
import urllib.request


class BackendError(RuntimeError):
    """A backend could not produce a mesh, with a reason worth showing the user."""


class GenerationResult:
    __slots__ = ("path", "backend", "meta")

    def __init__(self, path, backend, meta=None):
        self.path = path
        self.backend = backend
        self.meta = meta or {}

    def as_dict(self):
        return {
            "path": self.path,
            "backend": self.backend,
            "bytes": os.path.getsize(self.path) if os.path.isfile(self.path) else 0,
            **self.meta,
        }


class MeshBackend:
    """Base class. Subclasses override `available`, `describe` and `generate`."""

    name = "abstract"
    #: Rough cost per generation in USD, for the caller to report before spending.
    cost_hint = None
    #: Where the money or the compute goes — shown in `list_backends`.
    kind = "unknown"

    def available(self):
        """True when this backend is configured well enough to be attempted."""
        raise NotImplementedError

    def why_unavailable(self):
        return "not configured"

    def describe(self):
        return {
            "name": self.name,
            "kind": self.kind,
            "available": self.available(),
            "cost_hint_usd": self.cost_hint,
            "detail": None if self.available() else self.why_unavailable(),
        }

    def generate(self, prompt, out_dir, image=None, options=None):
        raise NotImplementedError


# --------------------------------------------------------------------------
# Shared HTTP helpers
#
# urllib rather than requests: this server has to start inside whatever Python
# the user's Claude Code happens to run, and a missing third-party import at
# startup is a far worse failure than slightly wordier HTTP code.
# --------------------------------------------------------------------------

def http_json(url, method="GET", headers=None, payload=None, timeout=60):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Accept", "application/json")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        raise BackendError("%s %s -> HTTP %s: %s" % (method, url, exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise BackendError("cannot reach %s: %s" % (url, exc.reason)) from exc
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise BackendError("non-JSON reply from %s: %s" % (url, raw[:200])) from exc


def download(url, path, timeout=300):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response, open(path, "wb") as handle:
            while True:
                chunk = response.read(1 << 16)
                if not chunk:
                    break
                handle.write(chunk)
    except (urllib.error.URLError, OSError) as exc:
        raise BackendError("download failed from %s: %s" % (url, exc)) from exc
    if os.path.getsize(path) == 0:
        raise BackendError("downloaded an empty file from %s" % url)
    return path


def poll(check, timeout=600, interval=5, label="generation"):
    """Call `check` until it returns a truthy value, then return it.

    `check` returns None to mean "still working" and raises BackendError to fail
    fast. Every provider here is an async job API and they all need this loop, so
    it lives once rather than three times.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        outcome = check()
        if outcome is not None:
            return outcome
        time.sleep(interval)
    raise BackendError("%s did not finish within %ds" % (label, timeout))
