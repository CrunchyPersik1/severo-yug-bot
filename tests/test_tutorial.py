"""Обучение: команда в боте и подсветка в приложении."""

from app import tutorial
from app.handlers import cmd_tutorial
from app.webapp import HUB_PAGE
from app.webtheme import BOOTSTRAP, POLISH


def test_steps_are_short_and_have_targets():
    steps = tutorial.payload()
    assert len(steps) >= 5
    for step in steps:
        assert step["title"] and step["text"]
        assert step["selector"], step
        assert len(step["text"]) < 220


def test_command_exists():
    assert cmd_tutorial is not None


def test_tutorial_overlay_lives_in_shared_layer():
    from app.webtheme import BOOTSTRAP

    assert "function tutStart()" in BOOTSTRAP
    assert "window.__startTutorial = tutStart" in BOOTSTRAP
    assert 'location.search.indexOf("tutorial=1")' in BOOTSTRAP


def test_settings_have_tutorial_button():
    assert 'id="__tut-run"' in BOOTSTRAP
    assert "window.__startTutorial" in BOOTSTRAP
    assert '"/hub?tutorial=1"' in BOOTSTRAP
    assert ".__tut{" in POLISH
