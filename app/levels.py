"""Уровни игрока: за что дают XP и что выпадает за уровень.

Опыт:
  🃏 любая полученная карта   +100
  🎰 выигрыш в казино          +3
  🛒 покупка (рынок/магазин)  +50
  💰 успешная продажа         +75

Уровней 100. Первые 75 — мелкие награды, последние 25 — уже жирные.
"""

from __future__ import annotations

MAX_LEVEL = 100

XP_PER_CARD = 100
XP_CASINO_WIN = 3
XP_PURCHASE = 50
XP_SALE = 75


def xp_for_level(level: int) -> int:
    """Сколько XP нужно, чтобы уйти с уровня level на следующий."""
    level = max(1, int(level))
    return 300 + (level - 1) * 10


def total_xp_for(level: int) -> int:
    """Сколько XP нужно набрать суммарно, чтобы стоять на уровне level."""
    level = max(1, min(MAX_LEVEL, int(level)))
    return sum(xp_for_level(n) for n in range(1, level))


def level_from_xp(xp: int) -> int:
    xp = max(0, int(xp))
    level = 1
    need = 0
    while level < MAX_LEVEL:
        need += xp_for_level(level)
        if xp < need:
            return level
        level += 1
    return MAX_LEVEL


def progress(xp: int) -> tuple[int, int, int]:
    """(уровень, XP внутри уровня, сколько нужно до следующего)."""
    level = level_from_xp(xp)
    if level >= MAX_LEVEL:
        return level, 0, 0
    need = xp_for_level(level)
    inside = int(xp) - total_xp_for(level)
    return level, max(0, inside), need


def rewards_for(level: int) -> list[dict]:
    """Награда за конкретный уровень. Уровни до 75 — скромные."""
    level = int(level)
    if level < 2:
        return []
    if level <= 75:
        rewards: list[dict] = [
            {"kind": "points", "amount": 300 + level * 40},
        ]
        if level % 10 == 0:
            rewards.append({"kind": "drops", "amount": 2})
        if level % 15 == 0:
            rewards.append({"kind": "spins", "amount": 2})
        if level % 25 == 0:
            rewards.append({"kind": "cases", "amount": 1})
        return rewards

    # 76..100 — здесь уже нормально сыпет.
    rewards = [
        {"kind": "points", "amount": 15000 + (level - 75) * 2500},
        {"kind": "drops", "amount": 5},
        {"kind": "spins", "amount": 5},
    ]
    if level % 5 == 0:
        rewards.append({"kind": "cases", "amount": 2})
    if level % 10 == 0:
        rewards.append({"kind": "card", "rarity": "mythic"})
    if level in (80, 90, 100):
        rewards.append({"kind": "card", "rarity": "legendary"})
    if level in (90, 100):
        rewards.append({"kind": "shares", "amount": 10})
    return rewards


def describe(reward: dict) -> str:
    kind = reward["kind"]
    if kind == "points":
        return f"💰 {int(reward['amount'])} очков"
    if kind == "drops":
        return f"🎴 +{int(reward['amount'])} круток «Северо-Юг»"
    if kind == "spins":
        return f"🎰 +{int(reward['amount'])} спинов рулетки"
    if kind == "cases":
        return f"📦 +{int(reward['amount'])} кейс(ов)"
    if kind == "card":
        return f"🃏 карта ({reward['rarity']})"
    if kind == "shares":
        return f"📈 {int(reward['amount'])} акций"
    return str(reward)
