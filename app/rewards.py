"""Награды за PvP.

Проигравший отдаёт победителю 5% от очков своей карты (той, которой воевал).
Очки — это отдельный баланс игрока (players.bonus_points), а не стоимость карты:
сами карты в коллекции не портятся, их базовая стоимость неизменна.
Итоговый счёт = сумма очков уникальных карт + PvP-баланс (не ниже нуля).
"""

from __future__ import annotations

STAKE_PERCENT = 5


def battle_reward(loser_card_points: int) -> int:
    """Сколько очков победитель забирает у проигравшего."""
    return max(0, int(loser_card_points) * STAKE_PERCENT // 100)


def total_score(card_points: int, bonus_points: int) -> int:
    """Итоговый счёт игрока: карты + PvP-баланс, никогда не ниже нуля."""
    return max(0, int(card_points) + int(bonus_points))
