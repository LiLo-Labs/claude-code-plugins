"""A verifier that cannot fail is worth nothing. These are the failures.

Every test here breaks exactly one artefact of a known-good build and asserts
that the corresponding check goes red -- because every one of these corruptions
produces a sheet that still opens, still looks right, and is still wrong.
"""

import json
import os
import zipfile

import pytest

from spritepipe import image, pipeline, verify


@pytest.fixture
def built(hero_path, tmp_path):
    out = str(tmp_path / "out")
    result = pipeline.build_sheet(hero_path, out, animations=["idle", "walk"],
                                  engines=("all",))
    assert result.verification.ok, result.verification.report()
    return {"dir": out, "name": "hero", "reference": hero_path,
            "rig": result.written["rig"], "result": result}


def run(built, **kwargs):
    return verify.verify_directory(built["dir"], built["name"],
                                   kwargs.get("reference", built["reference"]),
                                   kwargs.get("rig", built["rig"]))


def check(result, name):
    return next(c for c in result.checks if c["check"] == name)


def test_a_clean_build_passes_every_check(built):
    result = run(built)
    assert result.ok, result.report()
    assert not any(c["skipped"] for c in result.checks)


def test_a_rect_pushed_off_the_sheet_is_caught(built):
    path = os.path.join(built["dir"], "hero.autosprite.json")
    document = json.load(open(path))
    document["clips"][0]["frames"][0]["x"] += 10000
    json.dump(document, open(path, "w"))
    assert not check(run(built), "RECT")["ok"]


def test_a_rect_moved_onto_empty_texture_is_caught(built):
    """One row off looks perfect and animates with a one-pixel jitter."""
    path = os.path.join(built["dir"], "hero.autosprite.json")
    document = json.load(open(path))
    frame = document["clips"][0]["frames"][0]
    frame["x"], frame["y"], frame["w"], frame["h"] = 0, 0, 1, 1
    json.dump(document, open(path, "w"))
    assert not check(run(built), "RECT")["ok"]


def test_a_zip_frame_that_no_longer_matches_the_sheet_is_caught(built):
    path = os.path.join(built["dir"], "hero-frames.zip")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        contents = {name: archive.read(name) for name in names}
    contents[names[0]] = contents[names[1]]
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    assert not check(run(built), "ZIP")["ok"]


def test_a_missing_zip_frame_is_caught(built):
    path = os.path.join(built["dir"], "hero-frames.zip")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        contents = {name: archive.read(name) for name in names[1:]}
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    assert not check(run(built), "ZIP")["ok"]


def test_a_colour_that_was_never_in_the_art_is_caught(built):
    sheet_path = os.path.join(built["dir"], "hero.png")
    sheet = image.load(sheet_path)
    box = image.content_box(sheet)
    sheet[box[1], box[0]] = [7, 254, 13, 255]
    image.save(sheet, sheet_path)
    result = run(built)
    assert not check(result, "PALETTE")["ok"]
    assert "not in the source art" in check(result, "PALETTE")["detail"]


def test_the_palette_check_no_longer_needs_to_be_told_the_reference(built):
    """The atlas records every image a pixel is allowed to have come from, so
    the check can run on an output directory alone."""
    result = verify.verify_directory(built["dir"], built["name"], None, built["rig"])
    palette_check = check(result, "PALETTE")
    assert palette_check["ok"] and not palette_check["skipped"]


def test_the_palette_check_is_skipped_rather_than_faked_when_nothing_is_known(built):
    """An atlas from before sources were recorded, and no --reference: there is
    no allowed set to check against, and saying so beats inventing one."""
    path = os.path.join(built["dir"], "hero.autosprite.json")
    document = json.load(open(path))
    document.pop("sources", None)
    json.dump(document, open(path, "w"))
    result = verify.verify_directory(built["dir"], built["name"], None, built["rig"])
    assert check(result, "PALETTE")["skipped"]


