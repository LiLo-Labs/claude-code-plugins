import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import make_fixture  # noqa: E402

from spritepipe import cutout, ingest, vision  # noqa: E402


@pytest.fixture
def hero_path(tmp_path):
    """The default character: arms clear of the body, legs parted, on white at 1x."""
    path = str(tmp_path / "hero.png")
    make_fixture.write(path, make_fixture.on_background(make_fixture.humanoid()))
    return path


@pytest.fixture
def beast_path(tmp_path):
    path = str(tmp_path / "beast.png")
    make_fixture.write(path, make_fixture.on_background(make_fixture.creature()))
    return path


@pytest.fixture
def gem_path(tmp_path):
    path = str(tmp_path / "gem.png")
    make_fixture.write(path, make_fixture.on_background(make_fixture.prop()))
    return path


@pytest.fixture
def hero(hero_path):
    return ingest.ingest(hero_path)


@pytest.fixture
def hero_rig(hero):
    return vision.TemplateBackend().rig(hero)


@pytest.fixture
def hero_cutout(hero, hero_rig):
    return cutout.cut(hero_rig, hero.pixels)
