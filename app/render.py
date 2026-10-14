"""Формирование текстов и инлайн-клавиатур. Только представление, без логики."""

from __future__ import annotations

import html
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .battle import ACTION_ABILITY, ACTION_HIT, KEY_A, KEY_B
from . import boss, casino, dice_casino, team_battle
from .battle import ability_targets
from .cards import (
    CARDS,
    CARDS_BY_ID,
    RARITIES,
    RARITY_ORDER,
    Card,
    cards_sorted_for_user,
    get_card,
)
from . import levels, titles
from .cases import CASE_RARITY_ORDER, CASE_RARITY_WEIGHTS
from .team_battle import TEAM_BLUE, TEAM_RED
from .items import (
    AURAS,
    BACKGROUNDS,
    BY_SLOT,
    EFFECTS,
    SLOTS,
    SLOT_AURA,
    SLOT_ICONS,
    SLOT_TITLES,
)
from .market import (
    RARITY_COEF,
    UPGRADE_MULT_MIN,
    UPGRADE_PRICE,
    describe_bonus,
    market_price,
    rarity_coef,
    upgrade_multiplier,
)

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
    "confuse": "смута {v} х.",
    "dodge": "уклонение ×{v}",
    "counter": "контрудар {v}",
    "counter_turns": "{v} х.",
    "weaken": "−{v} к урону врага",
    "weaken_turns": "на {v} х.",
    "cleanse": "снимает дебаффы",
    "self_stun": "свой ход пропущен",
    "drain": "утечка {v} HP в ход (пока жив)",
}

