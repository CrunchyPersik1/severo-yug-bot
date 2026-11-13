"""Админ-настройки: часть — для конкретного чата, часть — на всю игру.

Уведомления о бирже выключаются ТАМ, ГДЕ АДМИН ИХ ВЫКЛЮЧИЛ: в этой группе
перестанут приходить только её сообщения, остальные группы и лички живут
как жили. Поэтому такие ключи лежат в chat_settings, а не в app_settings.

Глобальные флаги (мини-аппки, кликер, магазин, дроп кристаллов) — это
состояние игры, оно одно на всех, и в панели они подписаны «глобально».
"""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Флаги уровня игры: одно значение на всех.
GLOBAL_ITEMS: tuple[dict[str, str], ...] = (
    {
        "key": "miniapps_live",
        "title": "Мини-аппки открыты",
        "desc": "кейсы, рулетка, казино, магазин, биржа",
        "default": "0",
    },
    {
        "key": "clicker_live",
        "title": "Кликер запущен",
        "desc": "кнопка «кликер» в чате",
        "default": "0",
    },
    {
        "key": "shop_open",
        "title": "Магазин работает",
        "desc": "витрина акций и паков",
        "default": "1",
    },
    {
        "key": "mop_gems",
        "title": "Кристаллы с мобов",
        "desc": "дроп 💎 в подземелье",
        "default": "1",
    },
)

# Флаги уровня чата: у каждой группы и каждой лички своё значение.
CHAT_ITEMS: tuple[dict[str, str], ...] = (
    {
        "key": "alerts_stocks",
        "title": "Оповещения о бирже",
        "desc": "только в этом чате",
        "default": "1",
    },
)

ITEMS = GLOBAL_ITEMS + CHAT_ITEMS
BY_KEY: dict[str, dict[str, str]] = {item["key"]: item for item in ITEMS}
CHAT_BY_KEY: dict[str, dict[str, str]] = {item["key"]: item for item in CHAT_ITEMS}


async def _setting(db: Any, key: str, default: str) -> str:
    value = await db.get_setting(key)
    return str(value if value is not None else default).strip()


async def _chat_setting(db: Any, chat_id: int, key: str, default: str) -> str:
    value = await db.chat_setting(int(chat_id), key)
    return str(value if value is not None else default).strip()


async def load(db: Any, chat_id: int | None = None) -> dict[str, bool]:
    """Состояние панели: глобальные флаги + флаг этого чата."""
    state: dict[str, bool] = {}
    for item in GLOBAL_ITEMS:
        state[item["key"]] = await _setting(db, item["key"], item["default"]) == "1"
    for item in CHAT_ITEMS:
        if chat_id is None:
            state[item["key"]] = item["default"] == "1"
        else:
            state[item["key"]] = (
                await _chat_setting(db, chat_id, item["key"], item["default"]) == "1"
            )
    return state


async def on(db: Any, key: str) -> bool:
    """Глобальный флаг. Чат-флаги здесь всегда читаются как False."""
    item = BY_KEY.get(key)
    if item is None or key in CHAT_BY_KEY:
        return False
    return await _setting(db, key, item["default"]) == "1"


async def chat_on(db: Any, chat_id: int, key: str) -> bool:
    item = CHAT_BY_KEY.get(key)
    if item is None or chat_id is None:
        return False
    return await _chat_setting(db, chat_id, key, item["default"]) == "1"


async def toggle(db: Any, chat_id: int | None, key: str) -> bool:
    """Переключает флаг и возвращает новое значение."""
    item = BY_KEY.get(key)
    if item is None:
        raise ValueError(f"нет такой настройки: {key}")
    if key in CHAT_BY_KEY:
        if chat_id is None:
            raise ValueError("эту настройку можно менять только в чате")
        current = await chat_on(db, chat_id, key)
        await db.set_chat_setting(int(chat_id), key, "0" if current else "1")
        return not current
    current = await on(db, key)
    await db.set_setting(key, "0" if current else "1")
    return not current


def _mark(value: bool) -> str:
    return "✅" if value else "⛔"


def text(state: dict[str, bool], chat_label: str = "", is_group: bool = True) -> str:
    """Панель: сначала то, что относится к этому чату, потом игра."""
    where = chat_label or ("этот чат" if is_group else "личка")
    lines = ["⚙️ <b>Настройки</b>", f"<i>Меняют только «{where}» или игру целиком.</i>", ""]
    lines.append("<b>ЭТОТ ЧАТ</b>")
    for item in CHAT_ITEMS:
        lines.append(f"{_mark(state.get(item['key'], True))} {item['title']}")
        lines.append(f"     <i>{item['desc']}</i>")
    lines += ["", "<b>ВСЯ ИГРА</b> <i>(видно всем игрокам)</i>"]
    for item in GLOBAL_ITEMS:
        lines.append(f"{_mark(state.get(item['key'], False))} {item['title']}")
        lines.append(f"     <i>{item['desc']}</i>")
    lines += ["", "Жми кнопку — переключу и перерисую панель."]
    return "\n".join(lines)


def keyboard(state: dict[str, bool]) -> InlineKeyboardMarkup:
    rows = []
    for item in CHAT_ITEMS:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{_mark(state.get(item['key'], True))} {item['title']} · чат",
                    callback_data=f"adm:s:{item['key']}",
                )
            ]
        )
    for item in GLOBAL_ITEMS:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{_mark(state.get(item['key'], False))} {item['title']} · игра",
                    callback_data=f"adm:s:{item['key']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:s:refresh")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
