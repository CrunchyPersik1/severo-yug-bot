"""Босс: движение каждый кадр, вход 5 c, предупреждение, урон."""

from app.webapp import DUNGEON_PAGE


def test_wait_is_five_seconds():
    assert "const BOSS_WAIT = 5;" in DUNGEON_PAGE


def test_boss_moves_every_frame():
    # движение вынесено из ветки idle/walk и работает во всех состояниях,
    # кроме собственного рывка
    assert "if (!(b.chargeT > 0)){" in DUNGEON_PAGE
    assert "b.x += mvx * b.sp * dt;" in DUNGEON_PAGE


def test_underlevel_asks_instead_of_denying():
    assert "function levelWarn(bs, req)" in DUNGEON_PAGE
    assert 'id="lvlyes"' in DUNGEON_PAGE and 'id="lvlno"' in DUNGEON_PAGE
    assert "bs.forced = true;" in DUNGEON_PAGE
    # старый запрет «нужен уровень» больше не просто тостит и выкидывает
    assert 'toast("Босс: нужен ур. " + req)' not in DUNGEON_PAGE


def test_boss_damage_is_meaningful():
    assert "dmg: Math.round(14 + zi * 4)" in DUNGEON_PAGE
    assert "const phaseMul = b.phase >= 3 ? 1.7 : b.phase === 2 ? 1.35 : 1;" in DUNGEON_PAGE
    assert "h1.hp -= Math.round(b.dmg * 1.2);" in DUNGEON_PAGE


def test_refusal_does_not_reopen_instantly():
    handler = DUNGEON_PAGE.index("no.onclick")
    body = DUNGEON_PAGE[handler:handler + 200]
    assert "bs.warned = true;" in body
    assert "bs.warned = false;      // вышел из круга" in DUNGEON_PAGE
