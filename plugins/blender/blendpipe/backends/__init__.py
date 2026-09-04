"""Backend registry.

`BLENDPIPE_BACKEND` names the preferred backend. When it is unset, the first
*available* backend in PREFERENCE order wins — local before paid, so that the
day a GPU box comes online it takes over by being configured, without anyone
having to remember to change a setting and without silently continuing to spend
money on an API that is no longer needed.
"""

import os

from .base import BackendError, GenerationResult, MeshBackend
from .local import LocalBackend
from .paid import MeshyBackend, RodinBackend, TripoBackend

#: Cheapest-first. Ties are broken by whoever is actually configured.
PREFERENCE = (LocalBackend, TripoBackend, MeshyBackend, RodinBackend)

_BY_NAME = {cls.name: cls for cls in PREFERENCE}


def all_backends():
    return [cls() for cls in PREFERENCE]


def describe_all():
    return [backend.describe() for backend in all_backends()]


def resolve(name=None):
    """Pick a backend, or explain precisely why none can be used."""
    name = name or os.environ.get("BLENDPIPE_BACKEND")
    if name:
        cls = _BY_NAME.get(name.strip().lower())
        if cls is None:
            raise BackendError(
                "unknown backend %r; known: %s" % (name, ", ".join(sorted(_BY_NAME)))
            )
        backend = cls()
        if not backend.available():
            raise BackendError("backend %r is not usable: %s" % (name, backend.why_unavailable()))
        return backend

    for backend in all_backends():
        if backend.available():
            return backend

    raise BackendError(
        "No mesh-generation backend is configured. Either set one up:\n"
        + "\n".join("  %-6s — %s" % (b.name, b.why_unavailable()) for b in all_backends())
        + "\n\nOr skip generation entirely: procedural modelling through `execute` needs "
        "no backend at all, and is the better tool for hard-surface, architectural and "
        "modular work."
    )


__all__ = [
    "BackendError",
    "GenerationResult",
    "MeshBackend",
    "all_backends",
    "describe_all",
    "resolve",
]
