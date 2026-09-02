"""Props animate as one piece, and the spin is the only interesting one."""

import numpy as np
import pytest

from spritepipe import (cutout, image, motion, props, quality, render,
                        rig as R)


@pytest.fixture
def gem_rig():
    return R.Rig((10, 10), [R.Part("body", "body", (0, 0, 10, 10), None, (5, 10))])


def test_every_prop_animation_validates():
    for name, animation in props.LIBRARY.items():
        assert motion.validate_animation(animation.to_dict()) == [], name


def test_spin_squashes_to_edge_on_at_the_quarter_points():
    spin = props.get("spin")
    widths = [spin.root.sample(t, True).sx for t in spin.times()]
    assert min(widths) < 0.2
    assert max(widths) == pytest.approx(1.0)


def test_spin_mirrors_for_the_second_half_because_there_is_no_back_face(gem_rig):
    spin = props.get("spin")
    flips = [spin.pose_at(gem_rig, t).flip for t in spin.times()]
    assert flips[:4] == [False] * 4
    assert flips[4:] == [True] * 4


def test_tumble_turns_exactly_once_per_loop():
    tumble = props.get("tumble")
    angles = [tumble.root.sample(t, True).angle for t in tumble.times()]
    assert angles[0] == pytest.approx(0.0)
    assert angles[-1] < 360.0
    assert all(b >= a for a, b in zip(angles, angles[1:])), "a tumble must not reverse"


def test_tumble_turns_at_a_constant_rate():
    """Easing a tumble makes it look like it is hitting something."""
    tumble = props.get("tumble")
    angles = [tumble.root.sample(t, True).angle for t in tumble.times()]
    steps = [round(b - a, 3) for a, b in zip(angles, angles[1:])]
    assert len(set(steps)) == 1


def test_pulse_keeps_the_volume_so_it_reads_as_elastic():
    pulse = props.get("pulse")
    for t in pulse.times():
        sample = pulse.root.sample(t, True)
        assert 0.9 < sample.sx * sample.sy < 1.1


def test_presets_expand():
    assert [a.name for a in props.resolve(["pickup"])] == ["bob", "spin"]


def test_an_unknown_prop_animation_lists_what_exists():
    with pytest.raises(KeyError) as error:
        props.get("explode")
    assert "spin" in str(error.value)


def test_the_prop_and_character_libraries_do_not_collide():
    assert not set(props.LIBRARY) & set(motion.LIBRARY)


# ---------------------------------------------------------------------------
# Trait-addressed clips: the ones that work on a subject rather than a body.
# ---------------------------------------------------------------------------

def _samples(track, animation):
    """What this one track actually DRAWS, frame by frame, as comparable tuples.

    `cycle` is rounded to a whole number rather than to three places, because
    that is what the renderer does with it: a step of 0.996 and a step of 1.0
    are the same picture, and a test that called them different would pass on a
    clip the viewer sees hold still.
    """
    out = []
    for t in animation.times():
        pose = track.sample(t, animation.loop)
        out.append(tuple(round(getattr(pose, channel),
                               0 if channel == "cycle" else 3)
                         for channel in motion.CHANNELS))
    return out


TRAIT_CLIPS = ("turn", "sway", "gust", "ripple", "creak",
               "flicker", "shimmer")


@pytest.mark.parametrize("name", TRAIT_CLIPS)
def test_no_trait_clip_holds_the_same_picture_for_two_frames_running(name):
    """The defect a viewer actually sees: a stutter.

    Weaker than requiring every frame to differ, and it is the right rule for a
    channel with few values -- a flicker returns to its rest shade several times
    a cycle and that is what a flicker IS, but drawing the same shade twice in a
    row is a frame the viewer watches nothing happen in. The wrap counts: the
    last frame runs into the first.
    """
    animation = props.get(name)
    for selector, track in animation.tracks.items():
        samples = _samples(track, animation)
        pairs = list(zip(samples, samples[1:]))
        if animation.loop:
            pairs.append((samples[-1], samples[0]))
        for index, (before, after) in enumerate(pairs):
            assert before != after, (
                "%s's %s track draws the same pose on frames %d and %d"
                % (name, selector, index, (index + 1) % animation.frames))


AFFINE_TRAIT_CLIPS = ("turn", "sway", "gust", "ripple", "creak")


