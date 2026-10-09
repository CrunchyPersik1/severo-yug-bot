"""Биржа: комиссия, границы курса и расчёт изменения."""

import random

from app import stocks


def test_buy_is_above_and_sell_below_the_rate():
    assert stocks.buy_price(1000) > 1000
    assert stocks.sell_price(1000) < 1000
    # круговая сделка всегда в минус — фармить нельзя
    assert stocks.buy_price(1000) > stocks.sell_price(1000)


def test_next_price_stays_in_corridor():
    rng = random.Random(1)
    price = 1000
    for _ in range(5000):
        price = stocks.next_price(price, 1000, 0.05, rng)
        assert 150 <= price <= 6000, price


def test_change_percent():
    assert stocks.change_percent([100, 110]) == 10.0
    assert stocks.change_percent([100, 90]) == -10.0
    assert stocks.change_percent([100]) == 0.0
    assert stocks.change_percent([]) == 0.0


def test_by_slug():
    assert stocks.by_slug("syug") is not None
    assert stocks.by_slug("SYUG") is not None
    assert stocks.by_slug("nope") is None


def test_stocks_page_has_chart_and_api():
    from app.webapp import STOCKS_PAGE

    assert "/api/stocks" in STOCKS_PAGE
    assert "spark" in STOCKS_PAGE
    assert "setInterval" in STOCKS_PAGE


def test_every_stock_has_required_fields():
    for stock in stocks.STOCKS:
        assert stock["slug"] and stock["name"] and stock["emoji"]
        assert int(stock["base"]) > 0
        assert 0 < float(stock["vol"]) < 0.5
