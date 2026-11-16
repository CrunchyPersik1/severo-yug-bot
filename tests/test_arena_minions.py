"""Залп босса вызывает подмогу: по мобу на каждую локацию."""

from app.webapp import DUNGEON_PAGE


def test_minions_spawn_with_volley():
    assert "function arenaSpawnMinions(count)" in DUNGEON_PAGE
    # 1 моб на 1-й локации, 10 на 10-й — считаем от индекса локации
    assert "arenaSpawnMinions(ARENA.zi + 1);" in DUNGEON_PAGE
    body = DUNGEON_PAGE[DUNGEON_PAGE.index("function arenaSpawnMinions"):][:900]
    assert "ARENA.mobs.push" in body


def test_minion_stats_scale_with_zone():
    body = DUNGEON_PAGE[DUNGEON_PAGE.index("function arenaSpawnMinions"):][:900]
    assert "hp: 60 + zi * 45" in body
    assert "sp: 55 + zi * 7" in body
    assert "dmg: Math.round(5 + zi * 2.5)" in body


def test_minions_chase_hit_and_die():
    assert "ARENA.mobs = ARENA.mobs.filter" in DUNGEON_PAGE
    assert "m.cd = 0.9;" in DUNGEON_PAGE
    assert "return m.hp > 0;" in DUNGEON_PAGE


def test_shots_hit_minions_before_boss():
    block = DUNGEON_PAGE[DUNGEON_PAGE.index("ARENA.shots = (ARENA.shots || [])"):][:800]
    assert "ARENA.mobs[i]" in block
    assert block.index("ARENA.mobs[i]") < block.index("b.y - 40")


def test_dash_gives_invulnerability():
    assert "if (h1.dashT > 0) return false;   // додж-ролл даёт неуязвимость" in DUNGEON_PAGE
