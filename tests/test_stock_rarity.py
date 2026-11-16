"""Сток: настоящие шансы редкостей и рабочие кнопки покупки."""

import collections

from app import card_stock
from app.webapp import PAGE


def test_rarity_weights_are_not_flattened():
    rare = card_stock._weight("rare")
    ultra = card_stock._weight("ultra")
    teacher = card_stock._weight("teacher")
    # раньше «пол» 0.05 уравнивал всё редкое: ультра и учителя выпадали
    # в сотни раз чаще. Теперь порядок сохраняется.
    assert ultra < rare / 100
    assert teacher < rare / 100


def test_stock_rarity_distribution_is_sane():
    counter = collections.Counter()
    for window in range(400):
        counter.update(item["rarity"] for item in card_stock.stock(window))
    total = sum(counter.values())
    share = {key: value / total for key, value in counter.items()}
    assert share.get("rare", 0) > 0.25
    assert share.get("legendary", 0) < 0.03
    assert share.get("teacher", 0) < 0.01
    assert share.get("ultra", 0) < 0.01


def test_buy_buttons_use_existing_helper():
    # post() в этой странице не существует — из-за этого клики молчали
    assert 'send("/api/shop/stock/buy"' in PAGE
    assert 'send("/api/shop/stock/reroll"' in PAGE
    assert 'await post("/api/shop/stock' not in PAGE
