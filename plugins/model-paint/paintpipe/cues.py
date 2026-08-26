"""Visual cues, computed in screen space from buffers (spec §6).

Every cue descends from a render buffer and never from geometry. That is what makes
cues independent of tessellation: a 20k-triangle and a 2M-triangle version of the same
shape produce the same cue maps, because the ray tracer resolves both to the same
picture and the picture is what is measured.

Each cue is emitted at every band the pixel is admissible for, with responses normalized
so that different zooms are directly comparable -- a crevice one millimetre across reads
the same whether the camera is close or far, because the kernel radius is set in
millimetres and converted to pixels through the camera's own footprint.

Cue maps are continuous with confidence, never binary. A thresholded cue throws away
exactly the information the fusion stage needs to weigh one view against another.
"""

import numpy as np

CHANNELS = ("cavity", "ridge", "plane", "silhouette", "albedo_break")


def _band_radius_px(wavelength_mm, camera):
    """A band's wavelength in pixels for this camera. The only zoom conversion (I4)."""
    return max(1.0, float(wavelength_mm) / max(camera.footprint_mm, 1e-9))


def _shift(field, dy, dx):
    return np.roll(np.roll(field, dy, axis=0), dx, axis=1)


def ring_support(visible, radius_px, taps=8):
    """Fraction of kernel taps that land on the object, per pixel.

    A ring wider than the object mostly samples empty space, and the response it returns
    is an artifact of the silhouette rather than a fact about surface detail. Measuring
    support makes that detectable without reference to what the response happens to look
    like on any particular model.
    """
    count = np.zeros(visible.shape, dtype=float)
    for k in range(taps):
        angle = 2.0 * np.pi * k / taps
        dy = int(round(np.sin(angle) * radius_px))
        dx = int(round(np.cos(angle) * radius_px))
        if dy == 0 and dx == 0:
            count += visible
            continue
        count += visible & _shift(visible, dy, dx)
    return count / float(taps)


def _ring(field, visible, radius_px, taps=8):
    """Mean of a field around a ring of given radius, and how many taps landed."""
    total = np.zeros_like(field, dtype=float)
    count = np.zeros(field.shape, dtype=float)
    for k in range(taps):
        angle = 2.0 * np.pi * k / taps
        dy = int(round(np.sin(angle) * radius_px))
        dx = int(round(np.cos(angle) * radius_px))
        if dy == 0 and dx == 0:
            continue
        shifted = _shift(field, dy, dx)
        ok = visible & _shift(visible, dy, dx) & np.isfinite(shifted)
        total[ok] += shifted[ok]
        count[ok] += 1.0
    return total, count


def cavity(bundle, wavelength_mm):
    """Where shade collects: wash targets.

    Screen-space AO from depth at a kernel radius set by the band. A pixel is occluded
    to the extent that its neighbours at that radius stand nearer to the camera, and the
    response is normalized by the band wavelength so that a 1mm crevice and a 10mm
    hollow each read as fully cavernous at their own band.
    """
    depth, visible = bundle["depth"], bundle["visible"]
    camera = bundle["camera"]
    radius_px = _band_radius_px(wavelength_mm, camera)
    filled = np.where(visible, depth, np.nan)
    total, count = _ring(filled, visible, radius_px)
    out = np.full(depth.shape, np.nan)
    live = count > 0
    # Positive where neighbours are nearer, i.e. this pixel sits in a hollow.
    relief = np.zeros(depth.shape)
    relief[live] = total[live] / count[live] - filled[live]
    out[live] = np.clip(-relief[live] / max(float(wavelength_mm), 1e-9), 0.0, 1.0)
    return np.where(visible, out, np.nan), live & visible


def ridge(bundle, wavelength_mm):
    """Edges that catch light: highlight targets.

    Positive curvature of the NORMAL buffer at the band's radius. Measured as how far
    the surrounding normals tip away from this one; a crest has neighbours falling away
    on both sides, a flat has none, and a groove has them tipping toward it, which the
    cavity channel already owns.
    """
    normal, visible = bundle["normal"], bundle["visible"]
    depth = bundle["depth"]
    camera = bundle["camera"]
    radius_px = _band_radius_px(wavelength_mm, camera)
    turn = np.zeros(depth.shape)
    count = np.zeros(depth.shape)
    toward = np.zeros(depth.shape)
    filled = np.where(visible, depth, np.nan)
    taps = 8
    for k in range(taps):
        angle = 2.0 * np.pi * k / taps
        dy = int(round(np.sin(angle) * radius_px))
        dx = int(round(np.cos(angle) * radius_px))
        if dy == 0 and dx == 0:
            continue
        other = _shift(normal, dy, dx)
        ok = visible & _shift(visible, dy, dx)
        dot = np.einsum("ijk,ijk->ij", normal, other)
        turn[ok] += 1.0 - np.clip(dot[ok], -1.0, 1.0)
        shifted = _shift(filled, dy, dx)
        toward[ok] += np.clip(filled[ok] - shifted[ok], 0.0, None)
        count[ok] += 1.0
    out = np.full(depth.shape, np.nan)
    live = (count > 0) & visible
    # Convexity gate: turning is a crease either way, and only the side whose
    # neighbours fall AWAY from the camera is a ridge rather than a groove.
    convex = np.zeros(depth.shape)
    convex[live] = np.clip(toward[live] / count[live] /
                           max(float(wavelength_mm), 1e-9), 0.0, 1.0)
    out[live] = np.clip(turn[live] / count[live], 0.0, 1.0) * convex[live]
    return out, live


