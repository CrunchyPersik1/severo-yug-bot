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


def test_next_price_moves_to_target_smoothly():
    # первый шаг вверх — не больше 25% (без телепорта)
    price = stocks.next_price(1000, 1000, 0.0, target=1500)
    assert 1000 < price <= 1250
    # доезжает до цели
    for _ in range(60):
        price = stocks.next_price(price, 1000, 0.0, target=1500)
    assert price == 1500
    # и вниз тоже
    price = 1500
    for _ in range(60):
        price = stocks.next_price(price, 1500, 0.0, target=900)
    assert price == 900
    # без цели — обычный шаг (волатильность 0 = стоит)
    assert stocks.next_price(1000, 1000, 0.0) == 1000


def test_target_stays_inside_the_corridor():
    # Цель ниже пола — курс прижимается к полу, а не улетает в ноль.
    price = 1000
    for _ in range(60):
        price = stocks.next_price(price, 1000, 0.0, target=10)
    assert price == int(1000 * stocks.FLOOR_MULT)

    # Цель выше потолка — курс прижимается к потолку.
    price = 1000
    for _ in range(80):
        price = stocks.next_price(price, 1000, 0.0, target=100_000)
    assert price == int(1000 * stocks.CEIL_MULT)


def test_max_per_stock_is_one_hundred():
    assert stocks.MAX_PER_STOCK == 100


def test_find_spikes():
    spikes = stocks.find_spikes([100, 100, 110, 110, 90, 91])
    assert [s["i"] for s in spikes] == [2, 4]
    assert spikes[0]["change"] == 10.0
    assert spikes[1]["change"] == -18.2


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
    assert "candles(" in STOCKS_PAGE, "график курса должен быть"
    assert "data-slug" in STOCKS_PAGE, "по монете нужно кликать"
    assert "setInterval" in STOCKS_PAGE, "курс должен обновляться сам"
    # сделки идут через тот же роутер, что и раньше
    assert '"/api/stocks/" + kind' in STOCKS_PAGE


def test_every_stock_has_required_fields():
    for stock in stocks.STOCKS:
        assert stock["slug"] and stock["name"] and stock["emoji"]
        assert int(stock["base"]) > 0
        assert 0 < float(stock["vol"]) < 0.5


def test_stale_target_below_floor_does_not_stick():
    """Устаревшая цель ниже пола не должна запирать курс на полу."""
    from app import stocks

    base = 1000
    low = int(base * stocks.FLOOR_MULT)
    # цель осталась с прошлых настроек и лежит ниже пола
    assert low > 100
    assert stocks.clamp_target(100, base) == low
    # ровно так торговый цикл понимает «дошли»: иначе цель не сбросится
    assert stocks.clamp_target(100, base) == low
    # а с пола обычный шаг обязан уводить вверх
    import random

    rng = random.Random(5)
    price = low
    for _ in range(80):
        price = stocks.next_price(price, base, 0.03, rng)
        if price != low:
            break
    assert price != low, "курс не выходит с пола"


def test_clamp_target_keeps_inside_corridor():
    from app import stocks

    base = 1000
    low = int(base * stocks.FLOOR_MULT)
    high = int(base * stocks.CEIL_MULT)
    assert stocks.clamp_target(1, base) == low
    assert stocks.clamp_target(999999, base) == high
    assert stocks.clamp_target(1200, base) == 1200