_ORDER = [
    "heal", "shield", "damage", "hits", "ignore_shield", "steal", "poison",
    "poison_turns", "stun", "silence", "confuse", "dodge", "counter",
    "counter_turns",
    "weaken", "weaken_turns", "cleanse", "self_stun", "drain",
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
    if side.get("confuse", 0) > 0:
        badges.append(f"❓{side['confuse']}")
    return " ".join(badges)


def card_title(card: Card) -> str:
    return f"{card.rarity_emoji} <b>{esc(card.display_name)}</b> <i>({card.rarity_title})</i>"


def render_drop(card: Card, count: int, is_new: bool) -> str:
    head = "🎴 <b>Северо-Юг</b>"
    if card.rarity in {"secret", "ultra", "legendary"}:
        head = "🌟 <b>СЕВЕРО-ЮГ</b> 🌟"
    tail = (
        "🆕 Новая карта в коллекции!"
        if is_new
        else f"🔁 Дубликат, теперь у тебя их <b>{count}</b>"
    )
    desc = f"<i>{esc(card.description)}</i>\n" if card.description else ""
    return (
        f"{head}\n\n"
        f"{card_title(card)}\n"
        f"{desc}"
        f"⚔️ Урон: <b>{card.atk}</b> · ❤️ HP: <b>{card.hp}</b> · 💰 {card.points}\n"
        f"✨ <b>{esc(card.ability.name)}</b> (КД {card.ability.cooldown}): {describe_ability(card)}\n\n"
        f"💰 <b>+{card.points}</b> очков на баланс\n"
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
        f"💰 Баланс: <b>{stats['total']}</b> очк. · коллекция на {stats['points']} · "
        f"всего карт: {stats['total_cards']} · 🔪 убийств: {stats['card_kills']}",
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
            f"{card.rarity_emoji} <code>#{card.card_id}</code> {esc(card.display_name)} · "
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
                f"{card.rarity_emoji} <code>#{unit['inventory_id']}</code> {esc(card.display_name)} · "
                f"⚔{st['atk']}/❤{st['hp']}{tail}"
            )
            if unit.get("items"):
                lines.append("      " + " · ".join(unit["items"]))
            won_in_casino = unit.get("casino_bonus") or {}
            if won_in_casino:
                lines.append("      🎰 казино: " + casino.describe_bonus(won_in_casino))
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
        f"{card.rarity_emoji} <code>{esc(unit['handle'])}</code> {mark}{esc(card.display_name)} · "
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
                f"<code>#{lot['id']}</code> {card.rarity_emoji} {esc(card.display_name)} · "
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
        f"🃏 <b>{esc(card.display_name)}</b> {card.rarity_emoji} <i>({card.rarity_title})</i>",
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
    # Баланс — это и есть очки игрока: карты начисляют их при выпадении,
    # PvP и рынок перекладывают между игроками.
    bonus_text = " (в минусе)" if bonus < 0 else ""
    title = titles.title_for(profile)
    points, _current, nxt = titles.progress(profile)
    level, inside, need = levels.progress(profile.get("xp") or 0)

    lines = [
        f"👤 <b>{esc(name)}</b>",
        f"⭐ Уровень: <b>{level}</b>/100"
        + (f" · {inside}/{need} XP" if need else " · максимум"),
        f"🏅 Титул: <b>{title}</b> · вклад {points}",
        f"🏆 Место в PvP-рейтинге: <b>#{profile['rank']}</b>",
        "",
        f"⚔️ Побед: <b>{profile['wins']}</b> · поражений: {profile['losses']} · "
        f"ничьих: {profile['draws']} ({winrate})",
        f"🔪 Убито чужих карт: <b>{profile['kills']}</b>",
        f"🗡 Мои карты убили: <b>{profile['card_kills']}</b> раз",
        "",
        f"💰 Баланс: <b>{profile['total']}</b> очк.{bonus_text}",
        f"🃏 Коллекция: {profile['unique_cards']}/{total_cards} карт "
        f"(всего {profile['total_cards']}, стоимость {profile['card_points']})",
        f"⚡ Улучшенных копий: <b>{profile.get('upgraded', 0)}</b>",
        "",
        _favorite_line(profile),
        "",
        "📊 <b>Чем занимался</b>",
        f"🎴 Выпадений: <b>{profile.get('drops', 0)}</b> · "
        f"🎲 ставок в казино: <b>{profile.get('casino_bets', 0)}</b>",
        f"🛒 Покупок: <b>{profile.get('shop_buys', 0)}</b> · "
        f"🏪 сделок на рынке: <b>{profile.get('market_deals', 0)}</b>",
        f"🎁 Подарков: <b>{profile.get('gifts_sent', 0)}</b> · "
        f"🔗 друзей приглашено: <b>{profile.get('invited', 0)}</b>",
    ]
    if nxt:
        lines += ["", f"До титула выше: ещё {nxt - points} очк. вклада."]
    else:
        lines += ["", "Максимальный титул — выше некуда!"]
    lines += ["", "«пвп» ответом на сообщение — вызвать на бой."]
    return "\n".join(lines)


def _plural(count: int, one: str, few: str, many: str) -> str:
    number = abs(int(count)) % 100
    if 11 <= number <= 14:
        return many
    number %= 10
    if number == 1:
        return one
    if 2 <= number <= 4:
        return few
    return many


def _favorite_line(profile: dict[str, Any]) -> str:
    card_id = profile.get("favorite_card_id")
    card = CARDS_BY_ID.get(card_id) if card_id else None
    if card is None:
        return "❤️ Любимая карта: пока нет — выбей первую «Северо-Юг»."
    kills = int(profile.get("favorite_kills") or 0)
    copies = int(profile.get("favorite_copies") or 0)
    details = []
    if kills:
        details.append(f"{kills} {_plural(kills, 'убийство', 'убийства', 'убийств')}")
    if copies > 1:
        details.append(f"{copies} {_plural(copies, 'копия', 'копии', 'копий')}")
    tail = " — " + ", ".join(details) if details else ""
    return (
        f"❤️ Любимая карта: {card.rarity_emoji} <b>{esc(card.display_name)}</b>"
        f"{tail}"
    )


def profile_keyboard(user_id: int, is_owner: bool = False) -> InlineKeyboardMarkup:
    """У владельца — кнопка ведёт в новое меню /my, у чужих — на их карты."""
    if is_owner:
        button = InlineKeyboardButton(text="🃏 Мои карты", callback_data="my:c:0")
    else:
        button = InlineKeyboardButton(
            text="🃏 Карты игрока", callback_data=f"pf:{user_id}:cards"
        )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def collection_keyboard(user_id: int, units: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """Кнопка на каждую карту из профиля."""
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for unit in units:
        card = unit["card"]
        mark = "⚡" if unit.get("bonus") else ""
        label = f"{mark}{card.name} ⚔{unit['stats']['atk']}/❤{unit['stats']['hp']}"
        if unit.get("count", 1) > 1:
            label += f" ×{unit['count']}"
        pair.append(
            InlineKeyboardButton(
                text=label, callback_data=f"pf:{user_id}:card:{unit['handle']}"
            )
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append(
        [InlineKeyboardButton(text="⬅️ Назад в профиль", callback_data=f"pf:{user_id}:back")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def render_card_detail(
    unit: dict[str, Any], user_id: int, is_owner: bool = True
) -> tuple[str, InlineKeyboardMarkup]:
    card = unit["card"]
    stats = unit.get("stats") or {"atk": card.atk, "hp": card.hp, "def": 0}
    bonus = unit.get("bonus") or {}
    title = "⚡ улучшенная копия" if bonus else "обычная копия"
    lines = [card_title(card)]
    if card.description:
        lines.append(f"<i>{esc(card.description)}</i>")
    lines += [
        f"<code>{esc(unit['handle'])}</code> — {title}",
        "",
        f"⚔️ Атака: <b>{stats['atk']}</b> (база {card.atk})",
        f"❤️ HP: <b>{stats['hp']}</b> (база {card.hp})",
        f"🛡 Защита: <b>{stats['def']}%</b>",
        f"✨ <b>{esc(card.ability.name)}</b> (КД {card.ability.cooldown}): {describe_ability(card)}",
    ]
    lines += [
        f"💰 Стоимость карты: {card.points}",
        f"🔪 Убийств этой картой: {unit.get('kills', 0)}",
    ]
    if unit.get("count", 1) > 1:
        lines.append(f"📚 В стаке: {unit['count']} шт.")
    if unit.get("items"):
        lines.append("")
        lines.append("🔧 <b>Улучшения</b>")
        lines.extend(f"   {item}" for item in unit["items"])
    elif bonus:
        lines.append("")
        lines.append(f"🔧 Итого: {esc(describe_bonus(bonus))}")
    if is_owner:
        lines.append("")
        lines.append(f"Продать: <code>/sell {unit['handle']} цена</code>")
        if not bonus:
            lines.append(f"Улучшить: <code>/upgrade {unit['handle']}</code>")
    else:
        lines.append("")
        lines.append("<i>Это чужая карта — только просмотр.</i>")
    back_text = "⬅️ К моим картам" if is_owner else "⬅️ К картам игрока"
    back_callback = "my:c:0" if is_owner else f"pf:{user_id}:cards"
    return (
        "\n".join(lines),
        InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=back_text, callback_data=back_callback)]
            ]
        ),
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
            f"{marker}<b>{esc(side.get('name') or side['user_id'])}</b> — {esc(card.display_name)} "
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
                    f"(5% от карты «{esc(loser_card.display_name)}»)"
                )
            lines.append("🔪 +1 убийство карты победителя")
    else:
        turn_side = sides[state["turn"]]
        lines.append(
            f"Ход {state['turn_no']} · ходит "
            f"<b>{esc(turn_side.get('name') or turn_side['user_id'])}</b>"
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
        label = f"{mark}{card.display_name} ⚔{stats['atk']}/❤{stats['hp']}"
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
        "/profile [@игрок] — профиль и карты: свой или чужой.\n\n"
        "🏪 <b>Рынок</b>\n"
        "• /market — лоты, /sell #id цена — выставить, /mylots — свои лоты, "
        "/changeprice id цена — переставить цену\n"
        f"• /upgrade #id — улучшить карту за {UPGRADE_PRICE} очков: сразу аура, фон и эффект\n"
        "• /gift #id @игрок — подарить, /rating [@игрок] — репутация\n\n"
        "За победу в PvP победитель забирает 5% очков карты проигравшего, "
        "а карта победителя получает +1 убийство.\n\n"
        f"Меня зовут @{esc(bot_name)}. В группах нужен выключенный Privacy Mode."
    )

# --------------------------------------------------------------------------- #
# Рулетка и кейсы
# --------------------------------------------------------------------------- #


def render_upgrade(
    card: Card, items: dict[str, Any], balance: int, inventory_id: int
) -> str:
    lines = [
        f"⚡ <b>{esc(card.display_name)}</b> улучшена — копия <code>#{inventory_id}</code>",
        f"💸 Списано <b>{UPGRADE_PRICE}</b> очк. · осталось <b>{balance}</b>",
        "",
    ]
    for slot in ("aura", "background", "effect"):
        item = items.get(slot)
        if item is not None:
            lines.append(f"{SLOT_ICONS[slot]} <b>{esc(item.name)}</b> — {esc(item.summary)}")
    lines.append("")
    lines.append("Все три части выдаются сразу и навсегда — перебить нельзя.")
    return "\n".join(lines)


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
            f"💰 <b>+{card.points}</b> очков на баланс",
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
    lines = ["📦 <b>Кейс открыт</b>", "", card_title(card)]
    if card.description:
        lines.append(f"<i>{esc(card.description)}</i>")
    lines.append(f"⚔️ Урон: <b>{card.atk}</b> · ❤️ HP: <b>{card.hp}</b> · 💰 {card.points}")
    lines.append(
        f"✨ <b>{esc(card.ability.name)}</b> (КД {card.ability.cooldown}): {describe_ability(card)}"
    )
    lines += [f"💰 <b>+{card.points}</b> очков на баланс", "", tail]
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

# --------------------------------------------------------------------------- #
# Казино
# --------------------------------------------------------------------------- #


def render_casino_help(balance: int, left: int = 0, cap: int = 25) -> str:
    return "\n".join(
        [
            "🎰 <b>Казино</b>",
            "",
            f"Твой баланс: <b>{balance}</b> очков.",
            f"🎟 Круток на сегодня: <b>{left}</b> из {cap}",
            "Докупить одну — 2 000 очков (кнопка ниже).",
            "",
            "Ставь очки или карту и выбирай цвет:",
            "🔴 красное и ⚫ чёрное — <b>x2</b>",
            "🟢 зелёное — <b>x5</b> (выпадает примерно 1 раз на 50)",
            "",
            "Ставка очками: <code>/casino 1000</code>",
            "Ставка картой: <code>/casino #oleg</code> или <code>/casino #12</code>",
            "",
            "🎲 <b>Быстрые игры</b> (плюс к тем же 25 круткам):",
            "<code>/casino кости 10000</code> — чёт/нечёт ×2, угадаешь цифру ×3",
            "<code>/casino футбол 10000</code> и <code>/casino баскет 10000</code> — "
            "попадёт/не попадёт ×2",
            "",
            "Проигрыш: очки возвращаются только на треть, карта либо уничтожается (20%), "
            "либо теряет статы (80%). Редкую карту можно выкупить за двойную цену.",
            "",
            "📊 Свои итоги (и чужие): <code>/casinostats</code> или "
            "<code>/casinostats @игрок</code>",
            "",
            # пасхалка: код на очки
            "🍖 Промокод: <code>mishakotletka</code>",
        ]
    )


def render_casino_colors(bet_label: str, token: str) -> tuple[str, InlineKeyboardMarkup]:
    text = "\n".join(["🎰 <b>Ставка принята</b>", "", f"Ставим: {bet_label}", "", "На какой цвет?"])
    rows = [
        [InlineKeyboardButton(text="🔴 Красное x2", callback_data=f"cs:{token}:red")],
        [InlineKeyboardButton(text="⚫ Чёрное x2", callback_data=f"cs:{token}:black")],
        [InlineKeyboardButton(text="🟢 Зелёное x5", callback_data=f"cs:{token}:green")],
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def render_casino_result(
    result: dict[str, Any], balance: int
) -> tuple[str, InlineKeyboardMarkup]:
    rolled = casino.color_title(result["rolled"])
    bet_label = casino.color_title(result["color"])
    lines = [f"🎰 Выпало: <b>{rolled}</b> (ставил на {bet_label})", ""]

    if result["kind"] == "points":
        if result["won"]:
            lines += [
                f"🎉 <b>Победа!</b> Ставка {result['bet']} → <b>{result['payout']}</b> очков.",
                f"Чистыми: <b>+{result['delta']}</b>",
            ]
        else:
            lines += [
                f"💀 <b>Проигрыш.</b> Из {result['bet']} вернулась только треть: "
                f"<b>{result['payout']}</b>.",
                f"Чистыми: <b>{result['delta']}</b>",
            ]
        lines.append(f"💳 Баланс: <b>{balance}</b>")
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[])

    card = result["card"]
    if result["won"]:
        head = (
            "🟢🟢🟢 <b>ДЖЕКПОТ!</b> Карта улучшена до максимума:"
            if result["outcome"] == "max"
            else "🎉 <b>Победа!</b> Карта улучшена:"
        )
        lines += [head, f"   {casino.describe_bonus(result['bonus'])}"]
    elif result["outcome"] == "delete":
        lines += [
            "💀 <b>Проигрыш. Карта уничтожена.</b>",
            f"{card.rarity_emoji} <b>{esc(card.display_name)}</b> ({card.rarity_title})",
        ]
    else:
        lines += [
            "💀 <b>Проигрыш.</b> Карта потеряла часть статов:",
            f"   {casino.describe_bonus(result['bonus'])}",
        ]

    rows: list[list[InlineKeyboardButton]] = []
    if result.get("offer_id"):
        rows.append(
            [
                InlineKeyboardButton(
                    text="💸 Выкупить карту", callback_data=f"csb:{result['offer_id']}"
                )
            ]
        )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def render_dice_choices(
    game: str, bet_label: str, token: str
) -> tuple[str, InlineKeyboardMarkup]:
    """Экран выбора для костей/футбола/баскета."""
    lines = [
        f"{dice_casino.emoji(game)} <b>{dice_casino.title(game)}</b>",
        "",
        f"Ставка: {bet_label}",
        "",
        "Твой выбор:",
    ]
    rows: list[list[InlineKeyboardButton]] = []
    if game == dice_casino.GAME_DICE:
        lines.append("Чёт/нечёт — ×2, точная цифра — ×3.")
        rows.append(
            [
                InlineKeyboardButton(
                    text="Чёт ×2", callback_data=f"cg:{game}:{token}:{dice_casino.CHOICE_EVEN}"
                ),
                InlineKeyboardButton(
                    text="Нечёт ×2", callback_data=f"cg:{game}:{token}:{dice_casino.CHOICE_ODD}"
                ),
            ]
        )
        digits = [
            InlineKeyboardButton(
                text=f"{n} ×3", callback_data=f"cg:{game}:{token}:d{n}"
            )
            for n in dice_casino.digit_choices()
        ]
        rows.append(digits[:3])
        rows.append(digits[3:])
    else:
        lines.append("Угадай, попадёт или нет — ×2.")
        rows.append(
            [
                InlineKeyboardButton(
                    text="Попадёт ×2", callback_data=f"cg:{game}:{token}:{dice_casino.CHOICE_HIT}"
                ),
                InlineKeyboardButton(
                    text="Не попадёт ×2",
                    callback_data=f"cg:{game}:{token}:{dice_casino.CHOICE_MISS}",
                ),
            ]
        )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def render_dice_result(
    result: dict[str, Any], balance: int
) -> tuple[str, InlineKeyboardMarkup]:
    """Итог быстрой игры: что выпало и что стало со ставкой."""
    game = result["game"]
    lines = [
        f"{dice_casino.emoji(game)} <b>{dice_casino.title(game)}</b> — "
        f"выпало <b>{result['rolled']}</b>",
        f"Твой выбор: {dice_casino.choice_label(game, result['choice'])} "
        f"(×{result['multiplier']})",
        "",
    ]
    rows: list[list[InlineKeyboardButton]] = []

    if result["kind"] == "points":
        if result["won"]:
            lines += [
                f"🎉 <b>Победа!</b> {result['bet']} → <b>{result['payout']}</b> очков.",
                f"Чистыми: <b>+{result['delta']}</b>",
            ]
        else:
            lines += [
                f"💀 <b>Проигрыш.</b> Из {result['bet']} вернулась только треть: "
                f"<b>{result['payout']}</b>.",
                f"Чистыми: <b>{result['delta']}</b>",
            ]
        lines.append(f"💳 Баланс: <b>{balance}</b>")
        return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[])

    card = result["card"]
    if result["won"]:
        head = (
            "🌟 <b>ДЖЕКПОТ!</b> Карта улучшена до максимума:"
            if result["outcome"] == "max"
            else "🎉 <b>Победа!</b> Карта улучшена:"
        )
        lines += [head, f"   {casino.describe_bonus(result['bonus'])}"]
    elif result["outcome"] == "delete":
        lines += [
            "💀 <b>Проигрыш. Карта уничтожена.</b>",
            f"{card.rarity_emoji} <b>{esc(card.display_name)}</b> ({card.rarity_title})",
        ]
    else:
        lines += [
            "💀 <b>Проигрыш.</b> Карта потеряла часть статов:",
            f"   {casino.describe_bonus(result['bonus'])}",
        ]
    if result.get("offer_id"):
        rows.append(
            [
                InlineKeyboardButton(
                    text="💸 Выкупить карту", callback_data=f"csb:{result['offer_id']}"
                )
            ]
        )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def render_casino_bought(card: Card, price: int, balance: int, inventory_id: int) -> str:
    return "\n".join(
        [
            "💸 <b>Карта выкуплена</b>",
            "",
            f"{card.rarity_emoji} <b>{esc(card.display_name)}</b> ({card.rarity_title})",
            f"Копия <code>#{inventory_id}</code> вернулась в коллекцию.",
            f"Заплачено: <b>{price}</b> очков · осталось <b>{balance}</b>",
        ]
    )


