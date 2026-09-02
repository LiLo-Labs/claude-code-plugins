"""Ask a model to draw the frames, then make them obey the source art.

Everything else in this plugin animates by MOVING the user's pixels. That is
provably faithful and it has a ceiling, measured and recorded in HANDOFF: a
rigid part cannot bend a knee, turn a head, or foreshorten a limb swinging at
the camera, because those need pixels the source does not contain.

This module is the other half. A model draws the frame; `conform` then forces it
onto the source's grid, palette and alpha, so what comes back is still made of
the artist's own colours on the artist's own pixel grid. The generative step is
allowed to invent SHAPE. It is not allowed to invent COLOUR.

Two things make this more than a wrapper around somebody's API, and both come
out of work already done here:

**We have a rig, so we can condition on a pose.** A generic sprite tool sends a
reference image and a text prompt and hopes. We can render the character's own
skeleton in the exact pose of frame five of its own walk cycle -- fitted to that
character's proportions, not a stock human's -- and hand that over as a control
image. That is what AutoSprite's pose-sequence branch does, except their poses
come from a library and ours come from the subject.

**We have ground truth, so we can tell whether it worked.** `ground_truth.py`
scores frames against the artist's own animation of the same clip. So a
generative backend is not a demo here, it is a hypothesis with a number: does it
beat the cutout pipeline's 30.46%, on the same twelve clips, measured the same
way? Nothing else in this market publishes such a number about itself.
"""

import base64
import io
import json
import os
import time
import urllib.error
import urllib.request

import numpy as np

from . import conform as conform_module
from . import image as img
from . import ingest as ingest_module

REPLICATE = "https://api.replicate.com/v1"
TIMEOUT = 300


class Unavailable(Exception):
    """No credentials, no credit, or the service refused. Never a crash: the
    cutout path is always there and always works."""


def token(env="REPLICATE_API_TOKEN", path="~/.config/spritepipe/keys.env"):
    """The API token from the environment, or from a key file outside the repo.

    Read from a file rather than only the environment because a long session
    loses exported variables between shells, and because a token must never be
    committed -- the file lives in the user's config directory, not the tree.
    """
    found = os.environ.get(env)
    if found:
        return found.strip()
    full = os.path.expanduser(path)
    if os.path.exists(full):
        for line in open(full):
            name, _, value = line.partition("=")
            if name.strip() == env:
                return value.strip()
    raise Unavailable("no %s in the environment or %s" % (env, path))


def data_uri(pixels):
    """A PNG data URI for an RGBA array, which is how every one of these APIs
    takes an image without a separate upload step."""
    from PIL import Image
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def _post(url, payload, api_token, wait=True):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + api_token,
                 "Content-Type": "application/json",
                 **({"Prefer": "wait"} if wait else {})})
    try:
        return json.load(urllib.request.urlopen(request, timeout=TIMEOUT))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")[:400]
        if error.code in (401, 402, 403, 429):
            raise Unavailable("%s: %s" % (error.code, body))
        raise


def _get(url, api_token):
    request = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + api_token})
    return json.load(urllib.request.urlopen(request, timeout=TIMEOUT))


def settled(answer, api_token, patience=900, every=5):
    """Poll a prediction until it finishes, and return it.

    `Prefer: wait` holds the connection for about a minute and then hands back
    whatever the job is doing, which for a still image is the answer and for a
    VIDEO is `{"status": "starting"}`. Reading that as a failure is how two
    video jobs were reported dead here while they were both running fine.
    """
    if answer.get("status") in ("succeeded", "failed", "canceled"):
        return answer
    url = (answer.get("urls") or {}).get("get")
    if not url:
        return answer
    deadline = time.time() + patience
    while time.time() < deadline:
        answer = _get(url, api_token)
        if answer.get("status") in ("succeeded", "failed", "canceled"):
            return answer
        time.sleep(every)
    raise Unavailable("still %s after %ds" % (answer.get("status"), patience))


def _fetch(url):
    return urllib.request.urlopen(url, timeout=TIMEOUT).read()


