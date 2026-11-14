"""Последние пассивки: Лео, Дик, Мыш."""

import inspect

from app.webapp import DUNGEON_PAGE


def test_leo_and_dik_in_battle():
    from app import db

    source = inspect.getsource(db.Database.apply_battle_result)
    assert "pvp_points" in source
    assert "pvp_case" in source
    assert "pet_dik" in source


def test_mysh_boosts_weapon_drop():
    from app import webapp

    source = inspect.getsource(webapp.api_dungeon_hero)
    assert '"weapon"' in source
    assert "drop_bonus" in source
    assert "MOB_DROP_CHANCE = 0.05 * (1 + Number(hero.drop_bonus))" in DUNGEON_PAGE