def render_casino_stats(name: str, stats: dict[str, int]) -> str:
    """Сколько игрок поставил, вернул, выиграл и слил в казино."""
    staked = int(stats.get("staked", 0))
    returned = int(stats.get("returned", 0))
    won = int(stats.get("won_points", 0))
    lost = int(stats.get("lost_points", 0))
    net = returned - staked

    lines = [
        f"🎰 <b>Казино</b> — {esc(name)}",
        "",
        f"Ставок очками: <b>{int(stats.get('point_bets', 0))}</b>",
        f"Поставлено: <b>{_money(staked)}</b> · вернулось: <b>{_money(returned)}</b>",
        f"🟢 Выиграно: <b>+{_money(won)}</b>",
        f"🔴 Слито: <b>−{_money(lost)}</b>",
    ]
    if net > 0:
        lines.append(f"📊 Итог: <b>+{_money(net)}</b> — в плюсе")
    elif net < 0:
        lines.append(f"📊 Итог: <b>−{_money(-net)}</b> — в минусе")
    else:
        lines.append("📊 Итог: <b>0</b> — в нуле")

    card_bets = int(stats.get("card_bets", 0))
    if card_bets:
        lines += [
            "",
            f"🃏 Ставок картами: <b>{card_bets}</b> · "
            f"улучшено: {int(stats.get('card_wins', 0))} · "
            f"уничтожено: {int(stats.get('card_deleted', 0))}",
        ]
    if not int(stats.get("point_bets", 0)) and not card_bets:
        lines += ["", "Пока пусто. Крути: /casino"]
    return "\n".join(lines)

