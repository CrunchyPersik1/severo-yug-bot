"""Опыт в подземелье: 10-15 мобов на уровень, а не 50+."""

import re

from app.webapp import DUNGEON_PAGE


def _fn(name: str) -> str:
    m = re.search(r"function " + name + r"\([^)]*\)\{(.*?)\n\}", DUNGEON_PAGE, re.S)
    assert m, name
    return m.group(1)


def test_exp_need_is_zone_based():
    body = _fn("expNeed")
    assert "zoneMobHp" in body
    assert "ownZone" in body
    # старая формула роста по номеру уровня давала десятки мобов
    assert "Math.pow" not in body


def test_lvl46_needs_about_13_mobs():
    # цифры совпадают с формулой страницы: порог = HP мобов * 2.2, моб даёт HP/6
    zone_hp = [250, 500, 1000, 1350, 2000, 2500, 3000, 3500, 4500, 10000]

    def need(lvl):
        return round(zone_hp[min(9, (lvl - 1) // 25)] * 2.2)

    def per_mob(lvl):
        return max(8, round(zone_hp[min(9, (lvl - 1) // 25)] / 6))

    for lvl in (1, 10, 46, 60, 100, 250):
        mobs = need(lvl) / per_mob(lvl)
        assert 10 <= mobs <= 15, (lvl, mobs)


def test_xp_hint_matches_kill_reward():
    assert "zoneMobHp(zi) / 6 * mult" in DUNGEON_PAGE
