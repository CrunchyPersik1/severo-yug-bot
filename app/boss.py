"""Рейд-босс: общее HP, каждый удар — фиксированный урон.

Карты и способности не нужны: любой игрок жмёт кнопку и снимает 50 HP.
"""

from __future__ import annotations

DEFAULT_NAME = "Завуч-Титан"
DEFAULT_HP = 15_000
HIT_DAMAGE = 50

# Чтобы один игрок не задолбил босса за секунду.
HIT_COOLDOWN_SECONDS = 0.8

# Награда всем, если босса добили.
REWARD_DROPS = 10
REWARD_SPINS = 10
REWARD_CASES = 3


def bar(hp: int, max_hp: int, width: int = 12) -> str:
    """Полоска здоровья: 🟩 заполнено, ⬛ пусто."""
    max_hp = max(1, int(max_hp))
    hp = max(0, min(int(hp), max_hp))
    filled = int(round(width * hp / max_hp))
    return "🟩" * filled + "⬛" * (width - filled)


def percent(hp: int, max_hp: int) -> int:
    if max_hp <= 0:
        return 0
    return max(0, min(100, int(round(int(hp) * 100 / int(max_hp)))))