@pytest.mark.parametrize("name", AFFINE_TRAIT_CLIPS)
def test_a_trait_clip_is_still_distinct_when_it_drives_only_one_part(name):
    """The defect this was written for, and it was found on real art.

    A subject usually has ONE of each trait -- one cape, one canopy, one flag --
    so a trait clip's single track is the whole animation, and if that track's
    curve retraces its own path the clip is duplicate pictures. `sway` swung
    evenly out and back; on the first caped hero it was rigged against, eight
    frames drew five different pictures, and raising the amplitude changed
    nothing at all, because the problem was never the size of the swing.

    A character clip is not in this position -- a walk has legs in counter-phase
    -- which is why this is asserted of the subject library and not of both.
    """
    animation = props.get(name)
    for selector, track in animation.tracks.items():
        samples = _samples(track, animation)
        if not animation.loop and samples[0] == samples[-1]:
            # A one-shot starts and ends at rest, and those two being the same
            # pose is the clip being well formed rather than a wasted frame.
            samples = samples[:-1]
        assert len(set(samples)) == len(samples), (
            "%s's %s track draws %d different poses across %d frames; an evenly "
            "symmetric curve passes through the same values going out and "
            "coming back" % (name, selector, len(set(samples)), len(samples)))


def test_the_bob_does_not_draw_the_same_height_twice():
    """Four frames is not enough to spend one on a repeat."""
    bob = props.get("bob")
    assert len(set(_samples(bob.root, bob))) == bob.frames


def test_the_coin_spin_is_allowed_to_repeat_because_the_flip_is_the_difference():
    """Stated rather than left as an apparent oversight.

    A coin at 45 degrees and at 135 is the same width, so the squash alone
    repeats -- and the frames are still different pictures, because `flip_from`
    mirrors the second half. This is how hand-drawn coin spins have always
    worked.
    """
    spin = props.get("spin")
    assert spin.flip_from == 0.5
    widths = _samples(spin.root, spin)
    assert len(set(widths)) < spin.frames          # the squash alone repeats
    flips = [t >= spin.flip_from for t in spin.times()]
    assert len(set(zip(widths, flips))) > len(set(widths))


def test_a_trait_clip_drives_the_parts_that_have_the_trait_and_no_others():
    rig = R.Rig((16, 16), [
        R.Part("post", "body", (6, 6, 10, 16), None, (8, 15), 0),
        R.Part("flag", "accessory", (2, 2, 14, 7), "post", (7, 4), 1),
    ])
    assert props.get("sway").drives(rig)           # an accessory is a stalk
    assert not props.get("turn").drives(rig)       # nothing here is a spinner
    assert props.get("turn").missing(rig) == ["trait:spinner"]


def test_a_whole_object_clip_drives_anything_at_all():
    """A root track needs no parts, which is what makes bob and spin universal."""
    rig = R.Rig((8, 8), [R.Part("body", "body", (0, 0, 8, 8), None, (4, 8), 0)])
    for name in ("bob", "spin", "tumble", "pulse", "swing"):
        assert props.get(name).drives(rig)


def test_every_preset_names_animations_that_exist():
    for preset, names in props.PRESET_SETS.items():
        for name in names:
            assert name in props.LIBRARY, "%s names %r" % (preset, name)


def test_a_character_animation_can_be_asked_for_by_a_subject_build():
    """The two libraries are one catalogue with two tables in it."""
    assert [a.name for a in props.resolve(["walk"])] == ["walk"]
    assert [a.name for a in motion.resolve(["gust"])] == ["gust"]


def test_an_animation_in_neither_library_names_both_in_the_error():
    with pytest.raises(KeyError) as caught:
        props.resolve(["moonwalk"])
    assert "walk" in str(caught.value) and "sway" in str(caught.value)


# ---------------------------------------------------------------------------
# Passage: rain, a river, a conveyor. The thing stays where it is and something
# travels through it -- a class of subject nothing else here can animate, and
# the only motion in the plugin that cannot detach anything from anything.
# ---------------------------------------------------------------------------

