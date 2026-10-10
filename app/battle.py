"""Боевой движок PvP. Чистые функции без БД и Telegram — легко тестируется.

Урон зависит только от карты (ATK и способность), а не от редкости и очков.
Состояние полностью сериализуемо в JSON и живёт в БД (Render может перезапуститься).
"""

from __future__ import annotations

import random
from copy import deepcopy
from typing import Any

from .cards import CARD_PAIRS, Card, get_card

KEY_A = "a"
KEY_B = "b"

ACTION_HIT = "hit"
ACTION_ABILITY = "ability"

STATUS_ACTIVE = "active"
STATUS_FINISHED = "finished"

WINNER_A = "a"
WINNER_B = "b"
WINNER_DRAW = "draw"

MAX_LOG = 24


def other(key: str) -> str:
    return KEY_B if key == KEY_A else KEY_A


# --------------------------------------------------------------------------- #
# Создание состояния
# --------------------------------------------------------------------------- #


def new_side(user_id: int, card: Card, stats: dict[str, int] | None = None) -> dict[str, Any]:
    """stats — эффективные статы с учётом улучшений (атака, HP, защита)."""
    stats = stats or {}
    atk = int(stats.get("atk", card.atk))
    hp = int(stats.get("hp", card.hp))
    defense = max(0, min(60, int(stats.get("def", 0))))
    return {
        "user_id": user_id,
        "card_id": card.card_id,
        "hp": hp,
        "max_hp": hp,
        "atk": atk,
        "def": defense,
        "shield": 0,
        "poison": 0,
        "poison_turns": 0,
        "stun": 0,
        "dodge": 0,
        "counter": 0,
        "counter_turns": 0,
        "weaken": 0,
        "weaken_turns": 0,
        "silence": 0,
        # Смута: сколько ходов атака идёт «не туда» (Посейдон).
        "confuse": 0,
        "cd": 0,
        "timeouts": 0,
        # Вечная утечка (Словесное исцеление Эмина): сколько HP в ход жертвы
        # уходит хозяину заклинания. Действует, пока хозяин жив.
        "drain": 0,
        "drain_from": None,
    }


def new_state(
    card_a: Card,
    card_b: Card,
    first: str = KEY_A,
    stats_a: dict[str, int] | None = None,
    stats_b: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "sides": {
            KEY_A: new_side(0, card_a, stats_a),
            KEY_B: new_side(0, card_b, stats_b),
        },
        "turn": first,
        "turn_no": 1,
        "log": [],
        "over": False,
        "winner": None,
        "reason": None,
    }