def plane(bundle, wavelength_mm):
    """A continuous surface a painter would treat as one thing.

    High where the normals within the band radius agree, which is the complement of
    both other form cues: it marks the FIELD rather than its edges, and a region that
    scores high here is a candidate for a single flat colour.
    """
    normal, visible = bundle["normal"], bundle["visible"]
    camera = bundle["camera"]
    radius_px = _band_radius_px(wavelength_mm, camera)
    agree = np.zeros(normal.shape[:2])
    count = np.zeros(normal.shape[:2])
    taps = 8
    for k in range(taps):
        angle = 2.0 * np.pi * k / taps
        dy = int(round(np.sin(angle) * radius_px))
        dx = int(round(np.cos(angle) * radius_px))
        if dy == 0 and dx == 0:
            continue
        ok = visible & _shift(visible, dy, dx)
        dot = np.einsum("ijk,ijk->ij", normal, _shift(normal, dy, dx))
        agree[ok] += np.clip(dot[ok], 0.0, 1.0)
        count[ok] += 1.0
    out = np.full(normal.shape[:2], np.nan)
    live = (count > 0) & visible
    out[live] = agree[live] / count[live]
    return out, live


def silhouette(bundle, wavelength_mm):
    """What identifies the object at a glance: the depth discontinuity chain.

    This is the one cue whose high response marks pixels that must NOT vote (§7). It is
    computed and stored because the outline is real information about the object, and
    because the admission gate needs it -- not because a silhouette pixel has an opinion
    about what it is touching.
    """
    depth, visible = bundle["depth"], bundle["visible"]
    camera = bundle["camera"]
    filled = np.where(visible, depth, np.nan)
    step = np.zeros(depth.shape)
    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        shifted = _shift(filled, dy, dx)
        gap = np.abs(filled - shifted)
        seen = visible & _shift(visible, dy, dx)
        step = np.maximum(step, np.where(seen, np.nan_to_num(gap), np.inf))
        # A visible pixel next to empty space is the outer silhouette.
        step = np.where(visible & ~_shift(visible, dy, dx), np.inf, step)
    out = np.full(depth.shape, np.nan)
    out[visible] = np.clip(step[visible] / max(float(wavelength_mm), 1e-9), 0.0, 1.0)
    return out, visible


def albedo_break(bundle, wavelength_mm):
    """Material change independent of form, under the flat rig.

    On an UNTEXTURED mesh -- which every raw print is -- the flat rig is uniform by
    construction, so this channel is identically zero and carries no evidence. That is
    reported rather than hidden: a cue that is structurally incapable of firing on this
    input class must not be averaged in as though it had looked and found nothing.
    """
    lit, visible = bundle["rgb_lit"], bundle["visible"]
    if bundle["rig"] != "flat":
        return np.full(lit.shape, np.nan), np.zeros(lit.shape, dtype=bool)
    camera = bundle["camera"]
    radius_px = _band_radius_px(wavelength_mm, camera)
    filled = np.where(visible, lit, np.nan)
    total, count = _ring(filled, visible, radius_px)
    out = np.full(lit.shape, np.nan)
    live = (count > 0) & visible
    out[live] = np.abs(total[live] / count[live] - filled[live])
    spread = float(np.nanstd(out[live])) if live.any() else 0.0
    if spread <= 1e-9:
        # Structurally flat: no albedo variation exists to be found.
        return np.zeros(lit.shape), np.zeros(lit.shape, dtype=bool)
    return np.clip(out / (4.0 * spread), 0.0, 1.0), live


EXTRACTORS = {"cavity": cavity, "ridge": ridge, "plane": plane,
              "silhouette": silhouette, "albedo_break": albedo_break}


def extract(bundle, wavelength_mm, channels=CHANNELS):
    """All cues for one bundle at one band. Returns {channel: (map, valid)}."""
    return {name: EXTRACTORS[name](bundle, wavelength_mm) for name in channels}