# --------------------------------------------------------------------------- #
# Командный PvP
# --------------------------------------------------------------------------- #


def render_team_pick(
    battle_id: str, units: list[dict[str, Any]], picked: int, need: int
) -> tuple[str, InlineKeyboardMarkup]:
    lines = [
        "⚔️ <b>Командный бой</b>",
        f"Выбрано карт: <b>{picked}</b> из {need}.",
        "Жми на карту — она пойдёт в бой.",
    ]
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for unit in units:
        label = f"{unit['card'].name} ⚔{unit['stats']['atk']}/❤{unit['stats']['hp']}"
        pair.append(
            InlineKeyboardButton(text=label, callback_data=f"tk:{battle_id}:{unit['handle']}")
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append(
        [InlineKeyboardButton(text="🛑 Остановить бой", callback_data=f"ts:{battle_id}")]
    )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _team_board_lines(state: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for team, title in ((TEAM_RED, "🔴 Красные"), (TEAM_BLUE, "🔵 Синие")):
        lines.append(f"<b>{title}</b>")
        for key in state["teams"].get(team, []):
            side = state["sides"][key]
            card = get_card(side["card_id"])
            if side["hp"] <= 0:
                lines.append(f"  ☠️ {esc(card.display_name)} — уничтожена")
                continue
            marks = ""
            if side.get("acted"):
                marks += " ✔"
            if side.get("shield"):
                marks += f" 🛡{side['shield']}"
            if side.get("drain"):
                marks += " 🔗"
            if side.get("poison_turns"):
                marks += f" ☠{side['poison']}"
            lines.append(
                f"  {card.rarity_emoji} {esc(card.display_name)} — "
                f"<b>{max(0, side['hp'])}</b>/{side['max_hp']}{marks} · {esc(side['name'])}"
            )
        lines.append("")
    return lines


def render_team_battle(
    battle: dict[str, Any], state: dict[str, Any], view: dict[str, Any] | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    battle_id = battle["battle_id"]
    view = view or {}
    lines = [f"⚔️ <b>Командный бой</b> <code>{esc(battle_id)}</code> · раунд {state['round']}", ""]
    lines += _team_board_lines(state)

    rows: list[list[InlineKeyboardButton]] = []
    if state.get("over"):
        winner = state.get("winner")
        if winner:
            title = "🔴 Красные" if winner == TEAM_RED else "🔵 Синие"
            lines.append(f"🏆 Победили <b>{title}</b>")
        else:
            lines.append("🤝 Ничья")
    else:
        turn = state["turn"]
        person = next(
            (p for p in state.get("participants", []) if p["user_id"] == turn), None
        )
        name = person["name"] if person else str(turn)
        unit_key = view.get("unit")
        action = view.get("action")
        target = view.get("target")

        if unit_key is None:
            lines.append(f"Ходит <b>{esc(name)}</b>. Выбери карту:")
            for key in team_battle.available(state, turn):
                side = state["sides"][key]
                card = get_card(side["card_id"])
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=f"{card.name} ❤{max(0, side['hp'])}",
                            callback_data=f"tb:{battle_id}:u:{key}",
                        )
                    ]
                )
        else:
            side = state["sides"][unit_key]
            card = get_card(side["card_id"])
            lines.append(f"Карта: <b>{esc(card.display_name)}</b>")
            if action is None:
                lines.append("Что делаем?")
                # Удар доступен всегда — КД способности его не блокирует.
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=f"⚔️ Удар ({side['atk']})",
                            callback_data=f"tb:{battle_id}:a:{unit_key}:hit",
                        )
                    ]
                )
                # Способность показываем всегда: если на КД — просто с пометкой.
                ability_label = f"✨ {card.ability.name}"
                if side["silence"] > 0:
                    ability_label += " · 🔇"
                elif side["cd"] > 0:
                    ability_label += f" · КД {side['cd']}"
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=ability_label,
                            callback_data=f"tb:{battle_id}:a:{unit_key}:ability",
                        )
                    ]
                )
                rows.append(
                    [
                        InlineKeyboardButton(
                            text="⬅️ К списку карт",
                            callback_data=f"tb:{battle_id}:c",
                        )
                    ]
                )
            else:
                need = ability_targets(card) if action == "ability" else "enemy"
                if need == "both" and target is None:
                    lines.append("Кого бьём?")
                    rows += _team_target_rows(state, battle_id, unit_key, action, team_battle, enemy=True)
                elif need == "both":
                    lines.append("Кого лечим?")
                    rows += _team_ally_rows(state, battle_id, unit_key, target, team_battle)
                elif need == "ally":
                    lines.append("Кого лечим или прикрываем?")
                    rows += _team_ally_rows(state, battle_id, unit_key, None, team_battle)
                else:
                    lines.append("Кого бьём?")
                    rows += _team_target_rows(state, battle_id, unit_key, action, team_battle, enemy=True)

    tail = state.get("log", [])[-3:]
    if tail:
        lines.append("")
        lines.extend(f"· {esc(item)}" for item in tail)
    if not state.get("over"):
        rows.append(
            [InlineKeyboardButton(text="🛑 Остановить бой", callback_data=f"ts:{battle_id}")]
        )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _team_target_rows(state, battle_id, unit_key, action, tb, enemy: bool):
    actor = state["sides"][unit_key]
    team = actor["team"]
    keys = tb.team_keys(state, tb.enemy_team(team) if enemy else team)
    rows = []
    for key in keys:
        side = state["sides"][key]
        if side["hp"] <= 0:
            continue
        card = get_card(side["card_id"])
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{card.name} ❤{max(0, side['hp'])}",
                    callback_data=f"tb:{battle_id}:t:{unit_key}:{action}:{key}",
                )
            ]
        )
    return rows


