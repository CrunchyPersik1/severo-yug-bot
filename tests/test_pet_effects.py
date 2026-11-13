"""Пассивки петов: что подключено к системам игры."""

import inspect

from app import petfx, pets


def test_equipped_effect_reads_from_db():
    class DB:
        async def equipped_pet(self, uid):
            return {"pet_id": "rokki", "level": 3}

    got = __import__("asyncio").run(petfx.multi(DB(), 1))
    assert got == {"gems": pets.get("rokki").effect(3)}


def test_no_pet_no_effects():
    class DB:
        async def equipped_pet(self, uid):
            return None

    assert __import__("asyncio").run(petfx.multi(DB(), 1)) == {}


def test_scale_and_bonus_points():
    assert petfx.scale(100, 0.25) == 125
    bundle = {"points": 1000, "yugi": 500, "cases_g": 2}
    boosted = petfx.bonus_points(bundle, 0.25)
    assert boosted["points"] == 1250
    assert boosted["yugi"] == 625
    assert boosted["cases_g"] == 2


def test_kasper_saves_card_in_upgrader():
    from app import webapp

    source = inspect.getsource(webapp.api_upgrader_spin)
    assert "upgrade_save" in source
    assert "add_card" in source
    assert '"saved": saved' in source


def test_rocca_boosts_gems():
    from app import webapp

    assert "gem_bonus" in inspect.getsource(webapp.api_mob_kill)


def test_najda_gives_second_card():
    from app import webapp

    assert "double_drop" in inspect.getsource(webapp.api_drop)


def test_kotos_boosts_drop():
    from app import webapp

    source = inspect.getsource(webapp.api_drop)
    assert "chance_all" in source
    assert "roll_gacha_card(boost=boost)" in source


def test_simona_and_mishlen_in_cases():
    from app import webapp

    for fn in (webapp.api_case_open, webapp.api_case_open_many):
        source = inspect.getsource(fn)
        assert "ultra_luck" in source
        assert "case_points" in source


def test_chelsi_boosts_quest_rewards():
    from app import webapp

    assert "quest_reward" in inspect.getsource(webapp.api_mega_claim)


def test_lucy_and_yaichko_in_eggs():
    from app import webapp

    source = inspect.getsource(webapp.api_pets_put)
    assert "lucy" in source
    hatch = inspect.getsource(webapp.api_pets_hatch)
    assert "yaichko" in hatch
