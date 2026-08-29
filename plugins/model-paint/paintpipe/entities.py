"""Identity (spec §2). Nothing anonymous crosses a stage boundary.

Identity is not metadata bolted onto records, it is the precondition for the other
invariants. I5 -- every belief carries its evidence -- is unenforceable without stable
observation ids. I3 -- scale is a query parameter -- is meaningless if a region cannot
be named across two query radii. Caching, replay, incremental re-runs, human correction
and the audit trail all reduce to the same requirement: everything has a name, and that
name means the same thing tomorrow.

Two kinds, answering different questions (§2.1):

    digest -- content identity. A hash over inputs and parameters. "Is this the same
              COMPUTATION?" Drives caching, dedup and bit-exact replay.
    id     -- referential identity. A ULID minted once and never reused. "Is this the
              same THING?" Survives recomputation and boundary changes. This is what a
              human points at.

Rejections are entities too (§2.3). A pixel dropped at a silhouette, a region merged
under the brush floor, a hypothesised part that never materialised: each gets a reject
id with a reason and its inputs. Anonymous discards are how pipelines become
unexplainable, and a user asking "why isn't the visor a separate colour?" must get an
answer that is a record rather than a shrug.
"""

import base64
import hashlib
import json
import os
import threading
import time

# §2.3. A kind not in this registry cannot be minted -- that is the point of a registry.
KINDS = {
    "run": "one execution end to end",
    "object": "the physical thing being painted",
    "part_mesh": "one input mesh in a multi-part kit",
    "frame": "the intrinsic frame and its axis names",
    "band": "one detail band with its wavelength",
    "policy": "the dimensionless constants file",
    "profile": "the painter's hardware",
    "tip": "one brush tip",
    "paint": "one purchasable paint",
    "rig": "a lighting setup",
    "camera": "a pose and intrinsics",
    "bundle": "the buffer set from one camera x rig",
    "cuemap": "one cue channel at one band on one bundle",
    "proposal": "one mask from a region agent, pre-fusion",
    "observation": "one admitted vote",
    "node": "a part in the hypothesis tree",
    "region": "a named area of surface at a band",
    "scheme_entry": "region + paint + role",
    "reject": "anything discarded, and why",
    "bake": "the sampled output",
    "export": "the delivered bundle",
}

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_lock = threading.Lock()
_last = (0, 0)


def _ulid():
    """Time-ordered, monotonic within a process, opaque by contract (§2.5).

    Sorting by id sorts by creation, which makes a run's log readable without a join.
    Ids are never parsed and never carry meaning beyond the kind prefix.
    """
    global _last
    with _lock:
        now = int(time.time() * 1000)
        stamp, counter = _last
        if now == stamp:
            counter += 1
        else:
            stamp, counter = now, int.from_bytes(os.urandom(5), "big")
        _last = (stamp, counter)
    value = (stamp << 80) | (counter & ((1 << 80) - 1))
    out = []
    for shift in range(125, -1, -5):
        out.append(_CROCKFORD[(value >> shift) & 31])
    return "".join(out)


def digest_of(payload):
    """A stable content hash over anything JSON-shaped or array-shaped.

    Arrays are hashed over their raw bytes plus dtype and shape rather than through
    JSON: a 600k-element buffer must not become a 20MB string to be named, and the
    bytes are what identity means for a buffer anyway.
    """
    hasher = hashlib.sha256()
    _feed(hasher, payload)
    return "sha256:" + hasher.hexdigest()


def _feed(hasher, value):
    import numpy as np
    if isinstance(value, np.ndarray):
        hasher.update(b"ndarray")
        hasher.update(str(value.dtype).encode())
        hasher.update(str(value.shape).encode())
        hasher.update(np.ascontiguousarray(value).tobytes())
    elif isinstance(value, dict):
        hasher.update(b"dict")
        for key in sorted(value):
            hasher.update(str(key).encode())
            _feed(hasher, value[key])
    elif isinstance(value, (list, tuple)):
        hasher.update(b"seq")
        for item in value:
            _feed(hasher, item)
    elif isinstance(value, Entity):
        hasher.update(value.digest.encode())
    elif isinstance(value, (np.floating, np.integer)):
        hasher.update(repr(value.item()).encode())
    else:
        hasher.update(repr(value).encode())