def _team_ally_rows(state, battle_id, unit_key, target_key, tb):
    actor = state["sides"][unit_key]
    rows = []
    for key in tb.team_keys(state, actor["team"]):
        side = state["sides"][key]
        if side["hp"] <= 0:
            continue
        card = get_card(side["card_id"])
        suffix = " · себя" if key == unit_key else ""
        callback = (
            f"tb:{battle_id}:y:{unit_key}:{target_key}:{key}"
            if target_key
            else f"tb:{battle_id}:t:{unit_key}:ability:{key}"
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{card.name} ❤{max(0, side['hp'])}{suffix}",
                    callback_data=callback,
                )
            ]
        )
    return rows

# --------------------------------------------------------------------------- #
# FAQ
# --------------------------------------------------------------------------- #

FAQ_PAGE_SIZE = 6


def _money(value: int) -> str:
    return f"{int(value):,}".replace(",", " ")


def _ability_line(card: Card) -> str:
    effects = card.ability.effects
    parts: list[str] = []
    if "damage" in effects:
        parts.append(f"урон {effects['damage']}")
    if effects.get("hits"):
        parts.append(f"×{effects['hits']} удара")
    if "steal" in effects:
        parts.append(f"отжимает {effects['steal']} HP")
    if "heal" in effects:
        parts.append(f"лечит {effects['heal']}")
    if "shield" in effects:
        parts.append(f"щит +{effects['shield']}")
    if "poison" in effects:
        turns = effects.get("poison_turns", 2)
        parts.append(f"яд {effects['poison']} на {turns} хода")
    if "drain" in effects:
        parts.append(f"утечка {effects['drain']} HP в ход")
    if "stun" in effects:
        parts.append("оглушение")
    if "silence" in effects:
        parts.append("немота")
    if "weaken" in effects:
        parts.append("ослабление")
    if "counter" in effects:
        parts.append(f"контрудар {effects['counter']}")
    if "dodge" in effects:
        parts.append(f"уклонение ×{effects['dodge']}")
    if effects.get("cleanse"):
        parts.append("снимает дебаффы")
    if effects.get("self_stun"):
        parts.append("свой ход пропущен")
    if effects.get("ignore_shield"):
        parts.append("пробивает щит")
    return ", ".join(parts) or "без эффектов"


def _rarity_list() -> list[str]:
    sample: dict[str, Card] = {}
    for card in CARDS:
        sample.setdefault(card.rarity, card)
    out = []
    for rarity, coef in sorted(RARITY_COEF.items(), key=lambda pair: pair[1]):
        card = sample.get(rarity)
        emoji = card.rarity_emoji if card else "▫️"
        title = card.rarity_title if card else rarity
        out.append(f"  {emoji} {title} — ×{coef:g}")
    return out


