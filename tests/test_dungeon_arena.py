"""Арена боссов в подземелье."""

from app.webapp import DUNGEON_PAGE


def test_arena_markup():
    for marker in ('id="arena"', 'id="acv"', 'id="ajoy"', 'id="aattack"',
                   'id="adash"', 'id="abHp"', 'id="apHp"', 'id="aexit"'):
        assert marker in DUNGEON_PAGE, marker


def test_arena_moves_like_a_game():
    # джойстик даёт скорость, рывок — импульс, удар бьёт в радиусе,
    # укрытия блокируют движение
    assert "ARENA.joy.dx * 210" in DUNGEON_PAGE
    assert "h.dvx = ARENA.joy.dx / l * 620" in DUNGEON_PAGE
    assert "Math.hypot(b.x - h.x, b.y - h.y) < 100" in DUNGEON_PAGE
    assert "function arenaBlocked(" in DUNGEON_PAGE
    assert "ARENA.cover = [" in DUNGEON_PAGE


def test_arena_has_hit_feedback():
    assert "ARENA.flash = 0.16" in DUNGEON_PAGE
    assert "ARENA.shake = 0.3" in DUNGEON_PAGE
    assert "Math.floor(ARENA.t * 10) % 4" in DUNGEON_PAGE


def test_arena_boss_patterns():
    assert 'b.state = "windup"' in DUNGEON_PAGE
    assert 'b.state = "volley"' in DUNGEON_PAGE
    assert "ARENA.arrows.push" in DUNGEON_PAGE


def test_arena_rewards_and_cooldown():
    assert "P.coins = (P.coins || 0) + coins" in DUNGEON_PAGE
    assert "400 + zi * 300" in DUNGEON_PAGE
    assert "ARENA.cd[zi] = Date.now() + 5000" in DUNGEON_PAGE


def test_arena_uses_boss_sprites():
    for sprite in ("anomaly.png", "knight.png", "thief.png"):
        assert sprite in DUNGEON_PAGE, sprite
    assert "bossKeyForZone" in DUNGEON_PAGE


def test_arena_starts_at_boss_circle():
    # отдельной кнопки нет: арена открывается у круга босса в локации
    assert 'id="bossbtn"' not in DUNGEON_PAGE
    assert "function bossCircleNear()" in DUNGEON_PAGE
    assert 'talkBtn.textContent = "⚔ БОСС · "' in DUNGEON_PAGE
    assert "startArena(); }" in DUNGEON_PAGE
