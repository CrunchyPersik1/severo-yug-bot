"""Кооп-босс: математика боя без базы."""

import re
from datetime import datetime, timedelta, timezone

from app import dungeon


def test_zones_match_page():
    assert dungeon.zone_count() == 10
    assert dungeon.zone_name(0) == "Опушка"
    assert dungeon.zone_name(9) == "Бездна"
    assert dungeon.zone_name(99) == "Бездна"
    assert dungeon.zone_name(-5) == "Опушка"


def test_page_zones_are_the_same_as_server():
    from app.webapp import DUNGEON_PAGE

    names = re.findall(r'\{n: "([^"]+)",', DUNGEON_PAGE)[:10]
    assert names == [name for name, _ in dungeon.ZONES]


def test_coop_boss_has_more_hp():
    solo = dungeon.base_hp(0, 1)
    coop = dungeon.base_hp(0, 2)
    assert solo == 600
    assert coop > solo
    assert abs(coop / solo - dungeon.COOP_HP_FACTOR) < 0.02
    assert dungeon.base_hp(9, 2) > dungeon.base_hp(9, 1)


def test_hp_grows_with_zone():
    hp = [dungeon.base_hp(zone, 1) for zone in range(dungeon.zone_count())]
    assert hp == sorted(hp)
    assert hp[0] == 600


def test_boss_hits_harder_deeper():
    damage = [dungeon.boss_damage(zone) for zone in range(dungeon.zone_count())]
    assert damage == sorted(damage)
    assert dungeon.boss_damage(0) == 5


def test_damage_and_zone_are_clamped():
    assert dungeon.clamp_damage(0) == dungeon.MIN_DAMAGE
    assert dungeon.clamp_damage(10_000) == dungeon.MAX_DAMAGE
    assert dungeon.clamp_damage("abc") == dungeon.MIN_DAMAGE
    assert dungeon.clamp_damage(None) == dungeon.MIN_DAMAGE
    assert dungeon.clamp_zone("abc") == 0
    assert dungeon.clamp_zone(-3) == 0
    assert dungeon.clamp_zone(42) == dungeon.zone_count() - 1


def test_ticks_since_counts_boss_hits():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert dungeon.ticks_since(None, now) == 0
    assert dungeon.ticks_since(now, now) == 0
    assert dungeon.ticks_since(now - timedelta(seconds=1), now) == 0
    assert dungeon.ticks_since(now - timedelta(seconds=2), now) == 1
    assert dungeon.ticks_since(now - timedelta(seconds=30), now) == 15
    assert dungeon.ticks_since(now - timedelta(seconds=30), now, every=0) == 0


def test_next_tick_keeps_phase():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert dungeon.next_tick_at(start, 3) == start + timedelta(seconds=6)
    assert dungeon.next_tick_at(None, 3) is None


def test_cooldown_left():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert dungeon.cooldown_left(None, now) == 0.0
    assert dungeon.cooldown_left(now, now) == dungeon.HIT_COOLDOWN
    assert dungeon.cooldown_left(now - timedelta(seconds=1), now) == 0.0
    assert dungeon.cooldown_left(now - timedelta(seconds=0.25), now) > 0


def test_ready_in_counts_down():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert dungeon.ready_in(None, now) == 0
    assert dungeon.ready_in(now + timedelta(seconds=7), now) == 7
    assert dungeon.ready_in(now - timedelta(seconds=7), now) == 0


def test_status_texts():
    assert dungeon.room_is_open("waiting") is True
    assert dungeon.room_is_open("fight") is True
    assert dungeon.room_is_open("dead") is False
    assert dungeon.status_text("waiting") == "ждём второго"
    assert dungeon.status_text("failed") == "все пали"


def test_wait_is_ten_seconds():
    assert dungeon.WAIT_SECONDS == 10
    assert dungeon.MAX_PLAYERS == 2
    assert dungeon.PLAYER_HP == 120


def test_late_join_grace():
    """Напарник может подсесть в уже начавшийся бой."""
    assert dungeon.JOIN_GRACE >= dungeon.BOSS_HIT_EVERY * 5
    assert dungeon.JOIN_GRACE <= 60


def test_zone_lock_is_unique_per_zone():
    keys = {dungeon.zone_lock(zone) for zone in range(dungeon.zone_count())}
    assert len(keys) == dungeon.zone_count()
    assert dungeon.zone_lock(0) == dungeon.zone_lock(-5)
    assert dungeon.zone_lock(0) != dungeon.zone_lock(1)


def test_boss_reward_grows_with_zone_and_coop():
    solo = dungeon.boss_reward(0, 1)
    coop = dungeon.boss_reward(0, 2)
    deep = dungeon.boss_reward(9, 1)
    assert solo["coins"] == dungeon.BOSS_COINS
    assert coop["coins"] > solo["coins"]
    assert deep["coins"] > solo["coins"]
    assert solo["kills"] == 1 and coop["kills"] == 1
    assert dungeon.boss_reward(0, 2)["coins"] == int(round(dungeon.BOSS_COINS * dungeon.COOP_COIN_BONUS))


def test_chat_limits_are_sane():
    assert 0 < dungeon.CHAT_COOLDOWN <= 5
    assert 20 <= dungeon.CHAT_MAX <= 200