def faq_menu() -> tuple[str, InlineKeyboardMarkup]:
    lines = [
        "📖 <b>FAQ</b>",
        "",
        "Самое частое: цены, статы, способности, шансы выпадения и множители.",
    ]
    rows = [
        [InlineKeyboardButton(text="🃏 Персонажи и цены", callback_data="fq:cards:0")],
        [InlineKeyboardButton(text="🎲 Шансы выпадения", callback_data="fq:drop")],
        [InlineKeyboardButton(text="🎨 Ауры, фоны, эффекты", callback_data="fq:items:aura")],
        [InlineKeyboardButton(text="🧮 Как считается цена", callback_data="fq:price")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def faq_drops() -> tuple[str, InlineKeyboardMarkup]:
    """Проценты выпадения по редкостям: и «Северо-Юг», и кейс."""
    lines = [
        "🎲 <b>Шансы выпадения</b>",
        "",
        "🎴 <b>Крутка «Северо-Юг»</b> (и рулетка-карта):",
    ]
    for key in RARITY_ORDER:
        rarity = RARITIES[key]
        chance = rarity.weight * 100
        tail = f" · ≈1 из {round(100 / chance)}" if chance < 10 else ""
        lines.append(f"   {rarity.emoji} {rarity.name} — <b>{chance:.2f}%</b>{tail}")

    lines += ["", "📦 <b>Кейс</b> (ниже эпической не выпадает):"]
    for key in CASE_RARITY_ORDER:
        rarity = RARITIES[key]
        chance = CASE_RARITY_WEIGHTS[key] * 100
        tail = f" · ≈1 из {round(100 / chance)}" if chance < 10 else ""
        lines.append(f"   {rarity.emoji} {rarity.name} — <b>{chance:.0f}%</b>{tail}")

    lines += [
        "",
        "Внутри редкости все карты равновероятны.",
        "«Эльмира Ракидовна» выпадает только за промокод, в этих шансах её нет.",
    ]
    rows = [
        [InlineKeyboardButton(text="🃏 Персонажи и цены", callback_data="fq:cards:0")],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="fq:menu")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def faq_cards(page: int = 0) -> tuple[str, InlineKeyboardMarkup]:
    ordered = cards_sorted_for_user([card.card_id for card in CARDS])
    pages = max(1, (len(ordered) + FAQ_PAGE_SIZE - 1) // FAQ_PAGE_SIZE)
    page = max(0, min(int(page), pages - 1))
    chunk = ordered[page * FAQ_PAGE_SIZE : (page + 1) * FAQ_PAGE_SIZE]
    lines = [
        "🃏 <b>Персонажи</b> — рыночная цена",
        f"Страница <b>{page + 1}</b> из {pages}. Жми на карту: покажу статы и способность.",
        "",
    ]
    rows = [
        [
            InlineKeyboardButton(
                text=(
                    f"{card.rarity_emoji} {card.display_name} — "
                    f"{_money(market_price(card))}"
                ),
                callback_data=f"fq:card:{card.card_id}",
            )
        ]
        for card in chunk
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"fq:cards:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="fq:menu"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"fq:cards:{page + 1}"))
    rows.append(nav)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def faq_card(card: Card) -> tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"{card.rarity_emoji} <b>{esc(card.display_name)}</b> ({card.rarity_title})",
        f"<code>#{card.card_id}</code>",
    ]
    if card.description:
        lines.append(f"<i>{esc(card.description)}</i>")
    lines += [
        "",
        f"💰 <b>Рыночная цена: {_money(market_price(card))}</b>",
        f"     база {_money(card.points)} × редкость {rarity_coef(card):g}",
        "",
        f"⚔️ Атака: <b>{card.atk}</b> · ❤️ HP: <b>{card.hp}</b> · 💪 Бюджет: {card.budget}",
        "",
        f"✨ <b>{esc(card.ability.name)}</b> · перезарядка {card.ability.cooldown} х.",
        f"     {esc(_ability_line(card))}",
    ]
    if card.card_id == "misha":
        # пасхалка: код на бесплатного Мишу
        lines += ["", "🥔 Промокод: <code>MISHAINPOTATO</code>"]
    rows = [
        [
            InlineKeyboardButton(text="◀️ К списку", callback_data="fq:cards:0"),
            InlineKeyboardButton(text="🎨 Улучшения", callback_data="fq:items:aura"),
        ],
        [InlineKeyboardButton(text="🧮 Как считается цена", callback_data="fq:price")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def faq_items(slot: str = SLOT_AURA) -> tuple[str, InlineKeyboardMarkup]:
    if slot not in BY_SLOT:
        slot = SLOT_AURA
    lines = [
        f"{SLOT_ICONS[slot]} <b>{SLOT_TITLES[slot]}</b> — бонусы и множитель цены",
        "",
        "Аура множит все три стата, фон и эффект — только один.",
        "Множитель ниже — во сколько раз один этот предмет поднимает цену карты.",
        "",
    ]
    for item in BY_SLOT[slot]:
        total = sum(item.bonus.values())
        lines.append(f"<b>{esc(item.name)}</b> — {item.summary}")
        lines.append(f"     всего {total:+d}% → цена ×{upgrade_multiplier(item.bonus):.2f}")
    rows = [
        [
            InlineKeyboardButton(
                text=f"{SLOT_ICONS[s]} {SLOT_TITLES[s]}", callback_data=f"fq:items:{s}"
            )
        ]
        for s in SLOTS
    ]
    rows.append([InlineKeyboardButton(text="🧮 Как считается цена", callback_data="fq:price")])
    rows.append([InlineKeyboardButton(text="◀️ В меню", callback_data="fq:menu")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def faq_price() -> tuple[str, InlineKeyboardMarkup]:
    card = get_card("valeriya")
    aura = AURAS[0]
    aura_total = sum(aura.bonus.values())

    best_aura = max(AURAS, key=lambda item: sum(item.bonus.values()))
    best_bg = max(BACKGROUNDS, key=lambda item: sum(item.bonus.values()))
    best_fx = max(EFFECTS, key=lambda item: sum(item.bonus.values()))
    best_total = (
        sum(best_aura.bonus.values())
        + sum(best_bg.bonus.values())
        + sum(best_fx.bonus.values())
    )
    max_mult = 1 + best_total * 2.0 / 100

    lines = [
        "🧮 <b>Как считается рыночная цена</b>",
        "",
        "Формула:",
        "<b>цена = очки карты × коэффициент редкости × множитель улучшений</b>",
        "",
        "Множитель улучшений:",
        "<b>1 + (сумма всех процентов × 2 / 100)</b>",
        f"Не ниже {UPGRADE_MULT_MIN:g}. Максимум в игре — <b>×{max_mult:.2f}</b> "
        f"(аура «{esc(best_aura.name)}», фон «{esc(best_bg.name)}», "
        f"эффект «{esc(best_fx.name)}»: суммарно {best_total:+d}%).",
        "",
        "<b>Коэффициенты редкости:</b>",
    ]
    lines += _rarity_list()
    lines += [
        "",
        f"<b>Пример 1 — чистая карта.</b> {esc(card.display_name)}: "
        f"{_money(card.points)} × {rarity_coef(card):g} = <b>{_money(market_price(card))}</b>",
        "",
        f"<b>Пример 2 — с аурой «{esc(aura.name)}»</b> "
        f"({aura.summary}, суммарно {aura_total:+d}%):",
        f"множитель = 1 + {aura_total} × 2 / 100 = {upgrade_multiplier(aura.bonus):.2f}",
        f"{_money(card.points)} × {rarity_coef(card):g} × "
        f"{upgrade_multiplier(aura.bonus):.2f} = <b>{_money(market_price(card, aura.bonus))}</b>",
        "",
        "<b>Запомни главное:</b> проценты всех трёх улучшений складываются, и цена "
        "растёт от суммы — неважно, в какой стат они ушли. Отрицательные проценты "
        "снижают цену так же, как положительные её поднимают.",
    ]
    rows = [
        [InlineKeyboardButton(text="🃏 Персонажи", callback_data="fq:cards:0")],
        [InlineKeyboardButton(text="🎨 Улучшения", callback_data="fq:items:aura")],
        [InlineKeyboardButton(text="◀️ В меню", callback_data="fq:menu")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


# --------------------------------------------------------------------------- #
# /my — коллекция по страницам
# --------------------------------------------------------------------------- #

MY_PAGE = 8
MY_UNITS_PAGE = 6


def my_home(
    stats: dict[str, Any], total_cards: int, units: int, cases: int
) -> tuple[str, InlineKeyboardMarkup]:
    text = "\n".join(
        [
            "🎒 <b>Коллекция</b>",
            "",
            f"💰 Баланс: <b>{stats['total']}</b> очк. · коллекция на {stats['points']}",
            f"🃏 Карт: <b>{stats['unique_cards']}</b>/{total_cards} · "
            f"копий: {stats['total_cards']}",
            f"⚡ Улучшенных: <b>{units}</b> · 📦 Кейсов: <b>{cases}</b>",
            f"🔪 Убийств: {stats['card_kills']}",
            "",
            # пасхалка: код на дополнительные попытки «Северо-Юг»
            "🍁 Промокод: <code>северо юн</code>",
        ]
    )
    rows = [
        [InlineKeyboardButton(text="🃏 Карты", callback_data="my:c:0")],
        [InlineKeyboardButton(text=f"⚡ Улучшенные ({units})", callback_data="my:u:0")],
        [InlineKeyboardButton(text=f"📦 Кейсы ({cases})", callback_data="my:k")],
        [InlineKeyboardButton(text="🏆 Профиль", callback_data="my:p")],
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def _my_nav(
    prefix: str, page: int, pages: int, middle: str = "my:home"
) -> list[InlineKeyboardButton]:
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"{prefix}:{page - 1}"))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data=middle))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"{prefix}:{page + 1}"))
    return nav


def my_cards(
    cards: list[Card],
    counts: dict[str, int],
    page: int,
    *,
    prefix: str = "my",
    header: str = "Мои карты",
    middle: str = "my:home",
) -> tuple[str, InlineKeyboardMarkup]:
    pages = max(1, (len(cards) + MY_PAGE - 1) // MY_PAGE)
    page = max(0, min(int(page), pages - 1))
    chunk = cards[page * MY_PAGE : (page + 1) * MY_PAGE]
    lines = [
        f"🃏 <b>{header}</b>",
        f"Страница <b>{page + 1}</b> из {pages}.",
        "",
    ]
    rows: list[list[InlineKeyboardButton]] = []
    pair: list[InlineKeyboardButton] = []
    for card in chunk:
        count = counts.get(card.card_id, 1)
        label = f"{card.rarity_emoji} {card.name} ⚔{card.atk}/❤{card.hp}"
        if count > 1:
            label += f" ×{count}"
        pair.append(
            InlineKeyboardButton(
                text=label, callback_data=f"{prefix}:d:#{card.card_id}"
            )
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    rows.append(_my_nav(f"{prefix}:c", page, pages, middle))
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def my_units(units: list[dict[str, Any]], page: int) -> tuple[str, InlineKeyboardMarkup]:
    pages = max(1, (len(units) + MY_UNITS_PAGE - 1) // MY_UNITS_PAGE)
    page = max(0, min(int(page), pages - 1))
    chunk = units[page * MY_UNITS_PAGE : (page + 1) * MY_UNITS_PAGE]
    lines = [
        "⚡ <b>Улучшенные копии</b>",
        f"Страница <b>{page + 1}</b> из {pages}.",
        "",
        "Перебить улучшение нельзя, зато можно менять аксессуары.",
    ]
    rows: list[list[InlineKeyboardButton]] = []
    for unit in chunk:
        card = unit["card"]
        stats = unit["stats"]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{card.rarity_emoji} {card.name} ⚔{stats['atk']}/"
                    f"❤{stats['hp']}/🛡{stats['def']}",
                    callback_data=f"my:d:#{unit['inventory_id']}",
                )
            ]
        )
    rows.append(_my_nav("my:u", page, pages))
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def my_card(
    unit: dict[str, Any], worn: list[dict[str, Any]]
) -> tuple[str, InlineKeyboardMarkup]:
    card = unit["card"]
    stats = unit["stats"]
    lines = [
        card_title(card),
        f"<code>{esc(unit['handle'])}</code>",
        "",
        f"⚔️ Атака: <b>{stats['atk']}</b>   ❤️ HP: <b>{stats['hp']}</b>   "
        f"🛡 Защита: <b>{stats['def']}%</b>",
        f"✨ <b>{esc(card.ability.name)}</b> — КД {card.ability.cooldown}: "
        f"{describe_ability(card)}",
    ]
    if unit.get("items"):
        lines += ["", "Улучшения: " + " · ".join(unit["items"])]
    if worn:
        lines += ["", "🎒 Аксессуары: " + ", ".join(esc(a["name"]) for a in worn)]
    rows = [
        [
            InlineKeyboardButton(
                text="❤️ Сделать любимой", callback_data=f"my:v:{unit['handle']}"
            )
        ],
        [InlineKeyboardButton(text="🎒 Предметы", callback_data=f"my:i:{unit['handle']}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="my:home")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def my_items(
    unit: dict[str, Any], owned: list[dict[str, Any]]
) -> tuple[str, InlineKeyboardMarkup]:
    card = unit["card"]
    lines = [
        "🎒 <b>Предметы</b>",
        f"Карта: <b>{esc(card.display_name)}</b>",
        "",
        "Жми, чтобы надеть или снять. Аксессуар работает только на ту карту, "
        "на которую надет.",
        "",
    ]
    if not owned:
        lines.append("Аксессуаров пока нет — они продаются в магазине (/shop).")
    rows: list[list[InlineKeyboardButton]] = []
    for acc in owned:
        worn_here = acc.get("card_id") == card.card_id
        if acc.get("card_id") and not worn_here:
            label = f"🔒 {acc['name']} — на {get_card(str(acc['card_id'])).name}"
        else:
            label = f"{'✅' if worn_here else '▫️'} {acc['name']} · {acc['summary']}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label, callback_data=f"my:a:{unit['handle']}:{acc['id']}"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="⬅️ К карте", callback_data=f"my:d:{unit['handle']}")]
    )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


# --------------------------------------------------------------------------- #
# Главное меню
# --------------------------------------------------------------------------- #


def render_main_menu(bot_name: str, app_url: str = "") -> tuple[str, InlineKeyboardMarkup]:
    text = "\n".join(
        [
            f"🍁 <b>Северо-Юг</b> · <i>@{esc(bot_name)}</i>",
            "коллекционные карточки и PvP · школьная осень",
            "",
            "🎴 <b>«Северо-Юг»</b> — выбить карту (раз в сутки)",
            "🎰 <b>«рулетка»</b> — крутка в 20:00 по ЕКБ",
            "📦 <b>«кейс»</b> — открыть кейс",
            "⚔️ <b>«пвп»</b> ответом — вызвать на бой",
            "🎲 <b>/casino</b> — ставка очками или картой",
        ]
    )
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(text="🎒 Коллекция", callback_data="my:home"),
            InlineKeyboardButton(text="📖 FAQ", callback_data="fq:menu"),
        ]
    ]
    if app_url:
        from aiogram.types import WebAppInfo

        rows.append(
            [
                InlineKeyboardButton(
                    text="🛒 Магазин", web_app=WebAppInfo(url=f"{app_url}/app")
                ),
                InlineKeyboardButton(
                    text="🏪 Рынок", web_app=WebAppInfo(url=f"{app_url}/market")
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="📈 Биржа", web_app=WebAppInfo(url=f"{app_url}/stocks")
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="🏆 Топ", callback_data="mn:top"),
            InlineKeyboardButton(text="👤 Профиль", callback_data="my:p"),
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="❓ Помощь", callback_data="mn:help")]
    )
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def render_clicker() -> tuple[str, InlineKeyboardMarkup]:
    lines = [
        "👆 <b>КЛИКЕР</b>",
        "",
        "Жми кнопку — что-нибудь да упадёт. Что именно, решает рандом:",
        "  💰 очки — почти всегда",
        "  🎴 крутка «Северо-Юг» — редко",
        "  🎰 спин рулетки — редко",
        "  📦 кейс — редко",
        "  🃏 карта — совсем редко",
        "",
        "Тапай сколько хочешь — подарки капают!",
    ]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👆 Тапнуть", callback_data="clicker:tap")]
        ]
    )
    return "\n".join(lines), keyboard


