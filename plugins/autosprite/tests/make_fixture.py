"""Synthetic sprites, so the whole pipeline can be tested without shipping art.

`.gitignore` excludes PNGs from this repository on purpose, so every fixture is
generated. That turns out to be the better arrangement anyway: a parametric
character can be made to have or not have the exact property a test is about --
arms clear of the body or touching it, legs parted or robed, a palette with
ramps or a single flat colour -- and a checked-in PNG can only ever have one.

The humanoid below is deliberately crude but structurally honest: a narrow head
over wider shoulders, arms clear of the torso, legs parted at the hips, and
three shading ramps. Those are the four things the rigger measures.
"""

import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spritepipe import image  # noqa: E402

SKIN = ([120, 88, 58, 255], [190, 148, 104, 255], [232, 196, 152, 255])
CLOTH = ([28, 44, 96, 255], [52, 88, 172, 255], [96, 140, 224, 255])
BOOT = ([38, 32, 28, 255], [78, 66, 58, 255])


def _shade(canvas, x0, y0, x1, y1, ramp):
    """Fill a box with a ramp: dark on the left edge, light on the right.

    Sprite shading is what makes the palette tests meaningful -- a flat block
    has one colour and proves nothing about ramps or about a recolour keeping
    its shading.
    """
    for x in range(x0, x1):
        span = max(1, x1 - x0)
        position = (x - x0) / float(span)
        index = 0 if position < 0.25 else (2 if position > 0.75 else 1)
        canvas[y0:y1, x:x + 1] = ramp[min(index, len(ramp) - 1)]


def humanoid(arms_clear=True, legs_parted=True, width=20, height=28):
    """A side-on humanoid with the landmarks the template rigger looks for.

    Every span is written out rather than derived from a proportion, because the
    fixture's whole job is to have exact, known gaps: the rigger finds the arms
    by the gap between arm and torso and the hips by the gap between the legs,
    and a fixture that closes either one silently tests a different code path
    than the one the test name claims.
    """
    canvas = image.blank(height, width)
    mid = width // 2

    head_w = max(3, width // 4)
    head_x0 = mid - head_w // 2
    head_bottom = max(3, int(height * 0.26))
    _shade(canvas, head_x0, 1, head_x0 + head_w, head_bottom, SKIN)

    hip = int(height * 0.58)
    torso_w = max(head_w + 2, int(width * 0.36))
    torso_x0 = mid - torso_w // 2
    torso_x1 = torso_x0 + torso_w
    _shade(canvas, torso_x0, head_bottom, torso_x1, hip, CLOTH)

    arm_w = max(2, width // 8)
    gap = 1 if arms_clear else 0
    arm_top, arm_bottom = head_bottom + 1, hip - 1
    far_x1 = torso_x0 - gap
    near_x0 = torso_x1 + gap
    if far_x1 - arm_w >= 0:
        _shade(canvas, far_x1 - arm_w, arm_top, far_x1, arm_bottom, SKIN)
    if near_x0 + arm_w <= width:
        _shade(canvas, near_x0, arm_top, near_x0 + arm_w, arm_bottom, SKIN)

    if legs_parted:
        # One clear column between the legs, so `find_split` has something real
        # to find rather than a rounding artefact.
        leg_w = max(2, (torso_w - 1) // 2)
        _shade(canvas, torso_x0, hip, torso_x0 + leg_w, height - 1, BOOT)
        _shade(canvas, torso_x1 - leg_w, hip, torso_x1, height - 1, BOOT)
    else:
        _shade(canvas, torso_x0, hip, torso_x1, height - 1, BOOT)
    return canvas


def creature(width=30, height=18):
    """A side-on quadruped: long body, head at the right, legs under the belly."""
    canvas = image.blank(height, width)
    belly = int(height * 0.62)
    _shade(canvas, 5, 3, width - 8, belly, CLOTH)                 # body
    _shade(canvas, width - 8, 1, width - 1, belly - 1, SKIN)      # head
    _shade(canvas, 0, 5, 4, belly - 3, CLOTH)                     # tail
    _shade(canvas, 7, belly, 10, height - 1, BOOT)                # hind leg
    _shade(canvas, width - 13, belly, width - 10, height - 1, BOOT)  # fore leg
    return canvas


def prop(width=12, height=12):
    """A gem: no limbs, no split, nothing for a rigger to find."""
    canvas = image.blank(height, width)
    for y in range(height):
        span = int((1.0 - abs(y - height / 2.0) / (height / 2.0)) * width / 2.0)
        if span <= 0:
            continue
        _shade(canvas, width // 2 - span, y, width // 2 + span, y + 1, CLOTH)
    return canvas


def on_background(sprite, colour=(255, 255, 255, 255), margin=4, upscale=1):
    """Put a sprite on an opaque background, optionally upscaled.

    This is what a user's file actually looks like: art off a website, on white,
    exported at 4x. Every ingest test needs it, and none of them should have to
    build it themselves.
    """
    art = image.scale_nearest(sprite, upscale) if upscale > 1 else sprite
    margin = margin * upscale
    height, width = art.shape[:2]
    canvas = image.blank(height + margin * 2, width + margin * 2)
    canvas[:, :] = colour
    image.paste(canvas, art, margin, margin)
    return canvas


def write(path, pixels):
    image.save(pixels, path)
    return path


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(target, exist_ok=True)
    for name, pixels in (("hero.png", on_background(humanoid())),
                         ("beast.png", on_background(creature())),
                         ("gem.png", on_background(prop()))):
        path = write(os.path.join(target, name), pixels)
        print("%s: %dx%d" % (path, pixels.shape[1], pixels.shape[0]))
