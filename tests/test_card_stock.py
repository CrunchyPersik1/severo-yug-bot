"""Сток карт в магазине: общий, каждые 5 минут."""

from datetime import datetime, timedelta, timezone

from app import card_stock


def test_window_is_five_minutes():
    start = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    assert card_stock.window_key(start) == card_stock.window_key(
        start + timedelta(minutes=4, seconds=59)
    )
    assert card_stock.window_key(start) != card_stock.window_key(
        start + timedelta(minutes=5)
    )


def test_stock_is_shared_and_deterministic():
    window = 12_345
    first = card_stock.stock(window)
    second = card_stock.stock(window)
    assert len(first) == card_stock.SLOTS
    assert [x["id"] for x in first] == [x["id"] for x in second]


def test_stock_changes_between_windows():
    a = [x["id"] for x in card_stock.stock(1000)]
    b = [x["id"] for x in card_stock.stock(1001)]
    assert a != b


def test_rare_cards_weight_less():
    common = card_stock._weight("rare")
    ultra = card_stock._weight("ultra")
    assert ultra < common


def test_payload_has_timer_and_flags():
    data = card_stock.payload({"amelia"}, 777)
    assert data["window"] == 777
    assert 0 < data["seconds_left"] <= card_stock.WINDOW_SECONDS
    assert data["stock"]
    assert all("price" in item and "currency" in item for item in data["stock"])


def test_page_has_stock_block():
    from app.webapp import PAGE

    for marker in ('id="stockBox"', 'id="stkGrid"', 'id="stkTimer"', "stockLoad()"):
        assert marker in PAGE, marker
    # покупка и обновление каждые 5 минут
    assert "/api/shop/stock" in PAGE
    assert "Сток обновился" in PAGE
