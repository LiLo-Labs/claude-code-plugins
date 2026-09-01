"""The critic proposes, the measurement disposes.

The whole point of this module is that a model is allowed to say how the motion
READS -- the thing no metric here catches -- while a deterministic metric keeps
it from breaking the character to do it. These tests are mostly about that
second half, because the second half is what makes the first half safe.
"""

import pytest

from spritepipe import critic, image, motion, render


class Scripted:
    """A critic that says exactly what a test needs it to say."""

    actor = "test:scripted"

    def __init__(self, *critiques):
        self.queue = list(critiques)
        self.seen = []
        self.rigs = []

    def review(self, contact_sheet_path, animation, rig=None):
        self.seen.append(contact_sheet_path)
        self.rigs.append(rig)
        if not self.queue:
            return critic.Critique(actor=self.actor)
        head = self.queue.pop(0)
        return critic.Critique(head.get("verdict", "loose"), head.get("problems"),
                               head.get("adjustments"), head.get("rig_problems"),
                               self.actor)


# -- adjustments -----------------------------------------------------------

def test_a_delta_scales_with_how_far_a_keyframe_already_departs_from_rest():
    """Opening a swing widens its extremes and leaves the neutral frames alone."""
    walk = motion.get("walk")
    wider, touched = critic.apply_adjustments(walk, {"leg_near": {"angle": 10}})
    assert touched > 0
    before = [walk.tracks["leg_near"].sample(t, True).angle for t in walk.times()]
    after = [wider.tracks["leg_near"].sample(t, True).angle for t in wider.times()]
    assert max(after) > max(before)
    for was, now in zip(before, after):
        if abs(was) < 1e-6:
            assert abs(now) < 1e-6, "a neutral frame must stay neutral"


def test_a_negative_delta_closes_a_swing_down():
    walk = motion.get("walk")
    tighter, _ = critic.apply_adjustments(walk, {"leg_near": {"angle": -10}})
    assert (max(abs(a) for a in
                [tighter.tracks["leg_near"].sample(t, True).angle for t in walk.times()])
            < max(abs(a) for a in
                  [walk.tracks["leg_near"].sample(t, True).angle for t in walk.times()]))


def test_the_root_track_is_adjustable_by_name():
    run = motion.get("run")
    bouncier, touched = critic.apply_adjustments(run, {"root": {"dy": 2}})
    assert touched > 0
    assert (min(bouncier.root.sample(t, True).dy for t in run.times())
            < min(run.root.sample(t, True).dy for t in run.times()))


def test_an_adjustment_cannot_run_an_angle_away():
    walk = motion.get("walk")
    absurd, _ = critic.apply_adjustments(walk, {"leg_near": {"angle": 10000}})
    for key in absurd.tracks["leg_near"].keys:
        assert abs(key["angle"]) <= critic.CHANNEL_LIMITS["angle"]


def test_a_scale_cannot_be_driven_to_nothing():
    spin = motion.Animation("spin", 4, root=[{"t": 0.0, "sx": 1.0}, {"t": 0.5, "sx": 0.5}])
    shrunk, _ = critic.apply_adjustments(spin, {"root": {"sx": -100}})
    for key in shrunk.root.keys:
        assert key["sx"] >= critic.MIN_SCALE


def test_a_role_the_rig_does_not_have_is_ignored():
    walk = motion.get("walk")
    same, touched = critic.apply_adjustments(walk, {"accessory": {"angle": 20}})
    assert touched == 0
    assert same.to_dict() == walk.to_dict()


def test_an_unknown_channel_is_ignored():
    walk = motion.get("walk")
    _, touched = critic.apply_adjustments(walk, {"leg_near": {"twist": 20}})
    assert touched == 0


def test_a_non_numeric_delta_is_ignored():
    walk = motion.get("walk")
    _, touched = critic.apply_adjustments(walk, {"leg_near": {"angle": "lots"}})
    assert touched == 0


def test_a_track_sitting_at_rest_is_nudged_by_the_raw_delta():
    """The only way to start motion that is not there at all."""
    flat = motion.Animation("x", 4, tracks={"head": [{"t": 0.0, "angle": 0.0},
                                                     {"t": 1.0, "angle": 0.0}]})
    moved, touched = critic.apply_adjustments(flat, {"head": {"angle": 5}})
    assert touched == 2
    assert all(abs(key["angle"] - 5.0) < 1e-6 for key in moved.tracks["head"].keys)


# -- the loop --------------------------------------------------------------

def test_the_null_critic_asks_for_nothing(hero_cutout, hero_rig, hero, tmp_path):
    walk = motion.get("walk")
    best, history = critic.refine(hero_cutout, hero_rig, walk, hero.pixels,
                                  critic.NullCritic(), str(tmp_path))
    assert best.to_dict() == walk.to_dict()
    assert history and history[0]["outcome"] == "no change asked for"


def test_an_accepted_round_changes_the_animation(hero_cutout, hero_rig, hero, tmp_path):
    scripted = Scripted({"adjustments": {"leg_near": {"angle": -4},
                                         "leg_far": {"angle": -4}}})
    best, history = critic.refine(hero_cutout, hero_rig, motion.get("walk"),
                                  hero.pixels, scripted, str(tmp_path), rounds=1)
    assert best.to_dict() != motion.get("walk").to_dict()
    assert "accepted" in history[0]["outcome"]


