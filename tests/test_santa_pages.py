"""Страницы и ручки петов и ивента Санты."""

import inspect

from app import eggs, pets, santa


def test_santa_page_has_map_story_and_fight():
    from app.webapp import SANTA_PAGE

    assert 'id="map"' in SANTA_PAGE          # роадмап
    assert "data-ch=" in SANTA_PAGE          # 4 варианта сюжета
    assert 'id="cv"' in SANTA_PAGE           # канвас боя
    assert "startFight(" in SANTA_PAGE
    assert "/api/santa/story" in SANTA_PAGE
    assert "/api/santa/level" in SANTA_PAGE
    assert "/api/santa/buy" in SANTA_PAGE
    assert "telegram-web-app.js" in SANTA_PAGE


def test_pets_page_has_incubator_and_upgrades():
    from app.webapp import PETS_PAGE

    assert "/api/pets" in PETS_PAGE
    assert "incubator/put" in PETS_PAGE
    assert "incubator/hatch" in PETS_PAGE
    assert "data-up=" in PETS_PAGE
    assert "__revealCards" in PETS_PAGE


def test_santa_api_exists():
    from app import webapp

    assert "story_done" in inspect.getsource(webapp._santa_state)
    assert "santa_clear_level" in inspect.getsource(webapp.api_santa_level)
    assert "santa_buy" in inspect.getsource(webapp.api_santa_buy)
    assert "shop_open" in inspect.getsource(webapp.api_santa_buy)


def test_pets_api_gives_nine_slots():
    from app import webapp

    source = inspect.getsource(webapp._pets_state)
    assert "eggs_mod.slots()" in source
    assert "incubator_upgrades" in source


def test_level_rewards_match_the_deal():
    last = santa.levels()[-1]["reward"]
    assert last["eggs"] == 5 and last["gems"] == 50
    for item in santa.levels():
        assert "kotos" not in str(item["reward"])


def test_premium_fx_is_loud():
    from app import cardsfx

    data = cardsfx.payload("premium")
    assert data["level"] == 5
    assert data["color"] == "#ffd166"
    assert "crown" in data["decor"]


def test_vip_snow_theme():
    from app import themes

    vip = themes.get("snowvip")
    assert vip.vip is True
    assert themes.vip_only(vip) is True
    assert themes.is_free(vip) is False
    assert vip.particles == "snow"


def test_vip_theme_not_in_shop():
    from app import themes

    assert "snowvip" not in {t.id for t in themes.shop_entries()}


def test_dungeon_draws_mani():
    from app.webapp import DUNGEON_PAGE

    assert "function petTick(" in DUNGEON_PAGE
    assert 'PET.id !== "mani"' in DUNGEON_PAGE
    assert "petLoad();" in DUNGEON_PAGE
    assert "petDraw()" in DUNGEON_PAGE


def test_hub_has_new_tiles():
    from app import webapp

    paths = [section.get("path") for section in webapp.HUB_SECTIONS]
    assert "/santa" in paths
    assert "/pets" in paths


def test_schema_has_all_new_tables():
    sql = open("schema.sql", encoding="utf-8").read()
    for table in ("pets_owned", "incubator", "incubator_upgrades", "eggs_owned",
                  "santa_progress", "santa_levels", "santa_bought"):
        assert f"create table if not exists {table}" in sql, table


def test_egg_inventory_methods():
    import app.db as db

    for name in ("add_eggs", "egg_count", "take_egg", "incubator_put", "santa_buy"):
        assert hasattr(db.Database, name), name
