"""Рулетка и коллекция: новые элементы страниц и хендлеры."""

import inspect

from app.games_page import ROULETTE_PAGE
from app.webapp import COLLECTION_PAGE, PROFILE_PAGE, api_roulette, api_roulette_spin
from app.webtheme import BOOTSTRAP, POLISH


def test_roulette_has_two_kinds():
    assert 'data-k="classic"' in ROULETTE_PAGE
    assert 'data-k="crystal"' in ROULETTE_PAGE
    assert "Кристальная" in ROULETTE_PAGE


def test_roulette_can_spin_up_to_three():
    assert 'data-n="1"' in ROULETTE_PAGE
    assert 'data-n="2"' in ROULETTE_PAGE
    assert 'data-n="3"' in ROULETTE_PAGE
    assert "count: count" in ROULETTE_PAGE


def test_roulette_has_wheel_and_reel_views():
    assert 'data-v="wheel"' in ROULETTE_PAGE
    assert 'data-v="reel"' in ROULETTE_PAGE
    assert "makeReel(" in ROULETTE_PAGE
    assert "/api/prefs" in ROULETTE_PAGE


def test_roulette_shows_crystals_and_price():
    assert 'id="crystals"' in ROULETTE_PAGE
    assert "PRICE = 25000" in ROULETTE_PAGE
    assert "бесплатный" in ROULETTE_PAGE.lower()


def test_roulette_page_talks_to_telegram():
    """Без telegram-web-app.js initData пустой и все ручки отвечают 401."""
    assert "telegram-web-app.js" in ROULETTE_PAGE
    assert "X-Telegram-Init-Data" in ROULETTE_PAGE


def test_roulette_api_takes_kind_and_count():
    source = inspect.getsource(api_roulette_spin)
    assert 'body.get("kind")' in source
    assert 'body.get("count"' in source
    assert "clamp_count" in source
    assert "claim_crystal_spins" in source
    assert "claim_roulette_many" in source
    state_source = inspect.getsource(api_roulette)
    assert "query_params.get(\"kind\"" in state_source


def test_collection_plays_reveal_and_can_pin():
    assert "function revealCard(" in COLLECTION_PAGE
    assert '"reveal lv"' in COLLECTION_PAGE
    assert "/api/profile/pin" in COLLECTION_PAGE
    assert "pinCard(" in COLLECTION_PAGE
    assert "function decorHtml(" in COLLECTION_PAGE
    assert "fx-l" in COLLECTION_PAGE


def test_collection_fx_follows_settings():
    assert "S.data.fx" in COLLECTION_PAGE
    assert "window.__onPrefs" in COLLECTION_PAGE


def test_profile_shows_pinned_card():
    assert "function pinnedHtml(" in PROFILE_PAGE
    assert "vitrine" in PROFILE_PAGE
    assert "карточка в профиле" in PROFILE_PAGE


def test_settings_modal_has_all_switches():
    assert "gearButton" in BOOTSTRAP
    assert "__sw-fx" in BOOTSTRAP
    assert "view_classic" in BOOTSTRAP and "view_crystal" in BOOTSTRAP
    assert "pinned" in BOOTSTRAP
    # кнопка не лезет на игровые экраны с джойстиком
    assert '"/proto_dungeon"' in BOOTSTRAP
    # стили модалки уехали в общий слой
    assert "#__gear" in POLISH
    assert ".__sheet" in POLISH


def test_settings_are_stored_in_db():
    import app.db as db

    source = inspect.getsource(db.Database.set_prefs)
    assert "player_prefs" in source
    assert "json.dumps" in source


def test_crystals_and_spins_live_in_db():
    import app.db as db

    assert "claim_crystal_spins" in dir(db.Database)
    assert "claim_roulette_many" in dir(db.Database)
    assert "add_crystals" in dir(db.Database)


def test_schema_has_crystals_and_prefs():
    sql = open("schema.sql", encoding="utf-8").read()
    assert "crystals bigint not null default 0" in sql
    assert "create table if not exists player_prefs" in sql
    assert "crystal_day" in sql
