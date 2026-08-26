"""The only literals in the system (spec §3.3).

Invariant I2 says no dimensional constant may be written in source: every quantity
carrying units -- mm, mm^2, mm/px, dE -- is derived at runtime from the object, the
display condition, or the painter's declared hardware. What survives that rule is a
short list of DIMENSIONLESS policy constants, and they live here and nowhere else.

If you find yourself wanting to add a number with a unit attached to this file, the
number belongs in a profile, a frame or a band, and the fact that it feels like a
constant means something upstream has not been derived yet.
"""

from dataclasses import dataclass, asdict, fields


@dataclass(frozen=True)
class Policy:
    """Dimensionless policy. Content-addressed as a `policy` entity (§2.3)."""

    # §4 -- how finely the object is resolved and how its detail bands are found.
    nyquist_factor: float = 2.5      # samples per finest resolved wavelength
    band_prominence: float = 0.15    # min peak prominence to declare a band
    # A cue kernel wider than the object stops landing on it, and an unsupported
    # measurement is not a small measurement -- it is not a measurement. This is the
    # same kind of validity condition as resolvability in §5.3, stated from the other
    # end, and it is what keeps a slender model and a chunky one each losing their
    # ladder where their OWN geometry runs out rather than at a shared number.
    kernel_support: float = 0.5      # min fraction of kernel taps landing on surface

    # §4.5, §9 -- when to stop looking.
    incidence_bins: int = 3          # distinct viewing-angle bins required per point
    # Every area is either sampled at least this many times -- across cameras, rigs and
    # bands -- or it is INVISIBLE, and the invisible set is measured and reported rather
    # than quietly excluded. A single look can be wrong in ways that thirty looks from
    # different directions under different light cannot all be wrong in the same way,
    # which is what lets imperfect masks resolve into a reliable answer (§7, §8).
    min_samples: int = 30            # admitted observations required per point per band
    coverage_target: float = 0.995   # fraction of area meeting the coverage rule
    info_gain_floor: float = 0.02    # stop when marginal bits per view falls below

    # §7, §8 -- what is allowed to become a belief.
    posterior_floor: float = 0.55    # min posterior mass to admit a label
    boundary_guard_px: int = 2       # pixels dropped either side of a depth cut

    # §11 -- what survives contact with hardware.
    contrast_margin: float = 1.5     # multiplier on just-noticeable dE
    merge_ratio: float = 1.0         # region inscribed radius, in brush tip radii

    # §2.4 -- identity that survives re-segmentation.
    anchor_match_thresh: float = 0.82

    def as_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, values):
        known = {f.name for f in fields(cls)}
        unknown = set(values) - known
        if unknown:
            raise ValueError("unknown policy constants: %s" % ", ".join(sorted(unknown)))
        return cls(**values)


DEFAULT = Policy()
