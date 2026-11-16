"""Урон босса 30..200 и кот-охотник, которого видно."""

from app.webapp import DUNGEON_PAGE


def test_boss_damage_curve():
    # 30 урона в первой локации, ~200 в десятой
    assert "dmg: Math.round(30 + zi * 18.9)" in DUNGEON_PAGE
    assert 30 <= round(30 + 0 * 18.9) <= 40
    assert 190 <= round(30 + 9 * 18.9) <= 210


def test_phase_multiplier_is_moderate():
    assert "const phaseMul = b.phase >= 3 ? 1.35 : b.phase === 2 ? 1.15 : 1;" in DUNGEON_PAGE


def test_cat_hunts_mobs():
    body = DUNGEON_PAGE[DUNGEON_PAGE.index("function petTick(dt)"):][:1200]
    assert "const hunting = target && bestD < 320;" in body
    assert "const speed = hunting ? 250 : 160;" in body
    assert "if (hunting && dist < 34 && PET.cd <= 0){" in body


def test_cat_is_drawn_with_camera():
    body = DUNGEON_PAGE[DUNGEON_PAGE.index("function petDraw()"):][:300]
    assert "ctx.translate(-cam.x, -cam.y);" in body


def test_cat_uses_sheet_rows():
    assert "const row = PET.atk > 0 ? 1 : 0;" in DUNGEON_PAGE
