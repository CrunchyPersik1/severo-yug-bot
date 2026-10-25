"""Живая карта подземелья: санитайзеры присутствия."""

from datetime import datetime, timedelta, timezone

from app import dungeon_presence as dp


def test_coords_are_clamped():
    assert dp.clamp_coord("abc") == 0.0
    assert dp.clamp_coord(None) == 0.0
    assert dp.clamp_coord(-50) == 0.0
    assert dp.clamp_coord(1e9) == dp.MAX_COORD
    assert dp.clamp_coord(float("nan")) == 0.0
    assert dp.clamp_coord(12.5) == 12.5


def test_anim_and_weapon_whitelists():
    assert dp.clamp_anim("run") == "run"
    assert dp.clamp_anim("ATTACK") == "attack"
    assert dp.clamp_anim("летит") == "idle"
    assert dp.clamp_anim(None) == "idle"
    assert dp.clamp_weapon("bow") == "bow"
    assert dp.clamp_weapon("ракета") == "sword"
    assert dp.clamp_weapon(None) == "sword"


def test_ints_are_clamped():
    assert dp.clamp_int("7", 0, 9) == 7
    assert dp.clamp_int(99, 0, 9) == 9
    assert dp.clamp_int(-3, 0, 9) == 0
    assert dp.clamp_int(None, 0, 9) == 0


def test_fresh_window():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert dp.fresh(None, now) is False
    assert dp.fresh(now - timedelta(seconds=1), now) is True
    assert dp.fresh(now - timedelta(seconds=dp.TTL_SECONDS + 1), now) is False
    assert dp.stale_before(now) == now - timedelta(seconds=dp.TTL_SECONDS)


def test_limits_are_sane():
    # дольше TTL игрока не показываем, но и не мигаем каждую секунду
    assert 2 <= dp.TTL_SECONDS <= 15
    assert dp.MAX_REMOTE >= 4
