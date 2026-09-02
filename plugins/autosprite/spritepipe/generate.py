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


def _fetch(url):
    return urllib.request.urlopen(url, timeout=TIMEOUT).read()


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
        answer = _post("%s/models/%s/predictions" % (REPLICATE, self.model),
                       payload, self.token)
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