def render_top(rows: list[dict[str, Any]]) -> str:
    lines = ["🏆 <b>Топ по очкам</b>", ""]
    medals = ["🥇", "🥈", "🥉"]
    for index, row in enumerate(rows):
        medal = medals[index] if index < len(medals) else f"{index + 1}."
        name = row.get("first_name") or row.get("username") or "игрок"
        lines.append(
            f"{medal} {esc(name)} — <b>{int(row['points'])}</b> очк. · "
            f"{int(row['unique_cards'])} карт"
        )
    if not rows:
        lines.append("Пока пусто.")
    return "\n".join(lines)

def render_levelup(summary: dict[str, Any]) -> str:
    """Сообщение о новом уровне и выданных наградах."""
    gained = list(summary.get("levels") or [])
    if not gained:
        return ""
    top = int(gained[-1])
    lines = [f"🎉 <b>Новый уровень: {top}!</b>"]
    if len(gained) > 1:
        lines.append(f"Сразу {len(gained)}: с {gained[0]} по {top}")
    rewards = list(summary.get("rewards") or [])
    if rewards:
        lines += ["", "🎁 <b>Награда</b>"]
        lines += [f"  • {esc(item)}" for item in rewards]
    return "\n".join(lines)


def render_boss(
    raid: dict[str, Any], top: list[dict[str, Any]], stats: dict[str, Any]
) -> tuple[str, InlineKeyboardMarkup]:
    hp = int(raid["hp"])
    max_hp = max(1, int(raid["max_hp"]))
    damage = int(raid["hit_damage"])
    lines = [
        f"👹 <b>РЕЙД-БОСС: {esc(str(raid['name']))}</b>",
        "",
        f"❤️ HP: <b>{_money(hp)}</b> / {_money(max_hp)} · "
        f"{boss.percent(hp, max_hp)}%",
        boss.bar(hp, max_hp),
        "",
        f"👊 Один удар — <b>{damage}</b> урона. Карты и способности не нужны.",
        f"👥 Бьют: <b>{int(stats['people'])}</b> · "
        f"ударов: <b>{int(stats['hits'])}</b>",
    ]
    if top:
        lines += ["", "🏆 <b>Кто бьёт сильнее всех</b>"]
        for index, row in enumerate(top, start=1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(index, f"{index}.")
            lines.append(
                f"  {medal} {esc(str(row.get('name') or 'игрок'))} — "
                f"{int(row['hits'])} уд. ({_money(int(row['damage']))})"
            )
    lines += ["", "👇 Жми кнопку сколько угодно — лишь бы успеть добить!"]
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"⚔️ Ударить (−{damage})", callback_data="boss:hit"
                )
            ]
        ]
    )
    return "\n".join(lines), keyboard


