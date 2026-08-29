"""Object bundle and painter capability profile (spec §3.1, §3.2).

`target_size` is the only dimensional input accepted from a human, and it is optional.
When absent it is inferred (§4.1) and surfaced as a correctable assumption. It is never
silently defaulted -- a guessed millimetre that nobody was told about would poison every
threshold downstream while looking exactly like a measurement.
"""

import os
from dataclasses import dataclass, field

import numpy as np
import trimesh


@dataclass
class Tip:
    """One brush tip. The source of every physical length in §11."""
    name: str
    tip_radius_mm: float
    working_length_mm: float = 0.0
    half_angle_deg: float = 30.0


@dataclass
class Paint:
    """One purchasable paint. Lab, because §11 matches by dE2000, not by RGB."""
    sku: str
    name: str
    lab: tuple
    opacity: str = "opaque"      # opaque | semi | transparent
    finish: str = "matte"        # matte | satin | gloss | metallic


@dataclass
class ViewingCondition:
    """How the finished object will actually be looked at.

    Contrast requirements are angular, not absolute: two colours that separate cleanly
    at arm's length can collapse on a shelf across the room. §11 needs this to know what
    "distinguishable" means, and there is no defensible default -- so when it is absent
    the limiter says the scheme is unverifiable for contrast rather than inventing one.
    """
    distance_mm: float = None
    illuminant: str = "D65"


@dataclass
class PainterProfile:
    """§3.2. With neither tips nor palette the pipeline runs UNCONSTRAINED.

    That is the correct behaviour and not a degenerate one: the limiter still executes,
    with an infinite palette and zero minimum feature size, and the export is marked
    unrealizable. It produces a design rather than a plan, and says which it is.
    """
    tips: list = field(default_factory=list)
    palette: list = field(default_factory=list)
    techniques: list = field(default_factory=list)
    viewing: ViewingCondition = field(default_factory=ViewingCondition)

    @property
    def unconstrained(self):
        return not self.tips and not self.palette

    def finest_tip(self):
        return min(self.tips, key=lambda t: t.tip_radius_mm) if self.tips else None

    def params(self):
        return {"tips": [(t.name, t.tip_radius_mm, t.half_angle_deg) for t in self.tips],
                "palette": [(p.sku, tuple(p.lab)) for p in self.palette],
                "techniques": list(self.techniques),
                "viewing": (self.viewing.distance_mm, self.viewing.illuminant)}


@dataclass
class ObjectBundle:
    """§3.1. One or more surface meshes, a brief, and an optional real size."""
    paths: list
    intent: str = ""
    target_size_mm: float = None
    meshes: list = field(default_factory=list)

    def load(self):
        """Load every part. `process=False` so the file's geometry is what we hold.

        trimesh's default processing merges vertices and drops degenerate faces, which
        silently changes the thing being described. The mesh here is a ray target and an
        export target; it is not ours to edit.
        """
        self.meshes = []
        for path in self.paths:
            mesh = trimesh.load(path, process=False, force="mesh")
            self.meshes.append(mesh)
        return self.meshes

    def params(self):
        return {"paths": [os.path.basename(p) for p in self.paths],
                "intent": self.intent, "target_size_mm": self.target_size_mm}