class Entity:
    """The envelope every record in the system wears (§2.2), without exception."""

    __slots__ = ("id", "kind", "digest", "inputs", "created", "actor", "status",
                 "attrs", "payload")

    def __init__(self, kind, digest, inputs, actor, attrs=None, payload=None):
        if kind not in KINDS:
            raise ValueError("unregistered kind %r; add it to KINDS with a meaning"
                             % kind)
        self.id = "%s_%s" % (kind, _ulid())
        self.kind = kind
        self.digest = digest
        self.inputs = list(inputs)
        self.created = time.time()
        self.actor = actor
        self.status = "active"
        # attrs are human- and machine-readable facts ABOUT the entity and are part of
        # the record. payload is the bulk data (buffers, arrays) and is not serialised
        # into the manifest -- it is addressed by digest instead.
        self.attrs = dict(attrs or {})
        self.payload = payload

    def supersede(self, other_id):
        self.status = "superseded_by(%s)" % other_id

    def reject(self, reason_id):
        self.status = "rejected(%s)" % reason_id

    def record(self):
        return {"id": self.id, "kind": self.kind, "digest": self.digest,
                "inputs": self.inputs, "created": self.created, "actor": self.actor,
                "status": self.status, "attrs": _plain(self.attrs)}

    def __repr__(self):
        return "<%s %s>" % (self.kind, self.id)


def _plain(value):
    import numpy as np
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return value.item()
    return value


class Store:
    """The run's entities and the DAG they form.

    `inputs` on every entity is what makes a run a directed acyclic graph rather than a
    pile of files: any output walks back to the exact renders, masks, policy and model
    versions that produced it. Nothing is deleted within a run (§2.5) -- a rejected
    entity is still queryable, because the reason something is absent is as much a
    result as the things that are present.
    """

    def __init__(self, root, actor="deterministic:store@0.2.0"):
        self.root = root
        self.actor = actor
        self.by_id = {}
        self.by_digest = {}
        os.makedirs(root, exist_ok=True)

    def mint(self, kind, inputs=(), params=None, actor=None, attrs=None, payload=None,
             reuse=True):
        """Create an entity, or return the existing one with the same content (§2.1).

        `params` and the inputs' digests together are the content identity. Two runs
        with the same object, policy and profile therefore produce the same digest for
        every deterministic stage, which is what makes caching and replay possible
        without anyone writing a cache.
        """
        input_ids = [i.id if isinstance(i, Entity) else str(i) for i in inputs]
        input_digests = [i.digest if isinstance(i, Entity) else str(i) for i in inputs]
        digest = digest_of({"kind": kind, "inputs": input_digests,
                            "params": params or {}})
        if reuse and digest in self.by_digest:
            return self.by_digest[digest]
        entity = Entity(kind, digest, input_ids, actor or self.actor, attrs, payload)
        self.by_id[entity.id] = entity
        self.by_digest[digest] = entity
        return entity

    def reject(self, what, reason, inputs=(), count=None):
        """Mint a `reject` and mark the subject, so a discard is never anonymous."""
        entity = self.mint("reject", inputs=inputs,
                           params={"reason": reason, "what": what, "count": count},
                           attrs={"reason": reason, "what": what, "count": count},
                           reuse=False)
        return entity

    def get(self, entity_id):
        return self.by_id[entity_id]

    def of_kind(self, kind):
        return [e for e in self.by_id.values() if e.kind == kind]

    def provenance(self, entity_id):
        """Every entity this one transitively derives from, nearest first."""
        seen, order, stack = set(), [], [entity_id]
        while stack:
            current = stack.pop(0)
            if current in seen or current not in self.by_id:
                continue
            seen.add(current)
            order.append(current)
            stack.extend(self.by_id[current].inputs)
        return order

    def manifest(self):
        return {"entities": [e.record() for e in
                             sorted(self.by_id.values(), key=lambda e: e.id)]}

    def write(self, name="manifest.json"):
        path = os.path.join(self.root, name)
        with open(path, "w") as handle:
            json.dump(self.manifest(), handle, indent=2)
        return path