# How far into a generated video a character is still ITSELF.
#
# Measured on the corpus knight, silhouette pixels differing from the source, by
# video frame: 0 at frames 0-7, 11 at frame 10, 74 at 12, 125 at 15, 193 at 18,
# and 200-270 from frame 20 to the end. The model holds the character exactly for
# about a third of a second and then replaces it with a generic humanoid.
#
# So a clip is the FIRST few frames of a video, not a whole video, and a sheet is
# several short videos rather than one long one -- every call re-anchors on the
# true sprite and starts again at zero drift.
ANCHORED = 18


def sampled(video, count, until=ANCHORED):
    """`count` frames evenly spaced over the anchored window of a video.

    Not the lowest-drift frames. Picking those selects the frames where the
    character has not moved yet, which scores perfectly and animates nothing --
    the same one-sided mistake `quality.footprint` makes, and it is worth not
    making twice.
    """
    import numpy as _np
    end = min(int(until), len(video) - 1)
    if end <= 0:
        return [video[0]]
    return [video[i] for i in _np.linspace(0, end, int(count)).astype(int)]


def calibrate(frame, source, tolerance=30):
    """(scale, floor) read once off a video's FIRST frame, for reuse on the rest.

    The first frame of an anchored video is the source sprite -- drift measured
    at 0 -- so it is the one frame whose scale is known to be right, and the only
    honest place to measure from.

    Measuring per frame instead is a real bug and it corrupted every pose that
    changes the silhouette's bounding box. Scaling each frame so its content
    HEIGHT matches the source means a character raising a sword above its head
    gets taller content, so the body is shrunk to compensate -- and the fitted
    attack came back squashed, with the rig contorting to explain a shortening
    that the model never drew.
    """
    cleaned, _how = ingest_module.remove_background(frame_rgba(frame),
                                                    tolerance=tolerance)
    box = img.content_box(cleaned)
    if box is None or box[3] <= box[1]:
        return None, None
    inside = img.content_box(source)
    return (inside[3] - inside[1]) / float(box[3] - box[1]), inside[3]


def frame_rgba(frame):
    if frame.shape[-1] == 3:
        return np.dstack([frame, np.full(frame.shape[:2], 255, np.uint8)])
    return frame


