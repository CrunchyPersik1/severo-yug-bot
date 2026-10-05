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


def render_collection(
    cards: list[Card],
    counts: dict[str, int],
    kills: dict[str, int],
    stats: dict[str, int],
    total: int,
    instances: list[dict[str, Any]] | None = None,
    cases: list[dict[str, Any]] | None = None,
) -> str:
    instances = instances or []
    cases = cases or []
    lines = [
        f"🎒 <b>Коллекция</b> — {stats['unique_cards']}/{total} карт",
        f"💰 Очки: <b>{stats['total']}</b> · всего карт: {stats['total_cards']} · "
        f"🔪 убийств: {stats['card_kills']}",
        "",
    ]
    if not cards and not instances and not cases:
        lines.append("Пока пусто. Напиши «Северо-Юг», чтобы получить первую карту.")
    for card in cards:
        count = counts.get(card.card_id, 1)
        suffix = f" ×{count}" if count > 1 else ""
        killed = kills.get(card.card_id, 0)
        kill_suffix = f" · 🔪{killed}" if killed else ""
        lines.append(
            f"{card.rarity_emoji} <code>#{card.card_id}</code> {esc(card.name)} · "
            f"⚔{card.atk}/❤{card.hp}{suffix}{kill_suffix}"
        )
    if cases:
        lines.append("")
        lines.append("📦 <b>Кейсы</b> (открыть: /case)")
        for case in cases:
            lines.append(f"      <code>#c{case['id']}</code> закрытый кейс")

    if instances:
        lines.append("")
        lines.append("⚡ <b>Улучшенные копии</b> (нельзя улучшить повторно)")
        for unit in instances:
            card = unit["card"]
            st = unit["stats"]
            tail = f"/🛡{st['def']}" if st["def"] else ""
            lines.append(
                f"{card.rarity_emoji} <code>#{unit['inventory_id']}</code> {esc(card.name)} · "
                f"⚔{st['atk']}/❤{st['hp']}{tail}"
            )
            if unit.get("items"):
                lines.append("      " + " · ".join(unit["items"]))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Рынок
# --------------------------------------------------------------------------- #


def render_unit_line(unit: dict[str, Any]) -> str:
    """Одна строка карты в списке (стак или улучшенная копия)."""
    card = unit["card"]
    st = unit["stats"]
    tail = f"/🛡{st['def']}" if st.get("def") else ""
    mark = "⚡" if unit.get("bonus") else ""
    count = f" ×{unit['count']}" if unit.get("count", 1) > 1 else ""
    return (
        f"{card.rarity_emoji} <code>{esc(unit['handle'])}</code> {mark}{esc(card.name)} · "
        f"⚔{st['atk']}/❤{st['hp']}{tail}{count}"
    )


def render_market(
    lots: list[dict[str, Any]], page: int, pages: int, total: int, balance: int
) -> tuple[str, InlineKeyboardMarkup]:
    lines = [
        "🏪 <b>Рынок карт</b>",
        f"Лотов: <b>{total}</b> · твой баланс: <b>{balance}</b> очк.",
        "",
    ]
    if not lots:
        lines.append("Лотов нет. Выставь свой: /sell #id цена")
    for lot in lots:
        seller = lot.get("first_name") or lot.get("username") or f"id{lot['seller_id']}"
        flags = " ⚠️" if lot.get("suspect") else ""
        if lot.get("kind") == "case":
            lines.append(f"<code>#{lot['id']}</code> 📦 <b>Кейс</b>{flags}")
        else:
            card = get_card(lot["card_id"])
            stats = lot.get("stats") or {"atk": card.atk, "hp": card.hp, "def": 0}
            tail = f"/🛡{stats['def']}" if stats.get("def") else ""
            lines.append(
                f"<code>#{lot['id']}</code> {card.rarity_emoji} {esc(card.name)} · "
                f"⚔{stats['atk']}/❤{stats['hp']}{tail}{flags}"
            )
        lines.append(
            f"      💰 <b>{lot['price']}</b> очк. · продавец {esc(seller)} ⭐{float(lot['rating']):.2f}"
        )

    rows: list[list[InlineKeyboardButton]] = []
    for lot in lots:
        title = "📦 Кейс" if lot.get("kind") == "case" else get_card(lot["card_id"]).name
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"#{lot['id']} {title} — {lot['price']}",
                    callback_data=f"ml:{lot['id']}",
                )
            ]
        )
    if pages > 1:
        rows.append(
            [
                InlineKeyboardButton(text="◀️", callback_data=f"mk:{max(0, page - 1)}"),
                InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop:page"),
                InlineKeyboardButton(text="▶️", callback_data=f"mk:{min(pages - 1, page + 1)}"),
            ]
        )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def render_case_lot(lot: dict[str, Any], balance: int) -> str:
    seller = lot.get("first_name") or lot.get("username") or f"id{lot['seller_id']}"
    lines = [
        "📦 <b>Кейс</b>",
        f"Лот <code>#{lot['id']}</code>",
        "",
        "Внутри — карта <b>эпической редкости и выше</b>.",
        "Может выпасть даже ультралегендарная Валерия, но шанс маленький.",
        "",
        f"💰 Цена: <b>{lot['price']}</b> очк. (рынок 5000)",
        f"🏷 Продавец: {esc(seller)} ⭐{float(lot['rating']):.2f}",
    ]
    if lot.get("suspect"):
        lines.append("⚠️ <b>Подозрительный лот</b>: цена ниже 20% рыночной")
    lines.append(f"💳 Твой баланс: <b>{balance}</b> очк.")
    return "\n".join(lines)


