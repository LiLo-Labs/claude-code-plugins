"""Detail bands and working resolution (spec §4.3, §4.4).

This replaces every hardcoded level size. The number of levels of description, and
their sizes, come from the object (I6): a smooth sphere and a filigreed reliquary must
produce different ladders with no code change, and neither ladder is written anywhere.

ONE DELIBERATE DEVIATION, stated rather than buried. §4.3 forms the spectrum from two
ingredients: heat-kernel-smoothed mean curvature magnitude, and screen-space cavity
response at matching render scales. Only the second is used here. Mean curvature is a
property of the tessellation as much as of the shape -- a 626k-triangle mesh and its 25%
decimation do not agree on it -- so including it would put a tessellation-dependent term
into the ladder that every band, every threshold and every physical length downstream is
derived from. That directly contradicts I1 and would fail the tessellation-independence
gate in §13, which is the gate that proves the whole appearance-first claim. The
screen-space half is the half that satisfies I1, and it is sufficient: a cue kernel of
radius r in millimetres peaks when r matches the size of the feature under it, which is
exactly the characteristic-scale response the spectrum is looking for.

The sampling in §4.3 step 1 is likewise done by camera rather than by Poisson disk on
the surface, for the same reason: rays land on the object in proportion to visible area,
which is the measure the spectrum should be normalized by.
"""

import numpy as np

from . import cues as cue_module
from . import render as render_module


class Band:
    """One detail band: a characteristic wavelength and where it came from."""

    def __init__(self, index, wavelength_mm, energy, prominence):
        self.index = int(index)
        self.wavelength_mm = float(wavelength_mm)
        self.energy = float(energy)
        self.prominence = float(prominence)

    def params(self):
        return {"index": self.index, "wavelength_mm": round(self.wavelength_mm, 6),
                "energy": round(self.energy, 6), "prominence": round(self.prominence, 6)}

    def __repr__(self):
        return "<band %d lambda=%.3fmm>" % (self.index, self.wavelength_mm)


def pixel_area_mm2(bundle):
    """Surface area each pixel covers: footprint^2 divided by the cosine of incidence.

    This is the area weight that removes tessellation bias without ever referring to
    tessellation (§7). A face seen edge-on at twelve pixels cannot outvote the same face
    seen flat at four thousand, because each of those pixels is carrying its own honest
    share of surface with it.
    """
    camera = bundle["camera"]
    incidence = bundle["incidence"]
    out = np.full(incidence.shape, np.nan)
    live = bundle["visible"] & np.isfinite(incidence) & (incidence > 1e-3)
    out[live] = camera.footprint_mm ** 2 / incidence[live]
    return out, live


def cue_energy_spectrum(mesh, frame, radii_mm, policy, views=8, pixels=900,
                        rig="zenithal", store=None, inputs=()):
    """Area-normalized cue energy against feature size (§4.3 step 3).

    The band gate of §5.3 binds HERE too, and getting that wrong was a real bug worth
    recording: a kernel radius below one pixel clamps to one pixel, so every rung finer
    than the camera could resolve returned the SAME measurement while looking like four
    independent ones, and the fine end of the ladder was fabricated. A camera now
    declines to answer for a rung it cannot resolve, exactly as a view with insufficient
    GSD declines to vote on a band, and an unresolved rung is a `reject` with a reason
    rather than a silently duplicated number.
    """
    centre = mesh.vertices.mean(axis=0)
    radius = float(np.ptp(mesh.vertices, axis=0).max()) / 2.0 * 1.05
    directions = render_module.fibonacci_directions(views)
    energy = np.zeros(len(radii_mm))
    weight = np.zeros(len(radii_mm))
    support = np.zeros(len(radii_mm))
    support_weight = np.zeros(len(radii_mm))
    for direction in directions:
        camera = render_module.Camera(-direction, [0.0, 0.0, 1.0], centre, radius,
                                      pixels)
        bundle = render_module.render_bundle(mesh, camera, rig, frame, cavity_taps=8)
        area, area_ok = pixel_area_mm2(bundle)
        for k, wavelength in enumerate(radii_mm):
            if camera.footprint_mm > wavelength / policy.nyquist_factor:
                continue                      # cannot resolve it, so has no opinion
            cavity, cavity_ok = cue_module.cavity(bundle, wavelength)
            ridge, ridge_ok = cue_module.ridge(bundle, wavelength)
            ok = area_ok & cavity_ok & ridge_ok
            if not ok.any():
                continue
            radius_px = max(1.0, wavelength / camera.footprint_mm)
            landed = cue_module.ring_support(bundle["visible"], radius_px)
            support[k] += float(np.sum(landed[ok] * area[ok]))
            support_weight[k] += float(np.sum(area[ok]))
            response = cavity[ok] + ridge[ok]
            energy[k] += float(np.sum(response * area[ok]))
            weight[k] += float(np.sum(area[ok]))
    resolved = weight > 0
    if store is not None and not resolved.all():
        store.reject("band_rung", "below the working camera's resolving power",
                     inputs=inputs, count=int((~resolved).sum()))
    out = np.full(len(radii_mm), np.nan)
    out[resolved] = energy[resolved] / weight[resolved]
    held = np.full(len(radii_mm), np.nan)
    held[support_weight > 0] = support[support_weight > 0] / support_weight[
        support_weight > 0]
    supported = resolved & (held >= policy.kernel_support)
    if store is not None and (resolved & ~supported).any():
        store.reject("band_rung", "kernel wider than the object supports",
                     inputs=inputs, count=int((resolved & ~supported).sum()))
    return out, supported, held


