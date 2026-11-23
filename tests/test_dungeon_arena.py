"""Арена боссов в подземелье."""

from app.webapp import DUNGEON_PAGE


def test_arena_markup():
    for marker in ('id="arena"', 'id="acv"', 'id="ajoy"', 'id="aattack"',
                   'id="adash"', 'id="abHp"', 'id="apHp"', 'id="aexit"'):
        assert marker in DUNGEON_PAGE, marker


def test_arena_moves_like_a_game():
    # джойстик даёт скорость 300, рывок — импульс 700, удар бьёт в радиусе,
    # укрытия блокируют движение
    assert "const sp = 430;" in DUNGEON_PAGE
    assert "* 900" in DUNGEON_PAGE
    # лук: стрела летит в босса, урон фиксирован по локации
    assert "ARENA.shots.push({" in DUNGEON_PAGE
    assert "ARENA.dmg = 45 + zi * 35;" in DUNGEON_PAGE
    assert "function arenaBlocked(" in DUNGEON_PAGE
    assert "ARENA.cover = [" in DUNGEON_PAGE


def test_arena_has_hit_feedback():
    assert "ARENA.flash" in DUNGEON_PAGE
    assert "ARENA.shake = 0.18" in DUNGEON_PAGE
    assert "Math.floor(ARENA.t * 10) % 4" in DUNGEON_PAGE


def test_arena_boss_patterns():
    # арсенал растёт с локацией: одиночный, веер, кольцо, рывок, двойной
    assert "function bossShoot(pattern)" in DUNGEON_PAGE
    assert '"ring"' in DUNGEON_PAGE and '"fan"' in DUNGEON_PAGE
    assert '"charge"' in DUNGEON_PAGE and '"double"' in DUNGEON_PAGE
    assert "ARENA.arrows.push" in DUNGEON_PAGE
    # фазы по HP
    assert "b.hp < b.max * 0.33" in DUNGEON_PAGE


def test_arena_rewards_and_cooldown():
    assert "ARENA.reward = {coins: 500 + zi * 400" in DUNGEON_PAGE
    assert "ARENA.cd[zi] = Date.now() + 5000" in DUNGEON_PAGE
    # награда показывается на экране победы
    assert "ПОБЕДА" in DUNGEON_PAGE
    assert "монет" in DUNGEON_PAGE


def test_arena_uses_boss_sprites():
    for sprite in ("anomaly.png", "knight.png", "thief.png"):
        assert sprite in DUNGEON_PAGE, sprite
    assert "bossKeyForZone" in DUNGEON_PAGE


def test_arena_starts_at_boss_circle():
    # отдельной кнопки нет: арена открывается у круга босса в локации
    assert 'id="bossbtn"' not in DUNGEON_PAGE
    assert "function bossCircleNear()" in DUNGEON_PAGE
    assert 'talkBtn.textContent = "⚔ БОСС · "' in DUNGEON_PAGE
    # круг теперь открывает выбор: соло-арена или кооп на двоих
    assert "talkBtn.onclick = function(){ bossModeOpen(); };" in DUNGEON_PAGE
    assert "startArena();\n};" in DUNGEON_PAGE
