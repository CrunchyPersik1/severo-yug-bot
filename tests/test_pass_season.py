"""Сезонный скин, титул и бонусы после 50 уровня."""

import pathlib

from app.cards import CARDS_BY_ID
from app.pass_page import PASS_PAGE
from app.pass_repo import SKIN_CARD, PassRepo

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_skin_card_is_stronger_valeriya():
    base = CARDS_BY_ID["valeriya"]
    skin = CARDS_BY_ID[SKIN_CARD]
    assert skin.hp == base.hp + 200
    assert skin.atk == round(base.atk * 1.2)
    assert skin.rarity == "ultra"
    assert "скин" in (skin.description or "").lower()


def test_skin_is_not_in_gacha_pool():
    from app import cards as cards_mod

    assert SKIN_CARD in cards_mod.CARDS_BY_ID
    assert SKIN_CARD not in {card.card_id for card in cards_mod.CARDS}
    assert SKIN_CARD not in {card.card_id for cards in cards_mod.CARDS_BY_RARITY.values() for card in cards}
    assert 'skin_for="valeriya"' in (ROOT / "app" / "cards.py").read_text(encoding="utf-8")


def test_repo_has_season_tools():
    for name in ("claim_bonus", "bonus_state", "ensure_title", "close_old_seasons",
                 "unseen_reports", "_grant_skin"):
        assert hasattr(PassRepo, name), name


def test_page_shows_bonus_and_reports():
    assert 'id="bonusBox"' in PASS_PAGE
    assert "Бонусы после 50 уровня" in PASS_PAGE
    assert "showReports" in PASS_PAGE


def test_profile_has_title_plaque():
    page = (ROOT / "app" / "webapp.py").read_text(encoding="utf-8")
    assert "__ttl" in page
    assert "d.title.title" in page
    assert "__ttlflow" in page


def test_schema_has_titles_and_reports():
    schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
    assert "create table if not exists player_titles" in schema
    assert "create table if not exists pass_reports" in schema
