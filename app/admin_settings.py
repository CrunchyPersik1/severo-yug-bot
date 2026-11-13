"""Админ-настройки в чате: переключатели, которые видно и можно тыкать.

Всё лежит в таблице app_settings (ключ → "0"/"1"), поэтому переживает
перезапуск и читается из тех же мест, где уже читались clicker_live и
miniapps_live. Эта панель — единая точка: см. /admin settings.
"""

from __future__ import annotations

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# key, заголовок, описание, значение «по умолчанию», если в базе пусто
ITEMS: tuple[dict[str, str], ...] = (
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
        "key": "alerts_stocks",
        "title": "Оповещения о бирже",
        "desc": "ЛС и группы, когда монета +10%",
        "default": "1",
    },
    {
        "key": "mop_gems",
        "title": "Кристаллы с мобов",
        "desc": "дроп 💎 в подземелье",
        "default": "1",
    },
)

BY_KEY: dict[str, dict[str, str]] = {item["key"]: item for item in ITEMS}


async def load(db: Any) -> dict[str, bool]:
    """Текущее состояние всех переключателей."""
    out: dict[str, bool] = {}
    for item in ITEMS:
        value = await db.get_setting(item["key"])
        raw = value if value is not None else item["default"]
        out[item["key"]] = str(raw).strip() == "1"
    return out


async def on(db: Any, key: str) -> bool:
    """Включён ли переключатель. Неизвестный ключ — False."""
    item = BY_KEY.get(key)
    if item is None:
        return False
    value = await db.get_setting(key)
    raw = value if value is not None else item["default"]
    return str(raw).strip() == "1"


async def toggle(db: Any, key: str) -> bool:
    """Переключает и возвращает новое значение."""
    if key not in BY_KEY:
        raise ValueError(f"нет такой настройки: {key}")
    current = await on(db, key)
    await db.set_setting(key, "0" if current else "1")
    return not current


def text(state: dict[str, bool], extra: str = "") -> str:
    lines = ["⚙️ <b>Настройки бота</b>", ""]
    for item in ITEMS:
        mark = "✅" if state.get(item["key"]) else "⛔"
        lines.append(f"{mark} <b>{item['title']}</b>")
        lines.append(f"     <i>{item['desc']}</i>")
    if extra:
        lines += ["", extra]
    lines += ["", "Жми кнопку — переключу и покажу результат."]
    return "\n".join(lines)


def keyboard(state: dict[str, bool]) -> InlineKeyboardMarkup:
    rows = []
    for item in ITEMS:
        mark = "✅" if state.get(item["key"]) else "⛔"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {item['title']}",
                    callback_data=f"adm:s:{item['key']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:s:refresh")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