def render_boss_victory(
    raid: dict[str, Any], top: list[dict[str, Any]], stats: dict[str, Any]
) -> str:
    lines = [
        "🏆 <b>РЕЙД-БОСС ПОВЕРЖЕН!</b>",
        f"{esc(str(raid['name']))} добит: {int(stats['hits'])} ударов от "
        f"{int(stats['people'])} игроков.",
        "",
        "🎁 <b>Награда каждому игроку</b>",
        f"  🎴 +{boss.REWARD_DROPS} круток «Северо-Юг»",
        f"  🎰 +{boss.REWARD_SPINS} спинов рулетки",
        f"  📦 +{boss.REWARD_CASES} кейса",
        "",
        "Уже выдали — забирай: /drop и /case",
    ]
    if top:
        lines += ["", "🏆 <b>Топ по урону</b>"]
        for index, row in enumerate(top, start=1):
            lines.append(
                f"  {index}. {esc(str(row.get('name') or 'игрок'))} — "
                f"{_money(int(row['damage']))} урона"
            )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Кликер-копилка
# --------------------------------------------------------------------------- #


def clicker_hud(
    me: dict[str, Any], top: list[dict[str, Any]], running: bool
) -> tuple[str, InlineKeyboardMarkup]:
    lines = [
        "🎮 <b>Копилка ивента</b>",
        "",
        f"👆 Кликов: <b>{me['clicks']}</b>",
        f"💰 В копилке: <b>{me['points']}</b> очков",
        f"🏆 Место: <b>#{me['rank']}</b> из {me['players']}",
    ]
    if top:
        lines += ["", "<b>Топ кликеров</b>"]
        for index, row in enumerate(top):
            name = row.get("first_name") or row.get("username") or "игрок"
            lines.append(f"  {index + 1}. {esc(name)} — {row['points']}")
    lines.append("")
    lines.append(
        "⏳ Награды копятся и выдадутся все разом, когда закончится ивент."
        if running
        else "🎁 Ивент закончился — награды уже раздали."
    )
    rows = [
        [InlineKeyboardButton(text="👆 КЛИК", callback_data="kl:c")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="kl:r")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)
