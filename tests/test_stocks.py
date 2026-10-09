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


def test_alert_due_threshold():
    # рост меньше 10% — молчим
    assert not stocks.alert_due(1099, 1000, None)
    # +10% и больше — пора, если кулдаун прошёл
    assert stocks.alert_due(1100, 1000, None)
    assert stocks.alert_due(1200, 1000, None)
    # но не чаще кулдауна
    assert not stocks.alert_due(1200, 1000, 60)
    assert stocks.alert_due(1200, 1000, stocks.ALERT_COOLDOWN_MINUTES * 60 + 1)
    # без отметки не оповещаем
    assert not stocks.alert_due(2000, 0, None)


def test_alert_message_renders():
    from app.stocks_alerts import render_alerts

    text = render_alerts(
        [{"slug": "syug", "name": "SeveroCoin", "emoji": "🎴", "price": 1200, "from": 1000, "change": 20.0}]
    )
    assert "SeveroCoin" in text and "+20.0%" in text and "1 200" in text


def test_new_coin_names():
    names = {str(stock["slug"]): str(stock["name"]) for stock in stocks.STOCKS}
    assert names["syug"] == "SeveroCoin"
    assert names["uchitel"] == "ДэнКоин"
    assert names["misha"] == "Миша Inc."
    assert names["ludoman"] == "MusorDelta_Coin"
    assert names["kartofan"] == "Карточный_Coin"
    assert "zavuch" not in names, "Завуч Групп больше не торгуется"


def test_by_slug():
    assert stocks.by_slug("syug") is not None
    assert stocks.by_slug("SYUG") is not None
    assert stocks.by_slug("nope") is None


def test_stocks_page_has_chart_and_api():
    from app.webapp import STOCKS_PAGE

    assert "/api/stocks" in STOCKS_PAGE
    assert "lineChart" in STOCKS_PAGE, "график курса должен быть"
    assert "data-open" in STOCKS_PAGE, "по монете нужно кликать"
    assert "setInterval" in STOCKS_PAGE


def test_every_stock_has_required_fields():
    for stock in stocks.STOCKS:
        assert stock["slug"] and stock["name"] and stock["emoji"]
        assert int(stock["base"]) > 0
        assert 0 < float(stock["vol"]) < 0.5
