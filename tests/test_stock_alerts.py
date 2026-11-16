"""Сток: гемы, перекрутка и уведомления."""

from datetime import datetime, timezone

from app import card_stock, stock_alerts


def test_prices_are_in_gems_by_rarity():
    assert card_stock.GEM_PRICE["rare"] == 1
    assert card_stock.GEM_PRICE["legendary"] == 15
    assert card_stock.GEM_PRICE["secret"] == 20
    assert card_stock.GEM_PRICE["ultimate"] == 40
    assert card_stock.GEM_PRICE["teacher"] == 60
    assert card_stock.GEM_PRICE["ultra"] == 80
    assert all(item["currency"] == "gems" for item in card_stock.stock(99))


def test_reroll_changes_only_my_stock():
    shared = [x["id"] for x in card_stock.stock(4242)]
    mine = [x["id"] for x in card_stock.stock(4242, 1, 777)]
    other = [x["id"] for x in card_stock.stock(4242, 1, 778)]
    assert shared != mine
    assert mine != other


def test_timer_hits_even_boundaries():
    moment = datetime(2026, 11, 17, 16, 3, 20, tzinfo=timezone.utc)
    left = card_stock.seconds_left(moment)
    assert left == 100
    # граница ровно в 16:05:00
    exact = datetime(2026, 11, 17, 16, 5, 0, tzinfo=timezone.utc)
    assert card_stock.seconds_left(exact) == 300


def test_reroll_costs_19_gems():
    assert card_stock.REROLL_PRICE == 19


def test_alerts_module_wired():
    import inspect

    import main

    source = inspect.getsource(main._ticker)
    assert "stock_alerts.tick" in source
    text = inspect.getsource(stock_alerts.tick)
    assert "stock_alerts" in text
    assert "Сток карт обновился" in text


def test_settings_has_alert_toggle():
    from app.webtheme import BOOTSTRAP

    assert 'id="__sw-stock"' in BOOTSTRAP
    assert "stock_alerts" in BOOTSTRAP
