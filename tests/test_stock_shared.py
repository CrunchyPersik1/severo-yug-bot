"""Сток общий для всех, пока не перекрутили."""

from app import card_stock
from app.webapp import PAGE


def test_stock_is_same_for_different_players():
    window = 9090
    a = [x["id"] for x in card_stock.stock(window, 0, 1)]
    b = [x["id"] for x in card_stock.stock(window, 0, 999)]
    assert a == b


def test_reroll_makes_personal_stock():
    window = 9090
    base = [x["id"] for x in card_stock.stock(window, 0, 1)]
    mine = [x["id"] for x in card_stock.stock(window, 1, 1)]
    other = [x["id"] for x in card_stock.stock(window, 1, 2)]
    assert mine != base
    assert mine != other


def test_cards_are_not_dimmed_and_marked():
    # раньше купленные гасились opacity:.55 — выглядело как «нельзя купить»
    assert ".scard.own{opacity" not in PAGE
    assert 'class="scol"' in PAGE
    assert 'class="srar"' in PAGE
    assert "RARITY_COLORS" in PAGE