def _sheet(height=32, width=24, seed=11):
    rng = np.random.RandomState(seed)
    art = image.blank(height, width)
    for _ in range(46):
        y, x = rng.randint(0, height), rng.randint(0, width)
        for step in range(3):
            art[(y + step) % height, (x + step // 2) % width] = \
                [150 + 30 * (step > 0), 190, 235, 255]
    return art


def _flow_rig(height, width):
    return R.Rig((width, height), [
        R.Part("sheet", "body", (0, 0, width, height), None,
               (width // 2, height), 0, tags=("flow",))])


def _rendered(clip, art):
    height, width = art.shape[:2]
    rig = _flow_rig(height, width)
    cut = cutout.cut(rig, art)
    margin = render.suggest_margin(rig)
    return rig, render.render_sequence(
        cut, list(clip.applied(rig).poses(rig)), margin=margin), cut, margin


def test_fall_conserves_every_pixel_in_every_frame():
    """A wrap is a bijection, so this is exact rather than a matter of degree.
    It is a stronger claim than `shed` makes and the right one here: nothing
    leaves the part, so nothing can come away from anything."""
    art = _sheet()
    _rig, frames, _cut, _margin = _rendered(props.get("fall"), art)
    base = int(image.alpha_mask(art).sum())
    assert {int(image.alpha_mask(frame).sum()) for frame in frames} == {base}
    assert quality.conserved(frames, art)[0] == 0.0


def test_fall_invents_no_colour():
    art = _sheet()
    _rig, frames, _cut, _margin = _rendered(props.get("fall"), art)
    allowed = {tuple(colour) for colour in image.unique_colors(art)}
    for frame in frames:
        assert {tuple(c) for c in image.unique_colors(frame)} <= allowed


def test_fall_closes_its_loop_byte_for_byte():
    """One whole box per cycle, so the frame after the last IS the first."""
    art = _sheet()
    rig, frames, cut, margin = _rendered(props.get("fall"), art)
    wrapped = render.render_pose(
        cut, props.get("fall").applied(rig).pose_at(rig, 1.0), margin=margin)
    assert wrapped.tobytes() == frames[0].tobytes()


def test_the_scroll_is_a_fraction_of_the_box_so_one_clip_fits_any_size():
    """A clip written in pixels would have to be told the size of a part it has
    never met, and would close its loop on exactly one of them."""
    for height, width in ((16, 12), (32, 24), (96, 70)):
        art = _sheet(height, width)
        rig, frames, cut, margin = _rendered(props.get("fall"), art)
        assert len({frame.tobytes() for frame in frames}) > 1
        wrapped = render.render_pose(
            cut, props.get("fall").applied(rig).pose_at(rig, 1.0), margin=margin)
        assert wrapped.tobytes() == frames[0].tobytes()


def test_fall_and_current_move_along_different_axes():
    art = _sheet()
    _r, down, _c, _m = _rendered(props.get("fall"), art)
    _r, across, _c, _m = _rendered(props.get("current"), art)
    assert [f.tobytes() for f in down] != [f.tobytes() for f in across]


def test_a_subject_with_no_flow_part_is_told_rather_than_given_still_frames():
    rig = R.Rig((16, 16), [R.Part("body", "body", (0, 0, 16, 16), None, (8, 16), 0)])
    assert not props.get("fall").drives(rig)
    assert "flow" in props.get("fall").missing(rig)[0]


def test_scattered_art_is_measured_for_conservation_not_for_shedding():
    """`shed` asks how much came AWAY from the subject, which presumes there is
    one. Every corpus sprite has a largest blob of 96% or more; a sheet of rain
    is fifty separate marks."""
    art = _sheet()
    assert quality.scattered(art)
    solid = image.blank(16, 16)
    solid[2:14, 2:14] = [200, 100, 100, 255]
    assert not quality.scattered(solid)
    assert quality.connected_share(image.alpha_mask(solid)) == 1.0


def test_conservation_catches_what_a_scroll_cannot_do():
    """The check is only worth having if something fails it. A rotation loses
    pixels off the corners of the part; a wrap cannot."""
    art = _sheet()
    rig = _flow_rig(*art.shape[:2])
    cut = cutout.cut(rig, art)
    margin = render.suggest_margin(rig)
    spun = motion.Animation("spun", 4, tracks={
        "body": [{"t": 0.0, "angle": 0.0}, {"t": 0.5, "angle": 40.0}]})
    frames = render.render_sequence(cut, list(spun.poses(rig)), margin=margin)
    assert quality.conserved(frames, art)[0] > 0.0