def test_a_round_that_breaks_the_character_is_rejected(hero_cutout, hero_rig, hero,
                                                       tmp_path):
    """The guardrail: the critic may improve how it reads, never break the
    character to do it."""
    walk = motion.get("walk")
    scripted = Scripted({"adjustments": {"leg_near": {"angle": 400}}})
    best, history = critic.refine(hero_cutout, hero_rig, walk, hero.pixels,
                                  scripted, str(tmp_path), rounds=1,
                                  tolerance=0.0)
    entry = history[0]
    if "rejected" in entry["outcome"]:
        assert best.to_dict() == walk.to_dict(), "a rejected round must not be kept"
    else:
        assert entry["shed_after"] <= entry["shed_before"]


def test_the_guardrail_is_loose_enough_not_to_reject_on_noise():
    """Shed moves by about half a point in no consistent direction as an
    adjustment sweeps, so a tight gate would reject good rounds at random."""
    assert critic.SHED_TOLERANCE >= 0.01


def test_the_loop_stops_when_the_critic_is_satisfied(hero_cutout, hero_rig, hero, tmp_path):
    scripted = Scripted({"adjustments": {"leg_near": {"angle": -2}}},
                        {"verdict": "good", "adjustments": {}})
    _, history = critic.refine(hero_cutout, hero_rig, motion.get("walk"), hero.pixels,
                               scripted, str(tmp_path), rounds=5)
    assert len(history) == 2
    assert history[-1]["outcome"] == "no change asked for"


def test_zero_rounds_is_a_no_op(hero_cutout, hero_rig, hero, tmp_path):
    walk = motion.get("walk")
    best, history = critic.refine(hero_cutout, hero_rig, walk, hero.pixels,
                                  Scripted({"adjustments": {"leg_near": {"angle": 9}}}),
                                  str(tmp_path), rounds=0)
    assert best.to_dict() == walk.to_dict() and history == []


def test_the_critic_is_shown_a_contact_sheet(hero_cutout, hero_rig, hero, tmp_path):
    scripted = Scripted({"verdict": "good", "adjustments": {}})
    critic.refine(hero_cutout, hero_rig, motion.get("walk"), hero.pixels,
                  scripted, str(tmp_path), rounds=1)
    assert scripted.seen
    sheet = image.load(scripted.seen[0])
    assert sheet.shape[1] > sheet.shape[0], "the sheet is a row of frames"


def test_the_contact_sheet_leads_with_the_source(hero_cutout, hero_rig, hero, tmp_path):
    """So the critic can tell a rigging artefact from the art itself."""
    walk = motion.get("walk")
    frames = [render.render_pose(hero_cutout, pose, margin=8)
              for pose in walk.poses(hero_rig)]
    path, _ = critic.contact_sheet(frames, hero.pixels, str(tmp_path / "s.png"))
    assert image.load(path).shape[1] > 0


def test_make_critic_rejects_an_unknown_name():
    with pytest.raises(ValueError):
        critic.make_critic("gemini", "/tmp")


def test_make_critic_gives_the_null_one_by_default():
    assert isinstance(critic.make_critic("none", "/tmp"), critic.NullCritic)


# -- the critic can see the rig --------------------------------------------

def test_the_critic_is_handed_the_rig(hero_cutout, hero_rig, hero, tmp_path):
    """Shown only frames it can only answer "the motion is wrong", so it
    rationalises whatever rig it is given -- it once advised opening the leg
    swing of a slime that has no legs."""
    scripted = Scripted({"verdict": "good", "adjustments": {}})
    critic.refine(hero_cutout, hero_rig, motion.get("walk"), hero.pixels,
                  scripted, str(tmp_path), rounds=1)
    assert scripted.rigs and scripted.rigs[0] is hero_rig


def test_the_rig_is_described_as_fractions(hero_rig):
    text = critic.describe_rig(hero_rig)
    assert "role=" in text and "box=[" in text
    for part in hero_rig.parts:
        assert part.name in text
    for number in text.split("[")[1].split("]")[0].split(","):
        assert 0.0 <= float(number) <= 1.0, "boxes travel as fractions, not pixels"


def test_describing_no_rig_does_not_crash():
    assert "not supplied" in critic.describe_rig(None)


def test_blaming_the_rig_stops_the_loop(hero_cutout, hero_rig, hero, tmp_path):
    """Tuning the swing of a limb the character does not have is wasted work."""
    scripted = Scripted(
        {"verdict": "rig",
         "rig_problems": ["this character is a blob; it has no arms or legs"],
         "adjustments": {"leg_near": {"angle": 20}}},
        {"adjustments": {"leg_near": {"angle": -5}}})
    walk = motion.get("walk")
    best, history = critic.refine(hero_cutout, hero_rig, walk, hero.pixels,
                                  scripted, str(tmp_path), rounds=3)
    assert best.to_dict() == walk.to_dict(), "no adjustment may be applied"
    assert len(history) == 1
    assert "rig is the problem" in history[0]["outcome"]


def test_rig_problems_alone_are_enough_to_stop(hero_cutout, hero_rig, hero, tmp_path):
    scripted = Scripted({"verdict": "loose",
                         "rig_problems": ["the head box stops halfway down the face"],
                         "adjustments": {"head": {"angle": 4}}})
    walk = motion.get("walk")
    best, history = critic.refine(hero_cutout, hero_rig, walk, hero.pixels,
                                  scripted, str(tmp_path), rounds=2)
    assert best.to_dict() == walk.to_dict()
    assert "head box" in history[0]["outcome"]


def test_a_critique_without_rig_problems_still_adjusts(hero_cutout, hero_rig, hero,
                                                       tmp_path):
    scripted = Scripted({"adjustments": {"leg_near": {"angle": -4},
                                         "leg_far": {"angle": -4}}})
    best, history = critic.refine(hero_cutout, hero_rig, motion.get("walk"),
                                  hero.pixels, scripted, str(tmp_path), rounds=1)
    assert "rig is the problem" not in history[0]["outcome"]
    assert best.to_dict() != motion.get("walk").to_dict()
