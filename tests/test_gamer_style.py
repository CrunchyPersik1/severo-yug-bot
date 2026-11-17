"""Геймерский стиль: тема, эффекты, режим и выдача за Пасс++."""

import pathlib

from app import admin_actions, pass_repo, themes
from app.cards import SKINS, card_rows
from app.webtheme import BOOTSTRAP, POLISH

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_theme_is_personal_and_free():
    theme = themes.get("gamer")
    assert theme.id == "gamer"
    assert theme.personal is True
    assert theme.price == 0
    assert theme.bg.lower() == "#08090a"
    assert theme.acc.lower() == "#ffd400"
    assert themes.granted_only(theme) is True


def test_gamer_css_is_present():
    assert "theme-gamer" in POLISH
    assert "gm-marquee" in POLISH
    assert "gm-glitch" in POLISH
    assert "gm-lite" in POLISH


def test_effects_script_and_modes():
    assert "function gamerOn(" in BOOTSTRAP
    assert "function gmBeep(" in BOOTSTRAP
    assert "gm-lite" in BOOTSTRAP
    assert 'fx_mode === "lite"' in BOOTSTRAP


def test_premium_purchase_grants_style():
    assert hasattr(pass_repo.PassRepo, "_grant_gamer")
    src = pathlib.Path(pass_repo.__file__).read_text(encoding="utf-8")
    assert "_grant_gamer(user_id)" in src
    assert "'gamer'" in src


def test_skin_card_is_synced_to_db():
    rows = card_rows()
    ids = {row[0] for row in rows}
    for skin in SKINS:
        assert skin.card_id in ids
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    # purge не должен удалять скины сразу после upsert
    assert "+ [card.card_id for card in SKINS]" in main
