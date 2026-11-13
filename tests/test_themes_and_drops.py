"""Темы: Трофим, бесплатные, снежные и выдача по нику."""

import inspect

from app import themes


def test_snow_replaced_autumn():
    classic = themes.get("classic")
    assert classic.name == "Зима"
    assert classic.particles == "snow"
    assert classic.price == 0


def test_two_snow_variants():
    dark = themes.get("classic")
    light = themes.get("snowlight")
    assert dark.particles == light.particles == "snow"
    assert light.light is True
    assert dark.light is False
    assert light.bg != dark.bg


def test_free_themes_for_everyone():
    free = [theme.id for theme in themes.THEMES if themes.is_free(theme)]
    assert "classic" in free
    assert "snowlight" in free
    assert "mint" in free
    assert "clay" in free


def test_trofim_theme_is_black_and_white_and_personal():
    trofim = themes.get("trofim")
    assert trofim.name == "Чёрно-белая"
    assert trofim.personal is True
    assert themes.granted_only(trofim) is True
    assert themes.is_free(trofim) is False
    # строго чёрное и белое, без оттенков
    assert trofim.bg == "#000000"
    assert trofim.ink == "#ffffff"
    assert trofim.acc == "#ffffff"


def test_trofim_is_not_for_sale():
    ids = {theme.id for theme in themes.shop_entries()}
    assert "trofim" not in ids
    assert "classic" not in ids


def test_admin_can_grant_theme_by_username():
    from app import admin_actions

    source = inspect.getsource(admin_actions.act_theme)
    assert "player_themes" in source
    assert "_resolve_player" in source
    assert "theme" in admin_actions.COMMANDS
    assert "trofim" in admin_actions.HELP


def test_theme_payload_marks_personal_and_light():
    from app.webapp import _theme_payload

    data = _theme_payload(0, "", [])
    by_id = {item["id"]: item for item in data["all"]}
    assert by_id["trofim"]["owned"] is False
    assert by_id["trofim"]["personal"] is True
    assert by_id["mint"]["owned"] is True
    assert by_id["snowlight"]["light"] is True


def test_theme_setter_blocks_personal():
    from app.webapp import api_theme_set

    source = inspect.getsource(api_theme_set)
    assert "granted_only" in source
    assert "личный" in source


def test_snow_polish_present():
    from app.webtheme import BOOTSTRAP, POLISH

    assert "snowFront" in BOOTSTRAP
    assert "theme-snow" in BOOTSTRAP
    assert "__snowfront" in POLISH
    assert "body.theme-snow button::before" in POLISH


def test_reveal_overlay_is_shared():
    from app.webtheme import BOOTSTRAP, POLISH

    assert "window.__revealCards" in BOOTSTRAP
    assert "window.__revealOne" in BOOTSTRAP
    assert "rv-card" in POLISH
    assert "rv-spark" in POLISH


def test_reveal_wired_into_pages():
    from app.games_page import CASE_PAGE, ROULETTE_PAGE
    from app.webapp import DROP_PAGE

    assert "__revealCards" in CASE_PAGE
    assert "revealFrom" in ROULETTE_PAGE
    assert "__revealCards" in DROP_PAGE


def test_card_packs_in_shop():
    from app.webapp import PAGE

    assert "/api/shop/pack_cards/buy" in PAGE
    assert "/api/shop/pack_cards/open" in PAGE
    assert "Паки карточек" in PAGE
    assert "__revealCards" in PAGE


def test_drop_page_served():
    from app.webapp import DROP_PAGE
    from app import webapp

    assert "telegram-web-app.js" in DROP_PAGE
    assert "/api/drop" in DROP_PAGE
    assert 'path": "/drop"' in open("app/webapp.py", encoding="utf-8").read()


def test_drop_api_mechanics():
    from app import webapp

    source = inspect.getsource(webapp.api_drop)
    assert "claim_daily" in source
    assert "roll_card_d" in source
    assert "_card_reveal" in source
