"""The recipe that rebuilds the ground-truth corpus from its CC0 sources.

Nothing here touches the network: the licence parser is fed real OpenGameArt
markup, and the cutting is fed arrays. The measurement that matters -- that a
clean rebuild reproduces all ten sources byte for byte -- needs the network and
is recorded in HANDOFF rather than run here.
"""
import io
import zipfile

import numpy as np
import pytest
from PIL import Image

from scripts import fetch_truth


# Real OpenGameArt markup: several licences are several `field-item` divs INSIDE
# one licences field, not several fields. Getting that wrong is how a test can
# pass while the parser it is guarding does the opposite on a live page.
ITEM = ("<div class=\"field-item even\"><div class='license-icon'>"
        "<a href='%s' target='_blank'><img src='x.png' alt='' title=''>"
        "<div class='license-name'>%s</div></a></div></div>")

FIELD = ('<div class="field field-name-field-art-licenses'
         ' field-type-taxonomy-term-reference field-label-above">'
         '<div class="field-label">License(s):&nbsp;</div>'
         '<div class="field-items">%s</div></div>'
         '<div class="field field-name-collect field-type-ds field-label-above">')

CC0_DEED = "http://creativecommons.org/publicdomain/zero/1.0/"


def _page(pairs, before=""):
    return before + FIELD % "".join(ITEM % (deed, name) for deed, name in pairs)


def _feed(monkeypatch, html):
    monkeypatch.setattr(fetch_truth, "fetch", lambda url, cache: html.encode())


def test_a_cc0_licence_field_passes(monkeypatch):
    _feed(monkeypatch, _page([(CC0_DEED, "CC0")]))
    ok, why = fetch_truth.licensed_cc0("http://example/x", "/tmp")
    assert ok is True, why


def test_a_share_alike_licence_is_refused(monkeypatch):
    """The guard has to actually bite; one that never fires is worthless."""
    _feed(monkeypatch, _page([("http://creativecommons.org/licenses/by-sa/3.0/",
                               "CC-BY-SA 3.0")]))
    ok, why = fetch_truth.licensed_cc0("http://example/x", "/tmp")
    assert ok is False
    assert "CC-BY-SA 3.0" in why


def test_a_dual_licensed_asset_is_refused(monkeypatch):
    """CC0 listed BESIDE another licence is not the same as CC0. The looser
    licence is the one that binds a reuser who picks it, and this project's rule
    is CC0 only."""
    _feed(monkeypatch, _page([(CC0_DEED, "CC0"),
                              ("http://creativecommons.org/licenses/by/3.0/",
                               "CC-BY 3.0")]))
    ok, _why = fetch_truth.licensed_cc0("http://example/x", "/tmp")
    assert ok is False


def test_cc0_mentioned_outside_the_licence_field_does_not_count(monkeypatch):
    """A page can say CC0 in a comment, in a list of the author's other work, or
    in the title. Only the licence field binds, so only it is read."""
    _feed(monkeypatch, "<p>All my other art is CC0!</p>" +
          _page([("http://creativecommons.org/licenses/by/4.0/", "CC-BY 4.0")]))
    ok, _why = fetch_truth.licensed_cc0("http://example/x", "/tmp")
    assert ok is False


def test_a_page_with_no_licence_field_is_refused(monkeypatch):
    _feed(monkeypatch, "<html><body>nothing here</body></html>")
    ok, why = fetch_truth.licensed_cc0("http://example/x", "/tmp")
    assert ok is None
    assert "licence field" in why


def test_a_licence_name_without_the_deed_is_refused(monkeypatch):
    """The name and the link have to agree. A page that says CC0 while linking a
    by-sa deed is malformed, and guessing which half is right is not this
    script's job."""
    _feed(monkeypatch, _page([("http://creativecommons.org/licenses/by-sa/3.0/",
                               "CC0")]))
    ok, _why = fetch_truth.licensed_cc0("http://example/x", "/tmp")
    assert ok is False


def test_padding_leaves_the_art_where_it_was():
    """`pad` exists because a character whose feet sit on the last row cannot be
    planted. It must add rows, never move the art within its own columns."""
    cell = np.zeros((4, 3, 4), np.uint8)
    cell[3, 1] = (10, 20, 30, 255)
    out = fetch_truth._padded(cell, 2)
    assert out.shape == (8, 3, 4)
    assert tuple(out[5, 1]) == (10, 20, 30, 255)
    assert not out[:2].any() and not out[6:].any()


def test_no_padding_returns_the_cell_itself():
    cell = np.zeros((4, 3, 4), np.uint8)
    assert fetch_truth._padded(cell, 0) is cell


def _zip_of(frames):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, array in frames.items():
            raw = io.BytesIO()
            Image.fromarray(array).save(raw, format="PNG")
            archive.writestr(name, raw.getvalue())
    return buffer.getvalue()


def test_per_frame_files_compose_in_numeric_order(tmp_path):
    """Some authors ship a PNG per frame. Laying them side by side keeps every
    frame in the SAME coordinate space, which is what the alignment check exists
    to enforce -- and the order must be numeric, or frame 10 sorts before 2.
    """
    frames = {}
    for index in range(12):
        art = np.zeros((4, 3, 4), np.uint8)
        art[0, 0] = (index, 0, 0, 255)
        frames["1x/run_%d.png" % index] = art
    data = _zip_of(frames)
    subject = {"name": "x", "frames_dir": "1x"}
    path = fetch_truth.strip_from_frames(data, {"frames": "run"}, subject,
                                         str(tmp_path))
    strip = np.array(Image.open(path).convert("RGBA"))
    assert strip.shape == (4, 3 * 12, 4)
    assert [int(strip[0, 3 * i, 0]) for i in range(12)] == list(range(12))


def test_a_missing_clip_is_an_error_not_an_empty_strip(tmp_path):
    data = _zip_of({"1x/run_0.png": np.zeros((4, 3, 4), np.uint8)})
    with pytest.raises(KeyError):
        fetch_truth.strip_from_frames(data, {"frames": "idle"},
                                      {"name": "x", "frames_dir": "1x"},
                                      str(tmp_path))


def test_every_subject_records_where_it_came_from():
    """A number nobody can reproduce is the one thing this project has been
    strict about everywhere else."""
    for subject in fetch_truth.SUBJECTS:
        assert subject["page"].startswith("https://opengameart.org/content/")
        assert subject["url"].startswith("https://opengameart.org/sites/")
        assert subject["clips"], subject["name"]
        assert subject["facing"] in ("left", "right", "front", "back")
        for clip, spec in subject["clips"].items():
            assert spec["columns"], (subject["name"], clip)
            assert len(spec["rows"]) == 2


def test_the_subject_names_are_the_ones_handoff_quotes():
    names = {s["name"] for s in fetch_truth.SUBJECTS}
    assert {"sumohulk", "horse", "forest", "mv-male", "eldiran"} <= names
    assert {"deer", "boar", "shieldmaiden", "samurai", "slime"} <= names
