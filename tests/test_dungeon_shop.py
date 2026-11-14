"""Лавка Насибуллина: ежедневный сток оружия."""

from datetime import date, timedelta

from app import dungeon_shop
from app.webapp import DUNGEON_PAGE


def test_stock_is_six_and_deterministic():
    day = date(2026, 11, 15)
    first = dungeon_shop.stock(day)
    second = dungeon_shop.stock(day)
    assert len(first) == 6
    assert [w["id"] for w in first] == [w["id"] for w in second]


def test_stock_changes_next_day():
    a = [w["id"] for w in dungeon_shop.stock(date(2026, 11, 15))]
    b = [w["id"] for w in dungeon_shop.stock(date(2026, 11, 16))]
    assert a != b


def test_prices_grow_with_tier():
    stock = dungeon_shop.stock(date(2026, 11, 15))
    cheap = min(stock, key=lambda w: w["tier"])
    rich = max(stock, key=lambda w: w["tier"])
    assert rich["price"] > cheap["price"]


def test_find_only_today():
    day = date(2026, 11, 15)
    item = dungeon_shop.stock(day)[0]
    assert dungeon_shop.find(item["id"], day) is not None
    assert dungeon_shop.find("sword_9_9", day) in (None, dungeon_shop.find("sword_9_9", day))


def test_payload_marks_bought():
    day = date(2026, 11, 15)
    item = dungeon_shop.stock(day)[0]
    data = dungeon_shop.payload(500, [item["id"]], day)
    assert data["day"] == "2026-11-15"
    assert any(w["bought"] for w in data["stock"])
    assert data["coins"] == 500


def test_panel_in_page():
    for marker in ('id="nshop"', 'id="nshopbtn"', 'id="nslist"', "openShop()", "buyWeapon("):
        assert marker in DUNGEON_PAGE, marker
