"""Формирование текстов и инлайн-клавиатур. Только представление, без логики."""

from __future__ import annotations

import html
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .battle import ACTION_ABILITY, ACTION_HIT, KEY_A, KEY_B, can_use_ability, other
from .cards import RARITIES, Card, get_card

FLEE = "🏳️ Сдаться"

_ABILITY_TEXT = {
    "damage": "урон {v}",
    "hits": "×{v} удара",
    "ignore_shield": "сквозь щит",
    "steal": "крадёт {v} HP",
    "heal": "лечит {v}",
    "shield": "щит {v}",
    "poison": "яд {v}",
    "poison_turns": "на {v} х.",
    "stun": "оглушение {v} х.",
    "silence": "немота {v} х.",
    "dodge": "уклонение ×{v}",
    "counter": "контрудар {v}",
    "counter_turns": "{v} х.",
    "weaken": "−{v} к урону врага",
    "weaken_turns": "на {v} х.",
    "cleanse": "снимает дебаффы",
    "self_stun": "свой ход пропущен",
}

_ORDER = [
    "heal", "shield", "damage", "hits", "ignore_shield", "steal", "poison",
    "poison_turns", "stun", "silence", "dodge", "counter", "counter_turns",
    "weaken", "weaken_turns", "cleanse", "self_stun",
]


def esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def describe_ability(card: Card) -> str:
    parts: list[str] = []
    for key in _ORDER:
        if key in card.ability.effects and key in _ABILITY_TEXT:
            parts.append(_ABILITY_TEXT[key].format(v=card.ability.effects[key]))
    return ", ".join(parts)


def hp_bar(hp: int, max_hp: int, width: int = 10) -> str:
    hp = max(0, min(hp, max_hp))
    filled = int(round(width * hp / max_hp)) if max_hp else 0
    filled = max(0, min(width, filled))
    return "▰" * filled + "▱" * (width - filled)


def status_badges(side: dict[str, Any]) -> str:
    badges: list[str] = []
    if side["shield"] > 0:
        badges.append(f"🛡{side['shield']}")
    if side["poison_turns"] > 0:
        badges.append(f"☠{side['poison']}({side['poison_turns']})")
    if side["stun"] > 0:
        badges.append(f"💫{side['stun']}")
    if side["dodge"] > 0:
        badges.append(f"🌀{side['dodge']}")
    if side["counter_turns"] > 0:
        badges.append(f"↩{side['counter']}")
    if side["weaken_turns"] > 0:
        badges.append(f"🔻{side['weaken']}")
    if side["silence"] > 0:
        badges.append(f"🔇{side['silence']}")
    return " ".join(badges)


def card_title(card: Card) -> str:
    return f"{card.rarity_emoji} <b>{esc(card.name)}</b> <i>({card.rarity_title})</i>"


def render_drop(card: Card, count: int, is_new: bool) -> str:
    head = "🎴 <b>Северо-Юг</b>"
    if card.rarity in {"secret", "ultra", "legendary"}:
        head = "🌟 <b>СЕВЕРО-ЮГ</b> 🌟"
    tail = (
        "🆕 Новая карта в коллекции!"
        if is_new
        else f"🔁 Дубликат, теперь у тебя их <b>{count}</b>"
    )
    return (
        f"{head}\n\n"
        f"{card_title(card)}\n"
        f"⚔️ Урон: <b>{card.atk}</b> · ❤️ HP: <b>{card.hp}</b> · 💰 {card.points}\n"
        f"✨ <b>{esc(card.ability.name)}</b> (КД {card.ability.cooldown}): {describe_ability(card)}\n\n"
        f"{tail}\n"
        f"Следующее выпадание — после 12:00 ЕКБ."
    )


def render_collection(cards: list[Card], counts: dict[str, int], stats: dict[str, int], total: int) -> str:
    lines = [
        f"🎒 <b>Коллекция</b> — {stats['unique_cards']}/{total} карт",
        f"💰 Очки: <b>{stats['points']}</b> · всего карт: {stats['total_cards']}",
        "",
    ]
    if not cards:
        lines.append("Пока пусто. Напиши «Северо-Юг», чтобы получить первую карту.")
    for card in cards:
        count = counts.get(card.card_id, 1)
        suffix = f" ×{count}" if count > 1 else ""
        lines.append(f"{card.rarity_emoji} {esc(card.name)} · ⚔{card.atk}/❤{card.hp}{suffix}")
    return "\n".join(lines)


