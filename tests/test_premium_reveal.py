"""Премиум-анимация карты и миниатюры плиток хаба."""

import inspect


def test_premium_reveal_has_flyin_flash_and_jets():
    from app.webtheme import BOOTSTRAP, POLISH

    for token in ("rv-burst", "rv-jet", "rv-conf", "rvshine", "rvshimmer", "__rvfly"):
        assert token in POLISH, token
    source = BOOTSTRAP
    assert 'ov.className = "rv ultra"' in source
    assert "rv-jet left" in source and "rv-jet right" in source
    assert "rv-conf" in source


def test_premium_card_held_longer():
    from app.webtheme import BOOTSTRAP

    assert "lvl >= 4 ? 4200" in BOOTSTRAP


def test_hub_thumb_lookup():
    from app.webapp import HUB_ART_DIR, _hub_thumb

    assert HUB_ART_DIR.name == "hub"
    # пока картинок нет — арта нет, плитка рисуется как раньше
    assert _hub_thumb("yugi") is None
    assert _hub_thumb("nope") is None


def test_hub_page_renders_art():
    from app.webapp import HUB_PAGE

    assert 'class="tart"' in HUB_PAGE
    assert "sec.thumb" in HUB_PAGE
    assert ".tile.withart" in HUB_PAGE


def test_hub_payload_sends_thumb():
    from app import webapp

    source = inspect.getsource(webapp.api_hub)
    assert "_hub_thumb" in source
