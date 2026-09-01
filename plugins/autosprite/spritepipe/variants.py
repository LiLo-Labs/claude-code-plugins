"""Outfit and skin variants, by moving whole shading ramps rather than colours.

The naive way to recolour a sprite is to swap one colour for another. It always
looks wrong, because a sprite's colours are not independent: the four blues of a
cloak are one material's light, midtone, shadow and outline, and replacing the
midtone alone leaves a cloak lit by two different suns.

So the unit of recolouring here is the RAMP -- the group of shades that belong to
one material, ordered dark to light. A variant rotates a whole ramp's hue and
scales its saturation while leaving every value exactly where it was, so the
shading survives untouched and the character stays recognisably the same
character in a different coat.

Naming the ramps ("this one is the skin, this one is the cloak") is the one part
a model does better than arithmetic, and `ramp_atlas` renders the picture that
makes that call easy to get right.
"""

import colorsys

import numpy as np

from . import image as img
from . import palette as palette_module


def describe(pixels, ramps):
    """Per-ramp facts a model can name a ramp from without guessing.

    Share and position are what separate the skin from the eye highlight: the
    skin is 20% of the sprite and everywhere, the highlight is 0.4% of it and in
    one place. A model given only the colours has to guess; given these it does
    not have to.
    """
    height, width = pixels.shape[:2]
    solid = img.alpha_mask(pixels)
    total = max(1, int(solid.sum()))
    out = []
    for ramp in ramps:
        mask = np.zeros((height, width), dtype=bool)
        for colour in ramp["colours"]:
            mask |= (pixels == np.array(colour, dtype=np.uint8)).all(axis=2)
        mask &= solid
        count = int(mask.sum())
        entry = {"id": ramp["id"], "colours": ramp["colours"], "grey": ramp["grey"],
                 "hue": ramp["hue"], "pixels": count,
                 "share": round(count / total, 4), "shades": len(ramp["colours"])}
        if count:
            ys, xs = np.nonzero(mask)
            entry["centroid"] = [round(float(xs.mean()) / width, 3),
                                 round(float(ys.mean()) / height, 3)]
            entry["box"] = [round(float(xs.min()) / width, 3),
                            round(float(ys.min()) / height, 3),
                            round(float(xs.max() + 1) / width, 3),
                            round(float(ys.max() + 1) / height, 3)]
        out.append(entry)
    return sorted(out, key=lambda entry: -entry["pixels"])


def ramp_atlas(pixels, ramps, dim=(60, 60, 70, 255)):
    """One image per ramp: that ramp in full colour, the rest dimmed.

    This is what a vision model is shown to name the ramps. Asking it to name
    colours from a hex list is asking it to guess; showing it the cloak lit up
    on the character is asking it to read.
    """
    frames = []
    for ramp in ramps:
        mask = np.zeros(pixels.shape[:2], dtype=bool)
        for colour in ramp["colours"]:
            mask |= (pixels == np.array(colour, dtype=np.uint8)).all(axis=2)
        frame = pixels.copy()
        keep = img.alpha_mask(frame)
        frame[keep & ~mask] = dim
        frames.append(frame)
    return frames


def retint(colour, hue=None, saturation=1.0, value=1.0, grey_to_hue=True):
    """Move one colour's hue and saturation, keeping its value.

    Value is what carries the shading, so it is scaled and never replaced. A
    grey has no hue to rotate, so `grey_to_hue` decides whether a grey ramp can
    be tinted at all -- for steel-to-gold it must, for an outline it must not.
    """
    red, green, blue, alpha = (int(v) for v in colour)
    h, s, v = colorsys.rgb_to_hsv(red / 255.0, green / 255.0, blue / 255.0)
    if hue is not None:
        if s > 0.02 or grey_to_hue:
            h = (float(hue) % 360.0) / 360.0
            if s <= 0.02 and grey_to_hue:
                # A grey given a hue needs some saturation or it stays grey.
                s = 0.45
    s = max(0.0, min(1.0, s * float(saturation)))
    v = max(0.0, min(1.0, v * float(value)))
    out = colorsys.hsv_to_rgb(h, s, v)
    return [int(round(channel * 255)) for channel in out] + [alpha]


def build_mapping(ramps, spec, names=None):
    """{old rgba tuple: new rgba list} for a variant spec.

    `spec` keys are ramp names when `names` maps id -> name, or ramp ids. Each
    value is {"hue": deg, "saturation": x, "value": x} or {"colours": [...]}
    for an explicit replacement.
    """
    by_key = {}
    for ramp in ramps:
        by_key[str(ramp["id"])] = ramp
        if names and ramp["id"] in names:
            by_key[str(names[ramp["id"]]).lower()] = ramp

    mapping, unmatched = {}, []
    for key, change in spec.items():
        ramp = by_key.get(str(key).lower())
        if ramp is None:
            unmatched.append(key)
            continue
        explicit = change.get("colours") if isinstance(change, dict) else None
        if explicit:
            if len(explicit) != len(ramp["colours"]):
                raise ValueError(
                    "ramp %r has %d shades but %d replacement colours were given; "
                    "a ramp must be replaced shade for shade or its shading breaks"
                    % (key, len(ramp["colours"]), len(explicit)))
            for old, new in zip(ramp["colours"], explicit):
                mapping[tuple(old)] = list(new) + ([old[3]] if len(new) == 3 else [])
            continue
        for old in ramp["colours"]:
            mapping[tuple(old)] = retint(
                old, change.get("hue"), change.get("saturation", 1.0),
                change.get("value", 1.0), change.get("grey_to_hue", True))
    return mapping, unmatched


def recolour(pixels, mapping):
    """Apply a colour mapping. Anything unmapped is left exactly as it was."""
    out = pixels.copy()
    for old, new in mapping.items():
        hits = (pixels == np.array(old, dtype=np.uint8)).all(axis=2)
        if hits.any():
            out[hits] = np.array(new, dtype=np.uint8)
    return out


def variant(pixels, spec, names=None, ramps=None):
    """Recolour a reference by ramp. Returns (pixels, report)."""
    ramps = ramps if ramps is not None else palette_module.ramps(
        palette_module.lock(pixels), pixels)
    mapping, unmatched = build_mapping(ramps, spec, names)
    out = recolour(pixels, mapping)
    report = {"ramps": len(ramps), "colours_changed": len(mapping),
              "unmatched": unmatched}
    if unmatched:
        known = sorted(set([str(r["id"]) for r in ramps]
                           + [str(v) for v in (names or {}).values()]))
        report["hint"] = ("no ramp named %s; the rig knows %s"
                          % (", ".join(map(str, unmatched)), ", ".join(known)))
    return out, report
