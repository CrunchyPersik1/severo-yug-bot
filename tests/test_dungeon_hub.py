"""Живая карта: реестр позиций в памяти процесса."""

from app.dungeon_hub import (
    TTL_SECONDS,
    DungeonHub,
    clamp_anim,
    clamp_coord,
    clamp_int,
    clamp_weapon,
    fresh,
)


def test_touch_and_snapshot():
    hub = DungeonHub()
    hub.touch(1, "Тимка", {"x": 100, "y": 9000, "zone": 0, "anim": "run"}, now=1000.0)
    hub.touch(2, "Саня", {"x": 300, "y": 9100, "zone": 0, "anim": "attack",
                          "hp": 90, "max_hp": 120}, now=1000.0)
    snap = hub.snapshot(1, now=1000.5)
    assert len(snap) == 1
    assert snap[0]["name"] == "Саня"
    assert snap[0]["x"] == 300.0
    assert snap[0]["y"] == 9100.0
    assert snap[0]["anim"] == "attack"
    assert snap[0]["hp"] == 90 and snap[0]["max_hp"] == 120


def test_self_is_not_shown():
    hub = DungeonHub()
    hub.touch(1, "A", {"zone": 0}, now=1000.0)
    assert hub.snapshot(1, now=1000.0) == []


def test_stale_spots_disappear():
    hub = DungeonHub()
    hub.touch(1, "A", {"zone": 0}, now=1000.0)
    hub.touch(2, "B", {"zone": 0}, now=1000.0)
    assert len(hub.snapshot(1, now=1000.0 + TTL_SECONDS - 1)) == 1
    assert hub.snapshot(1, now=1000.0 + TTL_SECONDS + 1) == []


def test_only_neighbour_zones():
    hub = DungeonHub()
    hub.touch(1, "A", {"zone": 0}, now=1000.0)
    hub.touch(2, "B", {"zone": 2}, now=1000.0)
    assert hub.snapshot(1, now=1000.0) == []
    hub.touch(2, "B", {"zone": 1}, now=1000.0)
    assert len(hub.snapshot(1, now=1000.0)) == 1


def test_drop_and_prune():
    hub = DungeonHub()
    hub.touch(1, "A", {"zone": 0}, now=1000.0)
    assert len(hub) == 1
    hub.drop(1)
    assert len(hub) == 0
    hub.touch(2, "B", {"zone": 0}, now=1000.0)
    assert hub.prune(now=1000.0 + TTL_SECONDS + 1) == 1
    assert len(hub) == 0


def test_coords_are_clamped():
    assert clamp_coord("abc") == 0.0
    assert clamp_coord(None) == 0.0
    assert clamp_coord(-50) == 0.0
    assert clamp_coord(1e9) == 4000.0
    assert clamp_coord(float("nan")) == 0.0
    assert clamp_coord(12.5) == 12.5


def test_whitelists():
    assert clamp_anim("run") == "run"
    assert clamp_anim("ATTACK") == "attack"
    assert clamp_anim("летит") == "idle"
    assert clamp_weapon("bow") == "bow"
    assert clamp_weapon("ракета") == "sword"
    assert clamp_int("7", 0, 9) == 7
    assert clamp_int(99, 0, 9) == 9
    assert clamp_int(None, 0, 9) == 0


def test_payload_shape():
    hub = DungeonHub()
    spot = hub.touch(5, "Тест", {"x": 12.34, "y": 56.78, "zone": 3, "facing": 2,
                                 "anim": "attack", "hp": 100, "max_hp": 120,
                                 "weapon": "staff"}, now=1.0)
    payload = spot.payload()
    assert payload["id"] == 5
    assert payload["zone"] == 3
    assert payload["weapon"] == "staff"
    assert payload["x"] == 12.3


def test_fresh_window():
    assert fresh(10.0, 11.0) is True
    assert fresh(10.0, 10.0 + TTL_SECONDS + 0.1) is False