def test_a_source_that_has_changed_on_disk_is_reported_not_trusted(built):
    """A source file is the authority for what colours are allowed, so a
    verifier that silently accepts a swapped one proves nothing at all."""
    reference = image.load(built["reference"])
    reference[0, 0] = [7, 254, 13, 255]
    image.save(reference, built["reference"])
    result = run(built)
    assert not check(result, "PALETTE")["ok"]
    assert "changed on disk" in check(result, "PALETTE")["detail"]


def test_a_missing_source_is_reported_rather_than_ignored(built):
    path = os.path.join(built["dir"], "hero.autosprite.json")
    document = json.load(open(path))
    document["sources"] = [dict(document["sources"][0], path="/nowhere/gone.png")]
    json.dump(document, open(path, "w"))
    result = verify.verify_directory(built["dir"], built["name"], None, built["rig"])
    assert check(result, "PALETTE")["skipped"] or not check(result, "PALETTE")["ok"]


def test_a_front_view_may_carry_a_colour_the_side_view_does_not(hero_path, tmp_path):
    """The bug this was built for. A front reference exists to show what the
    side cannot; a check that allows only the side view's colours fails a build
    that is entirely correct."""
    import make_fixture

    front_path = str(tmp_path / "front.png")
    art = make_fixture.humanoid()
    art[2, 2] = [200, 20, 200, 255]
    make_fixture.write(front_path, make_fixture.on_background(art))
    result = pipeline.build_sheet(hero_path, str(tmp_path / "out"),
                                  animations=["idle"], direction_set="4",
                                  front=front_path, engines=())
    assert result.verification.ok, result.verification.report()


def test_an_engine_file_that_disagrees_with_the_atlas_is_caught(built):
    """This is the bug that works in Phaser and not in Godot."""
    path = os.path.join(built["dir"], "hero.phaser.json")
    document = json.load(open(path))
    key = sorted(document["frames"])[0]
    document["frames"][key]["frame"]["x"] += 3
    json.dump(document, open(path, "w"))
    result = run(built)
    assert not check(result, "ENGINES")["ok"]
    assert "phaser" in check(result, "ENGINES")["detail"]


def test_a_unity_meta_with_unflipped_y_is_caught(built):
    path = os.path.join(built["dir"], "hero.png.meta")
    text = open(path).read().replace("      y: ", "      y: 1", 1)
    open(path, "w").write(text)
    assert not check(run(built), "ENGINES")["ok"]


def test_a_godot_resource_missing_an_animation_is_caught(built):
    path = os.path.join(built["dir"], "hero.tres")
    text = open(path).read().replace('&"walk"', '&"stroll"')
    open(path, "w").write(text)
    result = run(built)
    assert not check(result, "ENGINES")["ok"]
    assert "walk" in check(result, "ENGINES")["detail"]


def test_a_clip_whose_frames_disagree_about_the_anchor_is_caught(built):
    path = os.path.join(built["dir"], "hero.autosprite.json")
    document = json.load(open(path))
    document["clips"][0]["frames"][1]["anchor"][1] += 2
    json.dump(document, open(path, "w"))
    assert not check(run(built), "ANCHOR")["ok"]


def test_a_mislabelled_rig_still_reassembles_and_rest_says_so(built):
    """The limit of this check, asserted rather than left to be discovered.

    Shrinking the head box is a rig that is wrong -- the head is cut off -- and
    it reassembles perfectly, because the pixels it stops covering are carried
    by the root instead. REST is about the CUT, not about the naming; the
    preview render is what catches a wrong name.
    """
    document = json.load(open(built["rig"]))
    for part in document["parts"]:
        if part["role"] == "head":
            part["box"][3] = max(part["box"][1] + 1, part["box"][3] - 2)
    json.dump(document, open(built["rig"], "w"))
    assert check(run(built), "REST")["ok"]