def clone(state: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(state)


# --------------------------------------------------------------------------- #
# Вспомогательное
# --------------------------------------------------------------------------- #


def _log(state: dict[str, Any], message: str) -> None:
    state["log"].append(message)
    if len(state["log"]) > MAX_LOG:
        del state["log"][: len(state["log"]) - MAX_LOG]


def ability_targets(card: Card) -> str:
    """Кого требует способность: 'enemy', 'ally' или 'both'."""
    effects = card.ability.effects
    offence = any(
        key in effects
        for key in ("damage", "steal", "poison", "stun", "silence", "weaken", "drain")
    )
    support = "heal" in effects or "shield" in effects or bool(effects.get("cleanse"))
    if offence and support:
        return "both"
    return "enemy" if offence else "ally"


def can_use_ability(side: dict[str, Any]) -> bool:
    return side["cd"] <= 0 and side["silence"] <= 0


def pair_partner(state: dict[str, Any], actor_key: str) -> str | None:
    """Живой союзник, который составляет пару с картой актёра.

    Работает только в командном бою: у сторон должна совпадать команда.
    В бою 1 на 1 у карт нет команды, поэтому пара не срабатывает — там они враги.
    """
    actor = state["sides"][actor_key]
    partner_card = CARD_PAIRS.get(str(actor.get("card_id")))
    if not partner_card:
        return None
    for key, side in state["sides"].items():
        if key == actor_key or side.get("card_id") != partner_card:
            continue
        if side["hp"] <= 0:
            continue
        if actor.get("team") is None or side.get("team") != actor.get("team"):
            continue
        return key
    return None


def _cleanse(state: dict[str, Any], key: str) -> None:
    side = state["sides"][key]
    had = (
        side["poison_turns"] > 0
        or side["stun"] > 0
        or side["silence"] > 0
        or side["weaken_turns"] > 0
    )
    side["poison"] = 0
    side["poison_turns"] = 0
    side["stun"] = 0
    side["silence"] = 0
    side["weaken"] = 0
    side["weaken_turns"] = 0
    if had:
        _log(state, "🧼 Сняты все негативные эффекты")


def _heal(state: dict[str, Any], key: str, amount: int) -> None:
    side = state["sides"][key]
    before = side["hp"]
    side["hp"] = min(side["max_hp"], side["hp"] + max(0, amount))
    gained = side["hp"] - before
    if gained > 0:
        _log(state, f"💚 Лечение: +{gained} HP")


def _deal_damage(
    state: dict[str, Any],
    target_key: str,
    amount: int,
    label: str,
    ignore_shield: bool = False,
    use_defense: bool = True,
) -> int:
    target = state["sides"][target_key]
    amount = int(amount)
    if amount <= 0:
        return 0

    # Защита от улучшений: процент снижения урона, максимум 60%.
    if use_defense:
        defense = int(target.get("def", 0))
        if defense > 0:
            amount = max(1, round(amount * (100 - defense) / 100))
    if target["dodge"] > 0:
        target["dodge"] -= 1
        _log(state, f"{label}: промах (уклонение)")
        return 0

    absorbed = 0
    if not ignore_shield and target["shield"] > 0:
        absorbed = min(target["shield"], amount)
        target["shield"] -= absorbed
        amount -= absorbed

    target["hp"] -= amount
    suffix = f" (щит поглотил {absorbed})" if absorbed else ""
    if ignore_shield and target["shield"] > 0:
        suffix = " (сквозь щит)"
    _log(state, f"{label}: −{amount}{suffix}")
    return amount


def _counter_attack(state: dict[str, Any], attacker_key: str, defender_key: str) -> None:
    defender = state["sides"][defender_key]
    if defender["hp"] <= 0 or defender["counter"] <= 0 or defender["counter_turns"] <= 0:
        return
    _deal_damage(state, attacker_key, int(defender["counter"]), "🛡️ Контрудар")


def _clear_owner_drains(state: dict[str, Any], dead_key: str) -> None:
    """Со смертью хозяина заклинания утечка с противника снимается."""
    for key in (KEY_A, KEY_B):
        side = state["sides"][key]
        if side.get("drain_from") == dead_key and side["drain"] > 0:
            side["drain"] = 0
            side["drain_from"] = None
            _log(state, "🔓 Заклинание спало")


def _check_over(state: dict[str, Any]) -> None:
    a_dead = state["sides"][KEY_A]["hp"] <= 0
    b_dead = state["sides"][KEY_B]["hp"] <= 0
    if a_dead:
        _clear_owner_drains(state, KEY_A)
    if b_dead:
        _clear_owner_drains(state, KEY_B)
    if not (a_dead or b_dead):
        return
    state["over"] = True
    if a_dead and b_dead:
        state["winner"] = WINNER_DRAW
        state["reason"] = "double_ko"
    elif a_dead:
        state["winner"] = WINNER_B
        state["reason"] = "ko"
    else:
        state["winner"] = WINNER_A
        state["reason"] = "ko"


# --------------------------------------------------------------------------- #
# Ходы
# --------------------------------------------------------------------------- #


def _begin_turn(state: dict[str, Any], key: str) -> str:
    return begin_unit_turn(state, key)


def begin_unit_turn(state: dict[str, Any], key: str, tick_cd: bool = True) -> str:
    """Начало хода карты. Возвращает 'act', 'skip' (оглушён) или 'dead'.

    tick_cd=False нужен командному бою: там КД откатывается раз в раунд,
    а яд, утечка и оглушение — в момент хода конкретной карты.
    """
    side = state["sides"][key]
    if tick_cd:
        side["cd"] = max(0, side["cd"] - 1)
        side["silence"] = max(0, side["silence"] - 1)
        side["confuse"] = max(0, int(side.get("confuse", 0)) - 1)

    if side["drain"] > 0:
        owner = state["sides"].get(side["drain_from"] or "")
        if owner is None or owner["hp"] <= 0:
            side["drain"] = 0
            side["drain_from"] = None
        else:
            moved = min(int(side["drain"]), max(0, side["hp"]))
            if moved > 0:
                side["hp"] -= moved
                owner["hp"] = min(owner["max_hp"], owner["hp"] + moved)
                _log(state, f"🔗 Заклинание: −{moved} HP в пользу врага")
            if side["hp"] <= 0:
                return "dead"

    if side["poison_turns"] > 0:
        _deal_damage(state, key, int(side["poison"]), "☠️ Яд", ignore_shield=True, use_defense=False)
        side["poison_turns"] -= 1
        if side["poison_turns"] <= 0:
            side["poison_turns"] = 0
            side["poison"] = 0
        if side["hp"] <= 0:
            return "dead"

    if side["stun"] > 0:
        side["stun"] -= 1
        _log(state, "💫 Оглушён — ход пропущен")
        return "skip"

    return "act"


def _end_turn(state: dict[str, Any], key: str) -> None:
    side = state["sides"][key]
    if side["weaken_turns"] > 0:
        side["weaken_turns"] -= 1
        if side["weaken_turns"] == 0:
            side["weaken"] = 0
    if side["counter_turns"] > 0:
        side["counter_turns"] -= 1
        if side["counter_turns"] == 0:
            side["counter"] = 0


def _strike(
    state: dict[str, Any], actor_key: str, card: Card, foe_key: str | None = None
) -> None:
    foe_key = foe_key or other(actor_key)
    # Ослабление снижает урон того, на кого наложено, поэтому берём стат актёра,
    # а не цели: раньше урон падал при ударе по ослабленному врагу и не падал
    # у самого ослабленного.
    attacker = state["sides"][actor_key]
    damage = max(1, card.atk - int(attacker["weaken"]))

    # Смута: запутавшийся бьёт не туда. 50% — как надо, 25% — лечит врага,
    # 25% — бьёт себя.
    if int(attacker.get("confuse", 0)) > 0:
        roll = random.random()
        if roll < 0.25:
            _heal(state, foe_key, damage)
            _log(state, f"❓ Смута: {card.name} вместо удара лечит врага (+{damage})")
            _counter_attack(state, actor_key, foe_key)
            return
        if roll < 0.5:
            _deal_damage(state, actor_key, damage, "❓ Смута: удар по себе")
            return

    _deal_damage(state, foe_key, damage, "⚔️ Удар")
    _counter_attack(state, actor_key, foe_key)


def _apply_ability(
    state: dict[str, Any],
    actor_key: str,
    card: Card,
    foe_key: str | None = None,
    ally_key: str | None = None,
) -> None:
    actor = state["sides"][actor_key]
    foe_key = foe_key or other(actor_key)
    ally_key = ally_key or actor_key
    foe = state["sides"][foe_key]
    effects = card.ability.effects
    name = card.ability.name

    hits = int(effects.get("hits", 1))
    if "damage" in effects:
        for _ in range(max(1, hits)):
            if foe["hp"] <= 0:
                break
            _deal_damage(
                state,
                foe_key,
                int(effects["damage"]),
                f"✨ {name}",
                ignore_shield=bool(effects.get("ignore_shield")),
            )

    if "steal" in effects:
        stolen = _deal_damage(state, foe_key, int(effects["steal"]), f"🩸 {name}")
        if stolen > 0:
            _heal(state, actor_key, stolen)

    heal_amount = 0
    if "heal" in effects:
        heal_amount = int(effects["heal"])
        _heal(state, ally_key, heal_amount)

    shield_amount = 0
    if "shield" in effects:
        shield_amount = int(effects["shield"])
        state["sides"][ally_key]["shield"] += shield_amount
        _log(state, f"🛡️ Щит: +{shield_amount}")

    # Парная синергия: пока напарник жив и в той же команде, он лечится и
    # прикрывается вместе с актёром. Если эффект и так нацелен на напарника,
    # второй раз не накладываем.
    partner_key = pair_partner(state, actor_key)
    if partner_key is not None and partner_key != ally_key:
        if heal_amount:
            _heal(state, partner_key, heal_amount)
            _log(state, "❤️ Пара: напарник тоже лечится")
        if shield_amount:
            state["sides"][partner_key]["shield"] += shield_amount
            _log(state, f"❤️ Пара: щит +{shield_amount} напарнику")

    if "poison" in effects:
        poison = int(effects["poison"])
        turns = int(effects.get("poison_turns", 2))
        foe["poison"] = max(int(foe["poison"]), poison)
        foe["poison_turns"] = max(int(foe["poison_turns"]), turns)
        _log(state, f"☠️ Яд {poison} на {turns} х.")

    if "stun" in effects:
        foe["stun"] += int(effects["stun"])
        _log(state, "💫 Оглушение")

    if "silence" in effects:
        foe["silence"] = max(int(foe["silence"]), int(effects["silence"]))
        _log(state, "🔇 Немота: способность недоступна")

    if "confuse" in effects:
        foe["confuse"] = max(int(foe.get("confuse", 0)), int(effects["confuse"]))
        _log(state, f"❓ Смута на {int(effects['confuse'])} х.")

    if "dodge" in effects:
        actor["dodge"] += int(effects["dodge"])
        _log(state, f"🌀 Уклонение ×{int(effects['dodge'])}")

    if "counter" in effects:
        actor["counter"] = int(effects["counter"])
        actor["counter_turns"] = int(effects.get("counter_turns", 2))
        _log(state, f"🛡️ Контрудар {actor['counter']}")

    if "drain" in effects:
        foe["drain"] = int(effects["drain"])
        foe["drain_from"] = actor_key
        _log(state, f"🔗 Заклинание: {int(effects['drain'])} HP в ход в пользу врага")

    if "weaken" in effects:
        foe["weaken"] = max(int(foe["weaken"]), int(effects["weaken"]))
        foe["weaken_turns"] = max(
            int(foe["weaken_turns"]), int(effects.get("weaken_turns", 2))
        )
        _log(state, f"🔻 Ослабление −{int(effects['weaken'])} к урону")

    if effects.get("cleanse"):
        _cleanse(state, ally_key)

    if "self_stun" in effects:
        actor["stun"] += int(effects["self_stun"])
        _log(state, f"😵 {name}: расплата, следующий ход пропущен")

    actor["cd"] = card.ability.cooldown

    if "damage" in effects or "steal" in effects:
        _counter_attack(state, actor_key, foe_key)


def _advance(state: dict[str, Any], max_turns: int) -> None:
    """Пропускает ходы оглушённых, пока не найдётся тот, кто может действовать."""
    for _ in range(8):
        if state["over"]:
            return
        key = state["turn"]
        status = _begin_turn(state, key)
        if status == "dead":
            _check_over(state)
            return
        if status == "act":
            return
        _end_turn(state, key)
        state["turn_no"] += 1
        if max_turns and state["turn_no"] > max_turns:
            _declare_draw(state, "turn_limit")
            return
        state["turn"] = other(key)


def _declare_draw(state: dict[str, Any], reason: str) -> None:
    state["over"] = True
    state["winner"] = WINNER_DRAW
    state["reason"] = reason


def apply_action(
    state: dict[str, Any],
    actor_key: str,
    action: str = ACTION_HIT,
    *,
    max_turns: int = 0,          # 0 — без лимита ходов
    max_timeouts: int = 3,
    register_timeout: bool = False,
) -> dict[str, Any]:
    """Применить ход. Возвращает {ok, error, status}.

    Функция мутирует state. Вызывающий обязан сохранить state в БД.
    """
    if state["over"]:
        return {"ok": False, "error": "Бой уже закончен"}
    if state["turn"] != actor_key:
        return {"ok": False, "error": "Сейчас не ваш ход"}

    side = state["sides"][actor_key]
    if register_timeout:
        side["timeouts"] += 1
        if side["timeouts"] >= max_timeouts:
            state["over"] = True
            state["winner"] = other(actor_key)
            state["reason"] = "timeout"
            _log(state, "⏱️ Слишком много пропусков хода — техническое поражение")
            return {"ok": True, "error": None, "status": "timeout_forfeit"}
        _log(state, "⏱️ Время вышло — автоудар")
    else:
        # Считаем именно подряд идущие пропуски: после настоящего хода счётчик
        # таймаутов сбрасывается, иначе три промаха за весь бой = поражение.
        side["timeouts"] = 0

    card = get_card(side["card_id"])
    if action == ACTION_ABILITY and can_use_ability(side):
        _apply_ability(state, actor_key, card)
    else:
        if action == ACTION_ABILITY and side["silence"] > 0:
            _log(state, "🔇 Способность заблокирована — обычный удар")
        elif action == ACTION_ABILITY and side["cd"] > 0:
            _log(state, f"⌛ Способность на перезарядке ({side['cd']}) — обычный удар")
        _strike(state, actor_key, card)

    _check_over(state)
    if state["over"]:
        return {"ok": True, "error": None, "status": "finished"}

    _end_turn(state, actor_key)
    state["turn_no"] += 1
    if max_turns and state["turn_no"] > max_turns:
        _declare_draw(state, "turn_limit")
        return {"ok": True, "error": None, "status": "draw"}

    state["turn"] = other(actor_key)
    _advance(state, max_turns)
    return {"ok": True, "error": None, "status": "finished" if state["over"] else "active"}


def surrender(state: dict[str, Any], actor_key: str) -> None:
    if state["over"]:
        return
    state["over"] = True
    state["winner"] = other(actor_key)
    state["reason"] = "surrender"
    _log(state, "🏳️ Сдался")


def turn_owner(state: dict[str, Any]) -> str | None:
    return None if state["over"] else state["turn"]


def side_for_user(state: dict[str, Any], user_id: int) -> str | None:
    for key in (KEY_A, KEY_B):
        if state["sides"][key]["user_id"] == user_id:
            return key
    return None
