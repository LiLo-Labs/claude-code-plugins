"""Vote admission (spec §7) and ground sample distance (§5.3).

Two gates stand between a pixel and the evidence store, and most pixels near a
silhouette never pass either. Both reject branches mint `reject` entities with reasons,
because a pixel that was not allowed to speak is part of the explanation for what the
field believes.

The area weight is what removes tessellation bias WITHOUT EVER REFERRING TO
TESSELLATION. A face seen edge-on across twelve pixels cannot outvote the same face seen
flat across four thousand, because each pixel carries its own honest share of surface
area with it. This is the mechanism that makes I1 hold in practice rather than in
principle: nothing counts triangles, and yet triangle density stops mattering.
"""

import numpy as np


def gsd(bundle):
    """Ground sample distance per pixel, in millimetres (§5.3).

    Orthographic camera, so the footprint is fixed and the whole of the depth term
    collapses; incidence is what remains and it is what varies across the image. A
    surface seen at a grazing angle is sampled coarsely no matter how near it is, which
    is exactly the fact this quantity exists to express.
    """
    incidence = bundle["incidence"]
    out = np.full(incidence.shape, np.inf)
    live = bundle["visible"] & np.isfinite(incidence) & (incidence > 1e-6)
    out[live] = bundle["camera"].footprint_mm / incidence[live]
    return out


def edge_guard(bundle, policy):
    """Pixels within `boundary_guard_px` of a depth discontinuity are excluded.

    A pixel straddling a silhouette has no single surface point behind it, so whatever
    it reports is about two things at once. Antialiasing is already off (§5.1); this is
    the second half of the same argument, and together they are why boundaries in this
    system come from the field rather than from the image.
    """
    depth, visible = bundle["depth"], bundle["visible"]
    filled = np.where(visible, depth, np.nan)
    # A discontinuity is a depth step large compared with the local sampling scale.
    scale = bundle["camera"].footprint_mm
    cut = np.zeros(depth.shape, dtype=bool)
    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        shifted = np.roll(np.roll(filled, dy, axis=0), dx, axis=1)
        seen = np.roll(np.roll(visible, dy, axis=0), dx, axis=1)
        step = np.abs(filled - shifted)
        cut |= visible & seen & np.isfinite(step) & (step > 4.0 * scale)
        cut |= visible & ~seen                     # the outer silhouette itself
    guard = cut.copy()
    for _ in range(int(policy.boundary_guard_px)):
        grown = guard.copy()
        for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
            grown |= np.roll(np.roll(guard, dy, axis=0), dx, axis=1)
        guard = grown
    return guard & visible


def band_fit(sample_distance, wavelength_mm):
    """How well this pixel resolves this band; decays as GSD approaches lambda.

    Not a step. A pixel that only just resolves a band is a worse witness to it than one
    that resolves it comfortably, and expressing that as a weight rather than a
    threshold is what lets marginal views contribute what they are actually worth.
    """
    ratio = np.divide(sample_distance, max(float(wavelength_mm), 1e-9))
    return np.clip(1.0 - ratio, 0.0, 1.0)


def admit(bundle, band, policy, mask_confidence=None, store=None, inputs=()):
    """Both gates plus the weight of §7. Returns (weight, admitted).

        w = mask_confidence * cos(incidence) * a(px) * band_fit(gsd, lambda)

    `a(px)` is the pixel's projected surface area in mm^2.
    """
    visible = bundle["visible"]
    sample = gsd(bundle)
    guard = edge_guard(bundle, policy)
    resolves = sample <= band.wavelength_mm

    admitted = visible & ~guard & resolves
    if store is not None:
        dropped_guard = int((visible & guard).sum())
        dropped_band = int((visible & ~guard & ~resolves).sum())
        if dropped_guard:
            store.reject("pixel", "within boundary guard of a depth discontinuity",
                         inputs=inputs, count=dropped_guard)
        if dropped_band:
            store.reject("pixel", "gsd exceeds band wavelength; no opinion at this band",
                         inputs=inputs, count=dropped_band)

    incidence = np.nan_to_num(bundle["incidence"])
    area = np.zeros(visible.shape)
    live = admitted & (incidence > 1e-3)
    area[live] = bundle["camera"].footprint_mm ** 2 / incidence[live]

    confidence = np.ones(visible.shape) if mask_confidence is None \
        else np.asarray(mask_confidence, dtype=float)
    weight = np.zeros(visible.shape)
    weight[admitted] = (confidence[admitted] * incidence[admitted] * area[admitted]
                        * band_fit(sample[admitted], band.wavelength_mm))
    return weight, admitted
