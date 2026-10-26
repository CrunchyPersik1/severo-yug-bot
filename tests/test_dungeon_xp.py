"""Полоса опыта и настройка прокачки уровней."""

from app.webapp import DUNGEON_PAGE


def test_xp_bar_in_hud():
    assert 'id="xpfill"' in DUNGEON_PAGE
    assert 'id="xptxt"' in DUNGEON_PAGE
    assert "function xpPaint(" in DUNGEON_PAGE
    # обновляется вместе с остальным HUD и после начисления опыта
    assert "xpPaint();" in DUNGEON_PAGE
    # подсказка, сколько ещё мобов
    assert "мобов" in DUNGEON_PAGE


def test_one_hp_formula():
    assert "function heroMax(" in DUNGEON_PAGE
    assert "P.max = heroMax(level);" in DUNGEON_PAGE
    assert "P.max = heroMax(stats.lvl);" in DUNGEON_PAGE
    assert "P.max = 120 + (level - 1) * 8" not in DUNGEON_PAGE


def test_leveling_is_reachable():
    # гейт 1 + зона * 10 (1, 11, 21, 31, ...), как попросил владелец
    assert "function zoneReq(y){ return 1 + zoneIndex(y) * 10; }" in DUNGEON_PAGE
    # старый гейт 25 уровней за локацию — та самая причина «опыт не капал»
    assert "zoneIndex(y) * 25" not in DUNGEON_PAGE
    # кривая: 40 * lvl^1.5, опыт с моба max/6 — на уровень ~30 мобов
    assert "Math.round(40 * Math.pow(Math.max(1, lvl), 1.5))" in DUNGEON_PAGE
    assert "Math.max(8, Math.round(m.max / 6))" in DUNGEON_PAGE


def test_weak_kills_still_give_xp():
    assert "gainExp(Math.round(baseXp * 0.5))" in DUNGEON_PAGE
    assert "опыта нет" not in DUNGEON_PAGE


def test_stored_exp_levels_up_on_load():
    # если в базе накопился опыт сверх нового порога — уровень догоняется
    assert "while (stats.exp >= expNeed(stats.lvl) && stats.lvl < 999)" in DUNGEON_PAGE


def test_mobs_per_level_is_sane():
    """Считаем по формулам страницы: до уровня уходит 3..70 мобов.

    В начале игры прокачка быстрая (2-3 уровня с пары мобов — так и надо),
    а с 12-го уровня уже 25..70 мобов, чтобы не было «слишком легко».
    """
    caps = (250, 500, 1_000, 1_350, 2_000, 2_500, 3_000, 3_500, 4_500, 10_000)

    def need(lvl: int) -> int:
        return round(40 * lvl ** 1.5)

    def gate(zone: int) -> int:
        return 1 + zone * 10

    for level in range(2, 90, 3):
        zone = min(9, max(0, (level - 1) // 10))
        per_mob = max(8, round(caps[zone] * 0.78 / 6))
        if level < gate(zone):
            per_mob = max(1, round(per_mob * 0.5))
        mobs = -(-need(level) // per_mob)
        assert 3 <= mobs <= 70, (level, zone + 1, mobs)
        if level >= 12:
            assert 20 <= mobs <= 70, (level, zone + 1, mobs)
