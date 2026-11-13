"""Живой лог игры: кто что нажал.

Пишется из двух мест — webhook бота (main.telegram_webhook) и ручки
мини-аппки (webapp._player), — а читается командой `admin.local.bat log`
в консоли. Таблица game_log, см. schema.sql.

Зачем через базу, а не через print: бот крутится на Render, его stdout
владельцу недоступен. База — единственный канал, который виден и снаружи,
и локально, и одинаково у обоих.

Ключевое правило: лог НИКОГДА не ломает игру. Любая ошибка записи
глотается — лучше потерять строчку истории, чем уронить нажатие кнопки.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import html
import re
from typing import Any

# Сколько дней храним. Лог растёт быстро (клики в кликере, удары в
# подземелье), а смотреть в него больше чем за неделю никто не станет.
KEEP_DAYS = 7

# Символов в detail. Обрезаем, чтобы в ленте не расползались простыни.
DETAIL_MAX = 220

# Как называть источники в ленте.
SOURCE_MARK = {
    "bot": "бот",
    "app": "приложение",
    "dungeon": "подземелье",
}

_TAG_RE = re.compile(r"<[^>]+>")
_SPACES_RE = re.compile(r"\s+")


def who_of(username: str | None, first_name: str | None, user_id: Any) -> str:
    """Человеческая подпись игрока: @ник, иначе имя, иначе id."""
    nick = (username or "").strip().lstrip("@")
    name = (first_name or "").strip()
    if nick and name:
        return f"{name} (@{nick})"
    if nick:
        return f"@{nick}"
    if name:
        return name
    return f"id{user_id}" if user_id else "?"


def clean(text: object, limit: int = DETAIL_MAX) -> str:
    """Однострочный текст без разметки и лишних пробелов."""
    raw = html.unescape(str(text or ""))
    raw = _TAG_RE.sub(" ", raw)
    raw = _SPACES_RE.sub(" ", raw).strip()
    if len(raw) > limit:
        raw = raw[: limit - 1] + "…"
    return raw


async def write(
    pool,
    user_id: Any,
    who: str,
    source: str,
    action: str,
    detail: object = "",
) -> None:
    """Одна строчка в лог. Никогда не бросает исключение наружу."""
    try:
        async with pool.acquire() as con:
            await con.execute(
                """
                insert into game_log (user_id, who, source, action, detail)
                values ($1::bigint, $2::text, $3::text, $4::text, $5::text)
                """,
                int(user_id) if user_id else None,
                clean(who, 80),
                clean(source, 24),
                clean(action, 60),
                clean(detail),
            )
    except Exception:  # noqa: BLE001
        # Лог не имеет права ломать игру. Молча.
        pass


def write_soon(pool, user_id: Any, who: str, source: str, action: str, detail: object = "") -> None:
    """Запись «в фоне», без ожидания.

    В горячем пути (ручка мини-аппки) ждать лишний round-trip к пулеру
    Supabase — это +1.5 с к ответу игроку. Логируем мимо кассы.
    Ссылку на задачу держим в множестве, иначе её может собрать GC
    раньше, чем она выполнится.
    """
    try:
        task = asyncio.create_task(write(pool, user_id, who, source, action, detail))
    except Exception:  # noqa: BLE001
        return
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)


_PENDING: set[asyncio.Task] = set()


async def recent(
    con,
    minutes: int = 30,
    limit: int = 60,
    username: str | None = None,
) -> list:
    """Последние строки ленты, свежие сверху."""
    minutes = max(1, min(int(minutes), 60 * 24 * 7))
    limit = max(1, min(int(limit), 500))
    if username:
        return await con.fetch(
            """
            select * from game_log
             where created_at > now() - make_interval(mins => $1)
               and (user_id in (select user_id from players
                                 where lower(username) = lower($3))
                    or who ilike '%' || $3 || '%')
             order by created_at desc, id desc
             limit $2
            """,
            minutes,
            limit,
            username,
        )
    return await con.fetch(
        """
        select * from game_log
         where created_at > now() - make_interval(mins => $1)
         order by created_at desc, id desc
         limit $2
        """,
        minutes,
        limit,
    )


async def prune(pool, keep_days: int = KEEP_DAYS) -> int:
    """Удаляет старые строки. Возвращает, сколько снесено."""
    try:
        async with pool.acquire() as con:
            result = await con.execute(
                "delete from game_log where created_at < now() - make_interval(days => $1)",
                int(keep_days),
            )
        # asyncpg отдаёт строкой вида "DELETE 12"
        return int(str(result).split()[-1]) if result else 0
    except Exception:  # noqa: BLE001
        return 0


def _stamp(moment: Any) -> str:
    """Время в локальной зоне машины, где смотрят лог."""
    if moment is None:
        return "  --:--:--"
    if isinstance(moment, dt.datetime):
        local = moment.astimezone()
        return local.strftime("%d.%m %H:%M:%S")
    return str(moment)


def line(row) -> str:
    """Одна строка ленты для консоли."""
    who = str(row["who"] or "").strip()
    if not who:
        who = f"id{row['user_id']}" if row["user_id"] else "?"
    src = SOURCE_MARK.get(str(row["source"] or ""), str(row["source"] or ""))
    body = f"{_stamp(row['created_at'])}  {who:<26} [{src}]".ljust(52)
    body += f" {row['action']}"
    detail = str(row["detail"] or "")
    if detail:
        body += " · " + detail
    return body


def frame(title: str, width: int = 100) -> str:
    """Разделитель, чтобы лента читалась глазами."""
    head = f"── {title} "
    return head + "─" * max(0, width - len(head))


# --------------------------------------------------------------------------- #
# Разбор апдейта бота в человеческую строку
# --------------------------------------------------------------------------- #

# callback_data у кнопок — служебные, режем до понятного вида.
_CALLBACK = {
    "drop": "крутка «Северо-Юг»",
    "roulette": "рулетка",
    "case": "кейс",
    "top": "топ",
    "profile": "профиль",
    "hub": "мини-аппка",
    "buy": "покупка",
    "sell": "продажа",
    "market": "биржа",
}


def describe_update(update: Any) -> tuple[Any, str, str, str] | None:
    """(user_id, кто, действие, подробности) — или None, если нечего писать.

    Пишем всё, во что человек ткнул: команды, кнопки, обычные сообщения.
    Служебные апдейты (правки, реакции, служебные чаты) пропускаем, иначе
    лента превращается в мусор.
    """
    message = getattr(update, "message", None) or getattr(update, "edited_message", None)
    query = getattr(update, "callback_query", None)

    if message is not None:
        user = getattr(message, "from_user", None)
        if user is None or getattr(user, "is_bot", False):
            return None
        who = who_of(user.username, user.first_name, user.id)
        text = (message.text or "").strip()
        where = getattr(getattr(message, "chat", None), "type", "") or ""
        place = {"private": "личка", "group": "группа", "supergroup": "группа"}.get(where, where or "чат")
        if text.startswith("/"):
            # Отрезаем @бота и аргументы оставляем: видно, что именно просили.
            head, _, rest = text.partition(" ")
            command = head.split("@")[0]
            args = clean(rest, 80)
            return user.id, who, f"команда {command}", f"{args} · {place}".strip(" ·")
        if text:
            return user.id, who, "сообщение", clean(text, 100)
        if getattr(message, "web_app_data", None) is not None:
            return user.id, who, "данные из мини-аппки", ""
        for name, label in (
            ("photo", "фото"), ("document", "файл"), ("sticker", "стикер"),
            ("voice", "голосовое"), ("video", "видео"), ("dice", "кубик"),
        ):
            if getattr(message, name, None) is not None:
                return user.id, who, label, place
        return None

    if query is not None:
        user = getattr(query, "from_user", None)
        if user is None or getattr(user, "is_bot", False):
            return None
        who = who_of(user.username, user.first_name, user.id)
        data = str(getattr(query, "data", "") or "")
        label = _CALLBACK.get(data.split(":")[0], "") if data else ""
        action = f"кнопка {label}" if label else "кнопка"
        return user.id, who, action, clean(data, 80)

    return None