def test_rest_catches_a_cut_that_loses_pixels(hero_path, monkeypatch):
    """The regression this check exists for, and has already caught once.

    Boxes are not a tiling: a rig names the parts it can see, so some opaque
    pixels always fall outside every box. They belong to the root, and the cut
    grows the root's window to reach them. Cutting the root from its declared
    box instead drops them, and drops them silently -- the sheet still builds.
    """
    from spritepipe import cutout, ingest, vision

    reference = ingest.ingest(hero_path)
    built = vision.TemplateBackend().rig(reference)
    for part in built.parts:      # shrink every box so the art is under-covered
        x0, y0, x1, y1 = part.box
        part.box = (x0, y0, max(x0 + 1, x1 - 1), max(y0 + 1, y1 - 1))

    pieces = cutout.cut(built, reference.pixels)
    assert pieces.strays > 0, "the fixture must actually under-cover the art"
    assert image.equal(pieces.rest(), reference.pixels)

    monkeypatch.setattr(cutout, "extraction_boxes",
                        lambda rig, owner: [part.box for part in rig.parts])
    assert not image.equal(cutout.cut(built, reference.pixels).rest(),
                           reference.pixels)


def test_a_structurally_invalid_rig_is_caught_before_the_rest_check(built):
    document = json.load(open(built["rig"]))
    for part in document["parts"]:
        part["parent"] = None
    json.dump(document, open(built["rig"], "w"))
    assert "invalid" in check(run(built), "REST")["detail"]


def test_a_rig_for_a_different_character_is_caught(built):
    document = json.load(open(built["rig"]))
    document["size"] = [document["size"][0] + 5, document["size"][1]]
    json.dump(document, open(built["rig"], "w"))
    assert not check(run(built), "REST")["ok"]


def test_a_directory_with_no_atlas_says_so(tmp_path):
    result = verify.verify_directory(str(tmp_path))
    assert not result.ok
    assert "autosprite.json" in result.checks[0]["detail"]


def test_a_missing_sheet_is_caught(built):
    os.remove(os.path.join(built["dir"], "hero.png"))
    assert not run(built).ok


def test_the_name_is_found_without_being_told(built):
    result = verify.verify_directory(built["dir"], None, built["reference"], built["rig"])
    assert result.ok, result.report()


def test_the_report_names_every_check_and_its_verdict(built):
    text = run(built).report()
    for name in ("ATLAS", "RECT", "ZIP", "PALETTE", "ENGINES", "ANCHOR", "REST"):
        assert name in text
    assert "passed" in text


def test_a_tampered_per_animation_frame_is_caught(built):
    """The per-animation download is a second copy of the same pixels, and a
    second copy is the thing that silently drifts."""
    import io as _io
    from PIL import Image as _PIL

    path = os.path.join(built["dir"], "hero-animations.zip")
    with zipfile.ZipFile(path) as archive:
        entries = {entry: archive.read(entry) for entry in archive.namelist()}
    target = next(entry for entry in entries if entry.endswith("frames/01.png"))
    corrupted = _PIL.open(_io.BytesIO(entries[target])).convert("RGBA")
    pixels = corrupted.load()
    pixels[0, 0] = (255, 0, 255, 255)
    buffer = _io.BytesIO()
    corrupted.save(buffer, "PNG")
    entries[target] = buffer.getvalue()
    with zipfile.ZipFile(path, "w") as archive:
        for entry, data in entries.items():
            archive.writestr(entry, data)

    result = run(built)
    assert not result.ok
    assert not check(result, "ANIMZIP")["ok"]


def test_a_missing_animation_folder_is_caught(built):
    path = os.path.join(built["dir"], "hero-animations.zip")
    with zipfile.ZipFile(path) as archive:
        entries = {entry: archive.read(entry) for entry in archive.namelist()
                   if not entry.startswith("walk/")}
    with zipfile.ZipFile(path, "w") as archive:
        for entry, data in entries.items():
            archive.writestr(entry, data)
    result = run(built)
    assert not result.ok
    assert not check(result, "ANIMZIP")["ok"]
