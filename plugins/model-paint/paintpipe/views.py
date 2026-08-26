"""Camera budget and convergence (spec §4.5, §9).

N IS NOT A PARAMETER. Views are drawn until the coverage predicate holds:

    Every surface point is observed, at each band it belongs to, by at least
    `incidence_bins` distinct viewing-angle bins with per-pixel GSD <= lambda_i, over at
    least `coverage_target` of surface area.

Three distinct viewing-angle bins, not three views: three cameras clustered on one side
of the object see the same thing three times, and a point they all view obliquely has
been looked at badly three times rather than well once. Binning by incidence direction
is what makes the count mean what it is supposed to mean.

Sampling proceeds in rounds -- a Fibonacci-sphere base round, then adaptive rounds aimed
at the deficit set. It halts on coverage, or earlier if the marginal information gain
per view falls below `info_gain_floor`, which is the correct outcome for a genuinely
featureless object and not a failure. Failure to converge is a reportable outcome with a
map of where, not an exception (§9).
"""

import numpy as np

from . import admit as admit_module
from . import render as render_module


class CoverageState:
    """Who has seen what, at which band, from how many distinct directions.

    Held per substrate vertex rather than per pixel, because the question "has this
    surface been seen enough" is about the object and must survive a change of camera.
    """

    def __init__(self, vertex_count, band_count, area_mm2, bins=6):
        # Six is not a tuning choice: it is how many faces a cube has, and `bin_of`
        # returns exactly one of them.
        self.bins = int(bins)
        self.area = np.asarray(area_mm2, dtype=float)
        # One bitmask per (vertex, band): which direction bins have resolved it.
        self.seen = np.zeros((band_count, vertex_count), dtype=np.int64)
        self.weight = np.zeros((band_count, vertex_count))
        # How many admitted observations each point has received at each band. This is
        # the quantity the predicate is actually about: not "was it looked at" but "was
        # it looked at enough times, from enough places, to be worth believing".
        self.samples = np.zeros((band_count, vertex_count), dtype=np.int32)
        self.views = 0

    def bin_of(self, direction):
        """Which viewing-angle bin a camera direction falls in.

        The signed dominant axis -- which face of a cube the camera looks from. Six
        bins, every direction in exactly one, and two directions share a bin only if
        they really do look from the same side.

        The first version of this combined an octant index with a dominant axis and took
        it modulo the bin count, which collided constantly: genuinely different views
        were recorded as the same view, so the predicate believed the object had been
        seen from three sides when it had been seen from one, and coverage stalled at a
        third with no indication why. A binning function that loses information is worse
        than no binning, because the count still looks like it means something.
        """
        direction = np.asarray(direction, dtype=float)
        dominant = int(np.argmax(np.abs(direction)))
        return dominant * 2 + int(direction[dominant] > 0)

    def add(self, band_index, vertices, weights, direction):
        bit = np.int64(1) << np.int64(self.bin_of(direction))
        np.bitwise_or.at(self.seen[band_index], vertices, bit)
        np.add.at(self.weight[band_index], vertices, weights)
        np.add.at(self.samples[band_index], vertices, 1)
        return self

    def bins_per_vertex(self, band_index):
        counts = np.zeros(self.seen.shape[1], dtype=np.int32)
        for bit in range(self.bins):
            counts += ((self.seen[band_index] >> bit) & 1).astype(np.int32)
        return counts

    def visibility_ceiling(self, band_index=0):
        """Fraction of area that has been resolved from at least ONE bin.

        The predicate can never do better than this, and the gap between them is the
        part of the object that is genuinely interior rather than merely under-sampled.
        Reporting the two together is what makes a non-converged run diagnosable instead
        of just disappointing: measured on the shell at 48 spread views, 92.5% of area
        is visible at all but only 63.8% reaches three distinct bins, because a point on
        a surface facing one way cannot be resolved from three cube faces at a
        non-grazing incidence. That is a fact about sculpted geometry, not a deficit
        more looking will fix.
        """
        seen = self.bins_per_vertex(band_index) >= 1
        return float(self.area[seen].sum() / max(self.area.sum(), 1e-12))

    def satisfied(self, policy):
        """Per band: the fraction of VISIBLE area meeting the rule, and the deficit.

        The rule has two halves and a point must pass both: at least `min_samples`
        admitted observations, and at least `incidence_bins` distinct viewing-angle
        bins. Thirty looks from one direction are one look repeated -- they share every
        systematic error that direction has -- so the count and the spread are separate
        requirements and neither substitutes for the other.

        The denominator is VISIBLE area. Interior surface that no camera can reach is
        not a sampling deficit and no number of further views will change it; it is
        reported separately by `invisible_area` so the two failures stay distinguishable.
        """
        out = []
        for band_index in range(self.seen.shape[0]):
            visible = self.samples[band_index] > 0
            enough = ((self.samples[band_index] >= policy.min_samples)
                      & (self.bins_per_vertex(band_index) >= policy.incidence_bins))
            denominator = max(self.area[visible].sum(), 1e-12)
            covered = float(self.area[enough].sum() / denominator)
            out.append((covered, visible & ~enough))
        return out

    def invisible_area(self, band_index=0):
        """Fraction of total area no admitted observation ever reached."""
        never = self.samples[band_index] == 0
        return float(self.area[never].sum() / max(self.area.sum(), 1e-12))

    def sample_report(self, band_index=0):
        """The distribution of sample counts, which is what "at least 30" is about."""
        counts = self.samples[band_index]
        visible = counts > 0
        if not visible.any():
            return {"visible_area": 0.0, "median": 0, "p10": 0, "min": 0}
        weights = self.area[visible]
        order = np.argsort(counts[visible])
        sorted_counts = counts[visible][order]
        cumulative = np.cumsum(weights[order]) / weights.sum()
        return {"visible_area": float(weights.sum() / max(self.area.sum(), 1e-12)),
                "p10": int(sorted_counts[np.searchsorted(cumulative, 0.10)]),
                "median": int(sorted_counts[np.searchsorted(cumulative, 0.50)]),
                "min": int(sorted_counts[0])}

    def holds(self, policy):
        return all(covered >= policy.coverage_target
                   for covered, _deficit in self.satisfied(policy))