def render_lot(lot: dict[str, Any], viewer_id: int, balance: int) -> tuple[str, InlineKeyboardMarkup]:
    if lot.get("kind") == "case":
        text = render_case_lot(lot, balance)
        case_rows: list[list[InlineKeyboardButton]] = []
        if lot["seller_id"] == viewer_id:
            case_rows.append(
                [InlineKeyboardButton(text="❌ Снять с продажи", callback_data=f"mx:{lot['id']}")]
            )
        else:
            case_rows.append(
                [InlineKeyboardButton(text="✅ Купить", callback_data=f"mb:{lot['id']}")]
            )
        case_rows.append([InlineKeyboardButton(text="◀️ К рынку", callback_data="mk:0")])
        return text, InlineKeyboardMarkup(inline_keyboard=case_rows)

    card = get_card(lot["card_id"])
    stats = lot.get("stats") or {"atk": card.atk, "hp": card.hp, "def": 0}
    bonus = lot.get("bonus") or {}
    seller = lot.get("first_name") or lot.get("username") or f"id{lot['seller_id']}"
    reference = int(lot.get("market_price") or 0)

    lines = [
        f"🃏 <b>{esc(card.name)}</b> {card.rarity_emoji} <i>({card.rarity_title})</i>",
        f"Лот <code>#{lot['id']}</code>",
        "",
        f"⚔️ Атака: <b>{stats['atk']}</b> (база {card.atk})",
        f"❤️ HP: <b>{stats['hp']}</b> (база {card.hp})",
        f"🛡 Защита: <b>{stats['def']}%</b>",
        f"✨ Способность: {esc(card.ability.name)} (КД {card.ability.cooldown})",
    ]
    if bonus:
        lines.append("")
        lines.append("🔧 <b>Улучшения</b>")
        for slot in ("aura", "background", "effect"):
            item = lot.get(slot)
            if item:
                lines.append(f"  {item['icon']} {esc(item['name'])} — {esc(item['summary'])}")
        lines.append(f"  Итого: {esc(describe_bonus(bonus))}")
    else:
        lines.append("")
        lines.append("🔧 Улучшений нет")
    lines.append("")
    lines.append(f"💰 Цена: <b>{lot['price']}</b> очк. (рынок ~{reference})")
    lines.append(f"🏷 Продавец: {esc(seller)} ⭐{float(lot['rating']):.2f}")
    if lot.get("suspect"):
        lines.append("⚠️ <b>Подозрительный лот</b>: цена ниже 20% рыночной")
    lines.append(f"💳 Твой баланс: <b>{balance}</b> очк.")

    rows: list[list[InlineKeyboardButton]] = []
    if lot["seller_id"] == viewer_id:
        rows.append([InlineKeyboardButton(text="❌ Снять с продажи", callback_data=f"mx:{lot['id']}")])
    else:
        rows.append([InlineKeyboardButton(text="✅ Купить", callback_data=f"mb:{lot['id']}")])
    rows.append([InlineKeyboardButton(text="◀️ К рынку", callback_data="mk:0")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def render_rating_profile(profile: dict[str, Any], deals: int, gifts_sent: int) -> str:
    name = profile.get("first_name") or profile.get("username") or f"id{profile['user_id']}"
    rating = float(profile.get("rating", 5.0))
    if rating >= 4.5:
        mark = "🟢"
    elif rating >= 1.5:
        mark = "🟡"
    else:
        mark = "🔴 запрет на лоты"
    lines = [
        f"⭐ <b>Репутация: {name}</b>",
        f"{mark} <b>{rating:.2f}</b> из 10 (старт 5.00)",
        "",
        f"🤝 Сделок на рынке: <b>{deals}</b>",
        f"🎁 Подарков отправлено: {gifts_sent}",
        f"📈 Сегодня заработано репутации: {profile.get('gained_today', 0):.2f} / 1.00",
    ]
    if rating < 1.5:
        lines.append("")
        lines.append("⚠️ Репутация ниже 1.50 — выставлять лоты нельзя.")
    return "\n".join(lines)


def render_profile(profile: dict[str, Any], total_cards: int) -> str:
    name = profile.get("first_name") or profile.get("username") or f"id{profile['user_id']}"
    games = profile["wins"] + profile["losses"] + profile["draws"]
    winrate = f"{profile['wins'] * 100 // games}%" if games else "—"
    bonus = int(profile["bonus_points"])
    if bonus > 0:
        bonus_text = f" (+{bonus} из PvP)"
    elif bonus < 0:
        bonus_text = f" (−{abs(bonus)} из PvP)"
    else:
        bonus_text = ""
    return "\n".join(
        [
            f"👤 <b>{esc(name)}</b>",
            f"🏅 Место в PvP-рейтинге: <b>#{profile['rank']}</b>",
            "",
            f"⚔️ Побед: <b>{profile['wins']}</b> · поражений: {profile['losses']} · "
            f"ничьих: {profile['draws']} ({winrate})",
            f"🔪 Убито чужих карт: <b>{profile['kills']}</b>",
            f"🗡 Мои карты убили: <b>{profile['card_kills']}</b> раз",
            "",
            f"💰 Очки: <b>{profile['total']}</b>{bonus_text}",
            f"🃏 Коллекция: {profile['unique_cards']}/{total_cards} карт "
            f"(всего {profile['total_cards']})",
            "",
            "«пвп» ответом на сообщение — вызвать на бой.",
        ]
    )


def render_rating(rows: list[dict[str, Any]]) -> str:
    lines = ["🏆 <b>Рейтинг PvP</b> — по выигранным боям", ""]
    if not rows:
        lines.append("Боёв ещё не было. Вызови кого-нибудь: «пвп» ответом.")
        return "\n".join(lines)
    medals = ["🥇", "🥈", "🥉"]
    for index, row in enumerate(rows):
        name = row["first_name"] or row["username"] or f"id{row['user_id']}"
        place = medals[index] if index < 3 else f"{index + 1}."
        lines.append(
            f"{place} {esc(name)} — <b>{row['wins']}</b> побед "
            f"({row['losses']} пор., {row['draws']} ничьих) · 🔪 {row['kills']}"
        )
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
            f"{marker}<b>{esc(side.get('name') or side['user_id'])}</b> — {esc(card.name)} "
            f"⚔{side.get('atk', card.atk)}"
            + (f" 🛡{side['def']}%" if side.get("def") else "")
            + "\n"
            f"{marker}{hp_bar(side['hp'], side['max_hp'])} {max(0, side['hp'])}/{side['max_hp']}"
            + (f"  {badges}" if badges else "")
        )

    lines = [f"⚔️ <b>Бой</b> <code>{esc(battle_id)}</code>", "", block(KEY_A, a), "", block(KEY_B, b), ""]

    if state["over"]:
        winner_key = state.get("winner")
        if not winner_key:
            lines.append("❌ Бой отменён")
        elif winner_key == "draw":
            lines.append("🤝 <b>Ничья</b> — очки остаются у владельцев")
        else:
            winner = sides[winner_key]
            lines.append(f"🏆 Победил <b>{esc(winner.get('name') or winner['user_id'])}</b>")
            reward = state.get("reward") or {}
            if reward.get("amount"):
                loser_card = get_card(reward["loser_card"])
                lines.append(
                    f"💰 <b>{reward['amount']}</b> очков перешли победителю "
                    f"(5% от карты «{esc(loser_card.name)}»)"
                )
            lines.append("🔪 +1 убийство карты победителя")
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
    units: list[dict[str, Any]],
    page: int,
    per_page: int,
    bot_side: str,
    opponent_name: str,
    picked: str | None,
) -> tuple[str, InlineKeyboardMarkup]:
    """units: [{'handle', 'card', 'count', 'bonus', 'stats'}]"""
    pages = max(1, (len(units) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    chunk = units[page * per_page : (page + 1) * per_page]

    lines = [
        f"🃏 <b>Выбор карты</b> — бой <code>{esc(battle_id)}</code>",
        f"Соперник: <b>{esc(opponent_name)}</b>",
        "",
    ]
    if picked:
        lines.append(f"Твой выбор: <b>{esc(picked)}</b>. Ждём соперника…")
    else:
        lines.append(
            "Жми на карту — её характеристики и способность решают бой. ⚡ — улучшенная копия."
        )

    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for unit in chunk:
        card = unit["card"]
        stats = unit["stats"]
        mark = "⚡" if unit.get("bonus") else ""
        label = f"{mark}{card.name} ⚔{stats['atk']}/❤{stats['hp']}"
        if stats.get("def"):
            label += f"/🛡{stats['def']}"
        if unit.get("count", 1) > 1:
            label += f" ×{unit['count']}"
        pair.append(
            InlineKeyboardButton(text=label, callback_data=f"pickc:{battle_id}:{unit['handle']}")
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
        "• «<b>Северо-Юг</b>» или /drop — получить карту. Одна карта в сутки, "
        "сброс в 12:00 по ЕКБ.\n"
        "• «<b>пвп</b>» или /pvp <i>ответом</i> на сообщение соперника — вызвать на бой. "
        "Каждый выбирает карту из своей коллекции, бой идёт в одном сообщении.\n"
        "• /my — коллекция, /top — счёт по очкам, /pvprating — топ боёв, "
        "/profile — профиль.\n\n"
        "🏪 <b>Рынок</b>\n"
        "• /market — лоты, /sell #id цена — выставить, /mylots — свои лоты, "
        "/changeprice id цена — переставить цену\n"
        "• /upgrade #id — улучшить карту (аура, фон или эффект — навсегда)\n"
        "• /gift #id @игрок — подарить, /rating [@игрок] — репутация\n\n"
        "За победу в PvP победитель забирает 5% очков карты проигравшего, "
        "а карта победителя получает +1 убийство.\n\n"
        f"Меня зовут @{esc(bot_name)}. В группах нужен выключенный Privacy Mode."
    )

# --------------------------------------------------------------------------- #
# Рулетка и кейсы
# --------------------------------------------------------------------------- #


def render_roulette(kind: str, value: Any, balance: int) -> str:
    if kind == "points":
        return "\n".join(
            [
                "🎰 <b>Рулетка</b>",
                "",
                f"💰 Выпало <b>{value}</b> очков!",
                f"💳 Твой баланс: <b>{balance}</b>",
                "",
                "Следующий спин — после 20:00 по ЕКБ.",
            ]
        )
    if kind == "case":
        return "\n".join(
            [
                "🎰 <b>Рулетка</b>",
                "",
                "📦 Выпал <b>кейс</b>!",
                "Внутри карта эпической редкости и выше — вплоть до ультралегендарной.",
                "",
                "Открыть: /case. Или продать на рынке за 5000.",
                "",
                "Следующий спин — после 20:00 по ЕКБ.",
            ]
        )
    card = get_card(value)
    return "\n".join(
        [
            "🎰🎰🎰 <b>ДЖЕКПОТ!</b> 🎰🎰🎰",
            "",
            f"🏆 Главный приз рулетки — {card_title(card)}",
            f"⚔️ {card.atk} · ❤️ {card.hp} · 💰 {card.points}",
            f"✨ {esc(card.ability.name)}: {describe_ability(card)}",
            "",
            "Следующий спин — после 20:00 по ЕКБ.",
        ]
    )


def render_case_open(card: Card, is_new: bool, count: int, cases_left: int) -> str:
    tail = (
        "🆕 Новая карта в коллекции!"
        if is_new
        else f"🔁 Дубликат, теперь у тебя их <b>{count}</b>"
    )
    lines = [
        "📦 <b>Кейс открыт</b>",
        "",
        card_title(card),
        f"⚔️ Урон: <b>{card.atk}</b> · ❤️ HP: <b>{card.hp}</b> · 💰 {card.points}",
        f"✨ <b>{esc(card.ability.name)}</b> (КД {card.ability.cooldown}): {describe_ability(card)}",
        "",
        tail,
    ]
    if cases_left:
        lines.append(f"Осталось кейсов: <b>{cases_left}</b> — /case")
    return "\n".join(lines)


def render_sell_case(lot: dict[str, Any], ratio: float, penalty: float, rating: float) -> str:
    lines = [
        f"✅ Лот <code>#{lot['id']}</code> выставлен",
        f"📦 <b>Кейс</b> за <b>{lot['price']}</b> очк.",
        f"Рыночная цена 5000 — это {ratio * 100:.0f}%",
    ]
    if penalty:
        lines.append(f"⚠️ Слишком дешёво: репутация {penalty:+.1f} → {rating:.2f}")
    if lot.get("suspect"):
        lines.append("🚩 Лот помечен как подозрительный.")
    lines.append(f"Изменить цену: <code>/changeprice {lot['id']} новая_цена</code>")
    return "\n".join(lines)
