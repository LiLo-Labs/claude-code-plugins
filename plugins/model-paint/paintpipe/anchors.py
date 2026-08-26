"""Semantic identity that survives re-segmentation (spec §2.4).

The hard case: a region's boundary moves between runs, or the critic restructures the
tree. Boundary geometry cannot BE the identity, because it is exactly what changes.

So each node and region carries an anchor -- a few high-confidence surface points in the
intrinsic frame, normalized by object size, plus an embedding of the name it was given.
On re-run a candidate inherits an existing ULID when its anchor points fall within its
own inscribed radius of the old ones AND the label embeddings agree. That is what lets a
user say "keep the left pauldron colour, redo everything else" and have it still mean
something three weeks later against a re-sliced mesh.
"""

import numpy as np


class Anchor:
    """Points in the intrinsic frame, normalized by object size, plus a name."""

    def __init__(self, points, label, parent=None, band=None, embedding=None):
        self.points = np.atleast_2d(np.asarray(points, dtype=float))
        self.label = label
        self.parent = parent
        self.band = band
        self.embedding = embedding if embedding is not None else embed(label)

    def params(self):
        return {"points": self.points.round(6).tolist(), "label": self.label,
                "parent": self.parent, "band": self.band}


def embed(text):
    """A deterministic bag-of-characters embedding, stated as the placeholder it is.

    §2.4 wants a text embedding so that "left pauldron" and "pauldron, left" agree while
    "left pauldron" and "visor" do not. A real run should hand in a model embedding via
    `Anchor(embedding=...)`. This fallback exists so identity inheritance is testable
    without a model in the loop, and it is deliberately weak rather than secretly
    clever: it compares spelling, not meaning, and anything relying on it should say so.
    """
    text = (text or "").lower()
    vector = np.zeros(37)
    for character in text:
        if character.isalpha():
            vector[ord(character) - 97] += 1.0
        elif character.isdigit():
            vector[26 + int(character)] += 1.0
    norm = np.linalg.norm(vector)
    return vector / norm if norm > 0 else vector


def agreement(a, b):
    return float(np.clip(np.dot(a, b), -1.0, 1.0))


def match_anchor(candidate, priors, inscribed_radius_mm, policy):
    """§2.4 / §12. Return the prior id whose identity this candidate inherits, or None.

    Both conditions must hold. Position alone would hand a renamed part its neighbour's
    history; a name alone would merge the left and right greave the moment the tree was
    restructured. The tolerance is the candidate's OWN inscribed radius, so a large
    region is allowed to move further than a small one -- a fixed millimetre tolerance
    would be a dimensional constant, which I2 forbids, and would mean different things
    on a miniature and on a terrain piece.
    """
    best, best_score = None, -1.0
    for prior_id, anchor in priors.items():
        if not len(anchor.points) or not len(candidate.points):
            continue
        distance = np.linalg.norm(
            candidate.points[:, None, :] - anchor.points[None, :, :], axis=2)
        near = float(distance.min(axis=1).mean())
        if near > inscribed_radius_mm:
            continue
        score = agreement(candidate.embedding, anchor.embedding)
        if score < policy.anchor_match_thresh:
            continue
        combined = score * (1.0 - near / max(inscribed_radius_mm, 1e-9))
        if combined > best_score:
            best, best_score = prior_id, combined
    return best