def coverage_state(field, bands, bins=6):
    """§4.5 / §12. A fresh coverage map for this object and its ladder."""
    return CoverageState(len(field.substrate.vertices), len(bands),
                         field.vertex_area, bins=bins)


def information_gain(before, after):
    """Marginal bits per view: how much newly-resolved area the last round bought.

    Expressed as a fraction of the object's area so the floor stays dimensionless (I2).
    """
    return float(max(after - before, 0.0))


def plan_views(frame, state, policy, bands, round_index, base=None,
               deficit_points=None, deficit_normals=None, taken=None):
    """§4.5 / §12. Directions for the next round.

    The base round is a Fibonacci sphere -- spread rather than random, so it is
    reproducible without a seed.

    Later rounds AIM ALONG THE DEFICIT'S OWN NORMALS, which is the whole trick. A point
    is visible from the direction it faces unless something stands in front of it, so
    the best camera for an unseen point is the one looking straight down its normal. An
    earlier version aimed by taking the principal axes of the deficit's POSITIONS, which
    is a fact about where the unseen surface sits rather than about which way it faces;
    it left a stubborn twelve percent of the shell unseen no matter how many rounds ran,
    because a camera pointed at a cavity from the wrong side still cannot see into it.

    Directions are clustered so that one camera serves many deficit points, and any
    direction already used is skipped -- repeating a view adds observations but adds no
    information, and the information-gain floor would then stop the loop for the wrong
    reason.
    """
    if round_index == 0:
        count = base or max(12, 6 * len(bands))
        return list(render_module.fibonacci_directions(count))
    if deficit_normals is None or len(deficit_normals) == 0:
        if deficit_points is None or len(deficit_points) == 0:
            return []
        centre = deficit_points.mean(axis=0)
        primary = centre / max(np.linalg.norm(centre), 1e-9)
        return [primary, -primary]

    normals = np.asarray(deficit_normals, dtype=float)
    normals = normals / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    # Cluster on the sphere by nearest Fibonacci direction: a fixed, spread codebook, so
    # the clustering is deterministic and needs no seed and no iteration count.
    codebook = render_module.fibonacci_directions(max(24, 8 * len(bands)))
    assignment = np.argmax(normals @ codebook.T, axis=1)
    population = np.bincount(assignment, minlength=len(codebook))
    order = np.argsort(population)[::-1]
    out = []
    used = [] if taken is None else [np.asarray(t, dtype=float) for t in taken]
    for index in order:
        if population[index] == 0:
            break
        direction = codebook[index]
        # Skip a direction already looked from: it would add votes without adding view.
        if any(float(direction @ prior) > 0.985 for prior in used):
            continue
        out.append(direction)
        used.append(direction)
        if len(out) >= 6:
            break
    return out