def render_battle(battle: dict[str, Any], state: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    battle_id = battle["battle_id"]
    sides = state["sides"]
    a, b = sides[KEY_A], sides[KEY_B]

    def block(key: str, side: dict[str, Any]) -> str:
        card = get_card(side["card_id"])
        marker = "👉 " if (not state["over"] and state["turn"] == key) else "   "
        badges = status_badges(side)
        return (
            f"{marker}<b>{esc(side.get('name') or side['user_id'])}</b> — {esc(card.name)} ⚔{card.atk}\n"
            f"{marker}{hp_bar(side['hp'], side['max_hp'])} {max(0, side['hp'])}/{side['max_hp']}"
            + (f"  {badges}" if badges else "")
        )

    lines = [f"⚔️ <b>Бой</b> <code>{esc(battle_id)}</code>", "", block(KEY_A, a), "", block(KEY_B, b), ""]

    if state["over"]:
        if state["winner"] == "draw":
            lines.append("🤝 <b>Ничья</b>")
        else:
            winner = sides[state["winner"]]
            lines.append(f"🏆 Победил <b>{esc(winner.get('name') or winner['user_id'])}</b>")
    else:
        turn_side = sides[state["turn"]]
        lines.append(
            f"Ход {state['turn_no']}/30 · ходит <b>{esc(turn_side.get('name') or turn_side['user_id'])}</b>"
        )

    tail = state["log"][-4:]
    if tail:
        lines.append("")
        lines.extend(f"· {esc(item)}" for item in tail)

    rows: list[list[InlineKeyboardButton]] = []
    if not state["over"]:
        current = state["turn"]
        side = sides[current]
        card = get_card(side["card_id"])
        ability_label = f"✨ {card.ability.name}"
        if side["silence"] > 0:
            ability_label += " · 🔇"
        elif side["cd"] > 0:
            ability_label += f" · КД {side['cd']}"
        rows.append(
            [
                InlineKeyboardButton(text=f"⚔️ Удар ({card.atk})", callback_data=f"b:{battle_id}:{ACTION_HIT}"),
                InlineKeyboardButton(text=ability_label, callback_data=f"b:{battle_id}:{ACTION_ABILITY}"),
            ]
        )
        rows.append([InlineKeyboardButton(text=FLEE, callback_data=f"b:{battle_id}:flee")])
    else:
        rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"b:{battle_id}:noop")])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def render_pick(
    battle_id: str,
    cards: list[Card],
    counts: dict[str, int],
    page: int,
    per_page: int,
    bot_side: str,
    opponent_name: str,
    picked: str | None,
) -> tuple[str, InlineKeyboardMarkup]:
    pages = max(1, (len(cards) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    chunk = cards[page * per_page : (page + 1) * per_page]

    lines = [
        f"🃏 <b>Выбор карты</b> — бой <code>{esc(battle_id)}</code>",
        f"Соперник: <b>{esc(opponent_name)}</b>",
        "",
    ]
    if picked:
        lines.append(f"Твой выбор: <b>{esc(get_card(picked).name)}</b>. Ждём соперника…")
    else:
        lines.append("Жми на карту — её характеристики и способность решают бой.")

    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for card in chunk:
        label = f"{card.name} ⚔{card.atk}/❤{card.hp}"
        if counts.get(card.card_id, 1) > 1:
            label += f" ×{counts[card.card_id]}"
        pair.append(
            InlineKeyboardButton(text=label, callback_data=f"pickc:{battle_id}:{card.card_id}")
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    if pages > 1:
        rows.append(
            [
                InlineKeyboardButton(text="◀️", callback_data=f"pick:{battle_id}:{max(0, page - 1)}"),
                InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop:page"),
                InlineKeyboardButton(text="▶️", callback_data=f"pick:{battle_id}:{min(pages - 1, page + 1)}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="❌ Отменить бой", callback_data=f"b:{battle_id}:flee")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def render_help(bot_name: str) -> str:
    return (
        "🎴 <b>Северо-Юг</b> — коллекционные карточки и PvP.\n\n"
        "• «<b>Северо-Юг</b>» (регистр не важен) — получить карту. Одна карта в сутки, "
        "сброс в 12:00 по ЕКБ.\n"
        "• «<b>пвп</b>» <i>ответом</i> на сообщение соперника — вызвать его на бой. "
        "Каждый выбирает карту из своей коллекции, бой идёт в одном сообщении.\n"
        "• /my — коллекция, /top — лидерборд.\n\n"
        f"Меня зовут @{esc(bot_name)}. В группах нужен выключенный Privacy Mode."
    )