def to_sprite(frame, source, tolerance=30, scale=None, floor=None):
    """One video frame reduced to a sprite on `source`'s grid and palette.

    Pass `scale` and `floor` from `calibrate` on the video's first frame and
    every frame of the clip is measured the same way. Without them each frame is
    normalised against itself, which reads a raised arm as a shrinking body.

    Aligned by the FLOOR rather than by the box, because a character stands on
    the ground and its feet are the part that must not wander; the top of the
    content moves whenever the pose does.
    """
    from PIL import Image
    cleaned, _how = ingest_module.remove_background(frame_rgba(frame),
                                                    tolerance=tolerance)
    box = img.content_box(cleaned)
    # An empty box, not just a missing one: a frame the model rendered blank --
    # or one whose whole content the background removal took -- yields a
    # DEGENERATE box rather than None, and cropping to it returns a fully
    # transparent sprite that would slip into a sheet as a missing frame.
    if box is None or box[2] <= box[0] or box[3] <= box[1]:
        return None
    crop = cleaned[box[1]:box[3], box[0]:box[2]]
    inside = img.content_box(source)
    if scale is None:
        scale = (inside[3] - inside[1]) / float(crop.shape[0])
    if floor is None:
        floor = inside[3]
    tall = max(1, int(round(crop.shape[0] * float(scale))))
    wide = max(1, int(round(crop.shape[1] * float(scale))))
    small = np.array(Image.fromarray(crop).resize((wide, tall), Image.NEAREST))
    out = img.blank(source.shape[0], source.shape[1])
    img.paste(out, small, (source.shape[1] - wide) // 2, int(floor) - tall)
    return conform_module.conform(out, source)[0]


def drift(pixels, source):
    """Silhouette pixels differing from the source. The identity metric.

    `quality.footprint` cannot judge a generated frame -- it asks whether the
    same pixels moved, and a redrawn character does not occupy the same pixels at
    all, so it scores every generative result at 85% regardless of quality. This
    asks the question that actually matters about generation: is this still the
    user's character?
    """
    base = img.alpha_mask(ingest_module.remove_background(source)[0])
    return int((img.alpha_mask(pixels) ^ base).sum())


class ReplicateBackend:
    """Frames from a model hosted on Replicate.

    `retro-diffusion/rd-animation` is the one purpose-built for this: it is a
    pixel-art model trained on sprite sheets rather than a general image model
    asked nicely, and it returns a spritesheet rather than a picture of one.
    Its Replicate build exposes four prompt-driven styles; the eight
    image-conditioned ones (`walking`, `idle`, `attack`, `jump`, `crouch`,
    `destroy`, `custom_action`, `subtle_motion`) live on Retro Diffusion's own
    API, which also takes an `input_palette`. Worth a second key when this one
    proves out.
    """

    name = "replicate"

    def __init__(self, model="retro-diffusion/rd-animation", api_token=None):
        self.model = model
        self.token = api_token or token()

    def animate(self, reference, prompt, style="walking_and_idle", size=48,
                seed=None, sheet=True):
        """(pixels, report) -- a raw spritesheet from the model, unconformed."""
        payload = {"input": {"prompt": prompt, "style": style,
                             "width": int(size), "height": int(size),
                             "input_image": data_uri(reference),
                             "return_spritesheet": bool(sheet)}}
        if seed is not None:
            payload["input"]["seed"] = int(seed)
        answer = settled(_post("%s/models/%s/predictions" % (REPLICATE, self.model),
                               payload, self.token), self.token)
        if answer.get("status") == 402 or answer.get("detail"):
            raise Unavailable(str(answer.get("detail"))[:300])
        output = answer.get("output")
        if isinstance(output, list):
            output = output[0] if output else None
        if not output:
            raise Unavailable("no output: %s" % str(answer.get("error"))[:200])
        from PIL import Image
        raw = np.array(Image.open(io.BytesIO(_fetch(output))).convert("RGBA"))
        return raw, {"model": self.model, "style": style,
                     "size": [int(raw.shape[1]), int(raw.shape[0])],
                     "id": answer.get("id")}


def split_sheet(sheet, count):
    """A returned spritesheet cut into `count` frames along its long axis.

    Every one of these services returns a strip and none of them agrees on the
    layout, so the honest thing is to measure it: whichever axis divides evenly
    by the frame count is the one the frames run along.
    """
    height, width = sheet.shape[:2]
    if count <= 1:
        return [sheet]

    def across(step):
        return [sheet[:, i * step:(i + 1) * step] for i in range(count)]

    def down(step):
        return [sheet[i * step:(i + 1) * step, :] for i in range(count)]

    # The frames run along whichever axis is LONGER -- a strip of eight frames
    # is eight times longer in the direction the animation goes. Testing
    # divisibility first instead gets a tall strip wrong every time: a 16x64
    # sheet of four frames divides evenly across its 16px WIDTH too, and cutting
    # there returns four 4px slivers of one frame rather than four frames.
    wide = width >= height
    if wide and width % count == 0:
        return across(width // count)
    if not wide and height % count == 0:
        return down(height // count)
    if width % count == 0:
        return across(width // count)
    if height % count == 0:
        return down(height // count)
    # Nothing divides evenly. Cut the longer axis approximately rather than hand
    # back a different number of frames than the caller asked for.
    return across(max(1, width // count)) if wide else down(max(1, height // count))


def frames(backend, reference, prompt, count, tolerance=12, **kwargs):
    """Generated frames, each conformed to `reference`'s grid and palette.

    The list that comes back is safe to hand to `verify` and to
    `ground_truth.measure`: every pixel is a colour the source already had,
    because `conform` assigns it one.
    """
    sheet, report = backend.animate(reference, prompt, **kwargs)
    out, reports = [], []
    for piece in split_sheet(sheet, count):
        pixels, how = conform_module.conform(piece, reference, tolerance)
        out.append(pixels)
        reports.append(how)
    report["frames"] = len(out)
    report["conform"] = reports
    return out, report