def band_pass(radii_mm, energy):
    """Energy ADDED at each scale: dE/d(log r).

    E(r) as measured is cumulative -- a kernel of radius r responds to everything at r
    and below -- so on any object with detail at many scales it climbs monotonically to
    the dominant structure and has no interior maxima at all. Measured on the shell: a
    clean single peak at 10mm, with the barnacle band invisible, because barnacles are a
    minority of the surface and the mean buries them.

    The derivative is the band-pass, and it is what §4.3's peak search actually wants:
    how much cue energy appears when the kernel grows to take in features of this size.
    On the same spectrum it recovers the bumps a person sees.
    """
    return np.gradient(energy, np.log(radii_mm))


def find_peaks(energy, min_prominence):
    """Local maxima with prominence above the floor (§4.3 step 4).

    Prominence is the standard definition -- the drop required on both sides before
    reaching higher ground -- normalized by the response's own range so the floor stays
    dimensionless, as I2 requires.
    """
    # A band is a local maximum of ADDED energy. Where the response is negative, growing
    # the kernel has removed normalized cue energy -- there is no feature at that scale,
    # by the definition of the measurement -- so such a rung cannot be a band and its
    # value must not set the scale that prominence is judged against either. Letting the
    # falling tail into the denominator is enough on its own to push every real band
    # below the floor: it cost the shell its rib band while the dragon kept its spikes,
    # which is the signature of a rule that depends on the model rather than the object.
    positive = energy > 0
    if not positive.any():
        return []
    span = float(np.nanmax(energy[positive]) - np.nanmin(energy[positive]))
    if span <= 0:
        return []
    peaks = []
    for i in range(1, len(energy) - 1):
        if not positive[i]:
            continue
        if not (energy[i] >= energy[i - 1] and energy[i] >= energy[i + 1]):
            continue
        left = energy[i]
        for j in range(i - 1, -1, -1):
            left = min(left, energy[j])
            if energy[j] > energy[i]:
                break
        right = energy[i]
        for j in range(i + 1, len(energy)):
            right = min(right, energy[j])
            if energy[j] > energy[i]:
                break
        prominence = (energy[i] - max(left, right)) / span
        if prominence >= min_prominence:
            peaks.append((i, prominence))
    return peaks


def derive_bands(mesh, frame, policy, levels=18, views=8, pixels=900, store=None,
                 inputs=()):
    """§4.3. Returns bands ordered COARSE to FINE, plus the spectrum for the record.

    The ladder spans the object's own diagonal down to what the working camera can
    resolve, so it is expressed in the object's terms and bounded by the measurement
    rather than by a number someone chose. Nothing here decides how many bands there
    are.
    """
    diagonal = frame.diagonal_mm
    footprint = 2.0 * (float(np.ptp(mesh.vertices, axis=0).max()) / 2.0 * 1.05) / pixels
    finest = footprint * policy.nyquist_factor
    # `mesh` here is already the working mesh, so this footprint is in millimetres.
    radii = np.exp(np.linspace(np.log(finest), np.log(diagonal / 2.0), levels))
    energy, supported, held = cue_energy_spectrum(mesh, frame, radii, policy,
                                                  views=views, pixels=pixels,
                                                  store=store, inputs=inputs)
    live = supported & np.isfinite(energy)
    kept_radii, kept_energy = radii[live], energy[live]
    response = band_pass(kept_radii, kept_energy)
    peaks = find_peaks(response, policy.band_prominence)
    spectrum = {"radii_mm": radii.tolist(), "energy": energy.tolist(),
                "support": held.tolist(), "admitted": live.tolist(),
                "band_pass_mm": kept_radii.tolist(), "band_pass": response.tolist()}
    if not peaks:
        # A genuinely featureless object has one band, its own dominant scale. That is
        # a correct outcome and not a failure: there is one thing to describe.
        peaks = [(int(np.nanargmax(response)), 0.0)]
        if store is not None:
            store.reject("band", "no peak cleared the prominence floor; "
                                 "object described at its dominant scale alone",
                         inputs=inputs, count=1)
    bands = [Band(0, kept_radii[i], kept_energy[i], prominence)
             for i, prominence in peaks]
    bands.sort(key=lambda b: -b.wavelength_mm)
    for order, band in enumerate(bands):
        band.index = order
    return bands, spectrum


def working_resolution(bands, profile, policy):
    """§4.4. Used for baking and ONLY for baking; reasoning never touches it.

    rho      -- the finest wavelength the object has, sampled at the Nyquist factor
    rho_paint-- what the finest brush can actually express
    rho_work -- never finer than paint can express, because a plan that resolves
                detail the painter cannot paint is a drawing, not a plan
    """
    finest = min(band.wavelength_mm for band in bands)
    rho = finest / policy.nyquist_factor
    tip = profile.finest_tip()
    if tip is None:
        # Unconstrained (§3.2): zero minimum feature, and the export says unrealizable.
        return rho, None, rho
    rho_paint = tip.tip_radius_mm
    return rho, rho_paint, max(rho, rho_paint / 2.0)
