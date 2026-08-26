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


DEFAULT_AGENTS = {"planner": Planner(), "identity": Identity(), "region": Region(),
                  "critic": Critic(), "painter": Painter()}
