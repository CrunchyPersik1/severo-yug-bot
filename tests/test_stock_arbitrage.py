"""Сток не абьюзится через скупщика."""

from app import buyer, card_stock, cards as cards_mod, cards_d as cards_d_mod


def _all_cards():
    return list(cards_mod.CARDS) + list(cards_d_mod.CARDS_D)


def test_stock_points_price_beats_buyer_payout():
    # Если бы сток стоил дешевле, чем платит скупщик, это была бы печатная
    # машинка: купил в стоке — сдал в плюс. Проверяем на всех картах.
    for card in _all_cards():
        payback = buyer.price(card)
        floor_by_rarity = card_stock.POINTS_PRICE.get(card.rarity, 0)
        guard = max(floor_by_rarity, int(payback * card_stock.SELL_GUARD) + 1)
        assert guard > payback, card.card_id


def test_stock_stock_items_are_profitable_only_for_play():
    for item in card_stock.stock(2024):
        card = cards_mod.CARDS_BY_ID.get(item["id"]) or cards_d_mod.CARDS_D_BY_ID.get(item["id"])
        if card is None:
            continue
        assert item["prices"]["points"] > buyer.price(card)


def test_gems_cannot_be_cashed_out():
    # Гемы нельзя обменять на очки, поэтому покупка за гемы и продажа карты
    # скупщику всегда в минус по курсу 1 💎 = 55 555 очков.
    for item in card_stock.stock(2025):
        card = cards_mod.CARDS_BY_ID.get(item["id"]) or cards_d_mod.CARDS_D_BY_ID.get(item["id"])
        if card is None:
            continue
        payout = buyer.price(card)
        gem_value = item["prices"]["gems"] * 55_555
        assert payout < gem_value
