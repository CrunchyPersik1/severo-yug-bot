"""Сейф-зона вокруг боссов."""

from app.webapp import DUNGEON_PAGE


def test_safe_zone_exists_and_is_bigger_than_boss():
    assert "const SAFE_R = 210;" in DUNGEON_PAGE
    assert "function inSafeZone(x, y){" in DUNGEON_PAGE
    assert "function nearBoss(x, y, pad){" in DUNGEON_PAGE
    # круг босса (r=60) целиком внутри сейф-зоны
    assert "bosses.push({x: WORLD.w / 2 - 180, y: i * ZONE_H + 300, r: 60" in DUNGEON_PAGE


def test_mobs_cannot_hurt_in_safe_zone():
    assert "const playerSafe = inSafeZone(P.x, P.y);" in DUNGEON_PAGE
    assert "if (!playerSafe && dm < 260){" in DUNGEON_PAGE
    # мобов выталкивает из зоны
    assert "m.x = guard.x + gx / gd * (SAFE_R + 10);" in DUNGEON_PAGE


def test_safe_zone_is_two_way():
    # в зоне не бьют и не бьёшь — иначе фарм без риска
    assert "В сейф-зоне не дерутся" in DUNGEON_PAGE


def test_safe_zone_is_drawn():
    assert 'ctx.fillText("СЕЙФ-ЗОНА"' in DUNGEON_PAGE
    assert "ctx.setLineDash([10, 10]);" in DUNGEON_PAGE
    # бейдж в HUD
    assert 'id="safebadge"' in DUNGEON_PAGE
    assert 'safeBadge.classList.toggle("on", inSafeZone(P.x, P.y));' in DUNGEON_PAGE


def test_boss_wait_still_works_inside():
    # ожидание босса считается по кругу босса, а не по сейф-зоне
    assert "const inside = Math.hypot(bs.x - P.x, bs.y - P.y) < bs.r;" in DUNGEON_PAGE
    assert "bs.t += dt;" in DUNGEON_PAGE
