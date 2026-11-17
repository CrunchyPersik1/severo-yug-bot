"""Северо-Пасс: репозиторий и страница на месте."""

import pathlib

from app import pass_config, pass_rewards
from app.pass_page import PASS_PAGE
from app.pass_repo import PassRepo

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_repo_methods_exist():
    for name in ("progress", "add_xp", "quests", "claim_quest", "buy", "claim_level"):
        assert hasattr(PassRepo, name), name


def test_purchase_prices_match_spec():
    assert pass_config.PRICE_PLUS_GEMS == 179
    assert pass_config.PRICE_PREMIUM_GEMS == 240
    assert pass_config.PRICE_UPGRADE_GEMS == 60
    assert pass_config.PRICE_PLUS_RUB == 39
    assert pass_config.PRICE_PREMIUM_RUB == 59
    assert pass_config.PRICE_UPGRADE_RUB == 19


def test_premium_boost_is_fifth_of_season():
    assert int(pass_config.TOTAL_XP * pass_config.PREMIUM_BOOST) == 8800


def test_page_has_tracks_and_quests():
    assert 'id="tracks"' in PASS_PAGE
    assert 'id="quests"' in PASS_PAGE
    assert 'id="buys"' in PASS_PAGE
    assert "Северо-Пасс+" in PASS_PAGE


def test_page_calls_pass_api():
    for path in ("/api/pass", "/api/pass/quest", "/api/pass/claim", "/api/pass/buy"):
        assert path in PASS_PAGE, path


def test_route_and_hub_tile():
    webapp = (ROOT / "app" / "webapp.py").read_text(encoding="utf-8")
    assert '@router.get("/pass", response_class=HTMLResponse)' in webapp
    assert '"id": "pass"' in webapp
    assert '"id": "quests"' not in webapp


def test_rewards_three_tracks_by_level():
    row = pass_rewards.level("2026-11", 5)
    assert row["free"] and row["plus"]
    assert row["premium"] is not None
    row = pass_rewards.level("2026-11", 25)
    assert row["premium"] is None
