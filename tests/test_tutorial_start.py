"""Обучение предлагается при старте и доступно из меню."""

from app.render import render_main_menu
from app.webapp import HUB_PAGE


def test_menu_has_tutorial_button():
    text, keyboard = render_main_menu("bot", "https://example.com")
    buttons = str(keyboard)
    assert "Обучение" in buttons
    assert "/hub?tutorial=1" in buttons


def test_start_mentions_tutorial():
    import inspect

    from app import handlers

    source = inspect.getsource(handlers.cmd_start_menu)
    assert "tut:start" in source
    assert "/tutorial" in source


def test_tutorial_callback_exists():
    from app import handlers

    assert hasattr(handlers, "cb_tutorial")
    assert hasattr(handlers, "_tutorial_sequence")


def test_hub_overlay_remeasures():
    assert "function tutMeasure()" in HUB_PAGE
    assert 'window.addEventListener("scroll"' in HUB_PAGE
    assert "tutScheduleMeasure" in HUB_PAGE
    # восемь шагов с объяснением игры
    assert "1/8" in HUB_PAGE and "8/8" in HUB_PAGE