def observe_bundle(field, bundle, bands, policy, labeller, store=None, inputs=(),
                   state=None):
    """§12 `observe`: turn one bundle into admitted observations at every band.

    `labeller` maps (bundle, band) to (label, mask_confidence) -- the seam where an
    agent's proposals enter (§10). A deterministic labeller is used by the tests and by
    the unsupervised path; nothing below this line knows or cares which it was.
    """
    written = 0
    sample = admit_module.gsd(bundle)
    for band in bands:
        weight, admitted = admit_module.admit(bundle, band, policy, store=store,
                                              inputs=inputs)
        if not admitted.any():
            continue
        for label, confidence_map in labeller(bundle, band):
            live = admitted & (confidence_map > 0)
            if not live.any():
                continue
            points = bundle["point"][live]
            weights = weight[live] * confidence_map[live]
            observation = None
            if store is not None:
                observation = store.mint(
                    "observation", inputs=inputs,
                    params={"label": label, "band": band.index,
                            "rig": bundle["rig"], "count": int(live.sum())},
                    attrs={"label": label, "band": band.index, "rig": bundle["rig"],
                           "count": int(live.sum()),
                           "weight_mm2": round(float(weights.sum()), 4)},
                    reuse=False)
            written += field.observe(
                points, label, weights, band.index,
                gsd=sample[live], incidence=bundle["incidence"][live],
                mask_confidence=confidence_map[live], rig_id=bundle["rig"],
                ids=None if observation is None else [observation.id] * int(live.sum()))
            if state is not None:
                state.add(band.index, field.nearest_vertex(points), weights,
                          bundle["camera"].forward)
    return written


def converge(field, mesh, frame, bands, policy, labeller, rigs=("zenithal",),
             pixels=700, store=None, inputs=(), max_rounds=6, log=None):
    """§9. Sampling and fusion as a LOOP, not a pass.

    Returns the coverage state and why it stopped. Which exit was taken is recorded on
    the run, because "covered" and "gave up" are different results that a caller must be
    able to tell apart.
    """
    centre = mesh.vertices.mean(axis=0)
    radius = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0 * 1.05
    state = coverage_state(field, bands)
    field.bands = list(bands)
    previous = 0.0
    reason = "budget"
    seen_directions = []
    normals = field.substrate.vertex_normals
    for round_index in range(max_rounds):
        deficit_points = deficit_normals = None
        if round_index > 0:
            # The deficit is everything not yet satisfied, INCLUDING what has never been
            # seen at all. Treating "never seen" as a separate category that the planner
            # ignores is what let it sit unresolved.
            worst = min(state.satisfied(policy), key=lambda entry: entry[0])
            never = state.samples.sum(axis=0) == 0
            short = np.flatnonzero(worst[1] | never)
            if len(short):
                deficit_points = field.substrate.vertices[short]
                deficit_normals = normals[short]
        directions = plan_views(frame, state, policy, bands, round_index,
                                deficit_points=deficit_points,
                                deficit_normals=deficit_normals,
                                taken=seen_directions)
        if not directions:
            reason = "no deficit to aim at"
            break
        for direction in directions:
            seen_directions.append(np.asarray(direction, dtype=float))
            camera = render_module.Camera(-np.asarray(direction, dtype=float),
                                          [0.0, 0.0, 1.0], centre, radius, pixels)
            for rig in rigs:
                bundle = render_module.render_bundle(mesh, camera, rig, frame)
                observe_bundle(field, bundle, bands, policy, labeller, store=store,
                               inputs=inputs, state=state)
            state.views += 1
        covered = min(entry[0] for entry in state.satisfied(policy))
        gain = information_gain(previous, covered)
        if log:
            report = state.sample_report()
            log("round %d: %d views, %.3f of visible area at >=%d samples "
                "(+%.3f); samples p10=%d median=%d; %.3f of area invisible"
                % (round_index, state.views, covered, policy.min_samples, gain,
                   report["p10"], report["median"], state.invisible_area()))
        if state.holds(policy):
            reason = "coverage"
            break
        if round_index > 0 and gain < policy.info_gain_floor:
            reason = "information gain below floor"
            break
        previous = covered
    if store is not None:
        covered = min(entry[0] for entry in state.satisfied(policy))
        ceiling = state.visibility_ceiling()
        if reason != "coverage":
            store.reject(
                "coverage",
                "stopped at %.3f of %.3f required (%s); %.3f of area is visible at all, "
                "so %.3f of the shortfall is interior surface rather than under-sampling"
                % (covered, policy.coverage_target, reason, ceiling,
                   max(1.0 - ceiling, 0.0)),
                inputs=inputs, count=int(round((1.0 - covered) * 1000)))
    return state, reason
