"""Сквозной тест хэндлеров на фейковой Telegram-сессии и фейковой БД.

Проверяет: разбор Update, инъекцию зависимостей aiogram (db/service),
фильтр «Северо-Юг» без учёта регистра и формат ответа.

Роутер приложения подключается к одному Dispatcher на весь модуль:
aiogram запрещает привязывать один Router к нескольким родителям.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Message, Update, User

from app.cards import get_card
from app.handlers import router

_DISPATCHER: Dispatcher | None = None


def dispatcher() -> Dispatcher:
    global _DISPATCHER
    if _DISPATCHER is None:
        _DISPATCHER = Dispatcher()
        _DISPATCHER.include_router(router)
    return _DISPATCHER


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def close(self) -> None:  # pragma: no cover
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.calls.append((type(method).__name__, dict(method.model_dump(exclude_none=True))))
        if type(method).__name__ in {"SendMessage", "SendPhoto"}:
            return Message(
                message_id=999,
                date=datetime.now(timezone.utc),
                chat=Chat(id=getattr(method, "chat_id", 1), type="private"),
            )
        if type(method).__name__ == "GetMe":
            return User(id=555, is_bot=True, first_name="bot", username="severo_yug_bot")
        return True

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        yield b""


class FakeDB:
    def __init__(self) -> None:
        self.collection: dict[int, dict[str, int]] = {}
        self.claimed: dict[int, bool] = {}
        self.balance: dict[int, int] = {}
        self.names: dict[int, str] = {}

    async def add_points(self, user_id: int, amount: int) -> int:
        self.balance[user_id] = self.balance.get(user_id, 0) + int(amount)
        return self.balance[user_id]

    async def ensure_player(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def claim_daily(self, user_id: int, day: Any, limit: int = 1) -> int | None:
        if self.claimed.get(user_id):
            return None
        self.claimed[user_id] = True
        return 0

    async def claim_roulette(self, user_id: int, day: Any, limit: int = 1) -> int | None:
        if self.claimed.get(user_id):
            return None
        self.claimed[user_id] = True
        return 0

    async def get_collection(self, user_id: int) -> dict[str, int]:
        return dict(self.collection.get(user_id, {}))

    async def accessory_bonus(self, user_id: int, card_id: str) -> dict[str, int]:
        return {}

    async def touch_chat(self, chat_id: int, kind: str, title: str | None = None) -> None:
        return None

    async def my_accessories(self, user_id: int):
        return []

    async def user_cases(self, user_id: int, include_listed: bool = False):
        return []

    async def get_card_kills(self, user_id: int) -> dict[str, int]:
        return {card_id: 0 for card_id in self.collection.get(user_id, {})}

    async def add_card(self, user_id: int, card_id: str) -> int:
        bucket = self.collection.setdefault(user_id, {})
        bucket[card_id] = bucket.get(card_id, 0) + 1
        return bucket[card_id]

    async def add_drop(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def player_profile(self, user_id: int):
        return {
            "user_id": user_id,
            "first_name": self.names.get(user_id, f"Игрок{user_id}"),
            "username": None,
            "wins": 1,
            "losses": 0,
            "draws": 0,
            "kills": 2,
            "card_kills": 2,
            "bonus_points": 100,
            "card_points": 250,
            "total": 100,
            "unique_cards": 1,
            "total_cards": 1,
            "rank": 1,
        }

    async def collection_stats(self, user_id: int) -> dict[str, int]:
        cards = self.collection.get(user_id, {})
        return {
            "points": 0,
            "bonus": 0,
            "total": 0,
            "unique_cards": len(cards),
            "total_cards": sum(cards.values()),
            "card_kills": 0,
        }

    async def top_players(self, limit: int = 10) -> list[dict[str, Any]]:
        return []


class FakeMarket:
    def __init__(self) -> None:
        self.gifted: list[tuple[int, str, int]] = []

    async def user_inventory(self, user_id: int, include_listed: bool = False):
        return []

    async def balance(self, user_id: int) -> int:
        return 0

    async def buy_lot(self, lot_id: int, buyer_id: int):
        return {
            "kind": "case",
            "card_id": None,
            "price": 5000,
            "fee": 250,
            "income": 4750,
            "honest": True,
            "seller_id": 999,
        }

    async def count_lots(self) -> int:
        return 0

    async def list_lots(self, limit: int = 6, offset: int = 0):
        return []

    async def seller_lots(self, seller_id: int, limit: int = 20):
        return [
            {
                "id": 1,
                "kind": "case",
                "card_id": None,
                "status": "active",
                "price": 5000,
                "market_price": 5000,
                "suspect": False,
                "seller_id": seller_id,
            }
        ]

    async def find_by_username(self, username: str):
        if username.lstrip("@").lower() == "friend":
            return {"user_id": 333, "first_name": "Друг", "username": "friend"}
        return None

    async def owned_unit(self, user_id: int, handle):
        return {"kind": "card", "card_id": "oleg", "inventory_id": None, "case_id": None}

    async def gift_card(self, sender_id: int, unit, receiver_id: int) -> None:
        self.gifted.append((sender_id, unit["card_id"], receiver_id))


class FakeService:
    def __init__(self) -> None:
        self.created: list[tuple[int, int]] = []

    async def create(self, message: Message, challenger: Any, opponent: Any) -> None:
        self.created.append((challenger.id, opponent.id))


def build_update(text: str, user_id: int = 111, chat_id: int = -100123, reply: dict | None = None) -> dict:
    message: dict[str, Any] = {
        "message_id": 10,
        "from": {"id": user_id, "is_bot": False, "first_name": "Тест", "username": "tester"},
        "chat": {"id": chat_id, "type": "supergroup", "title": "Группа"},
        "date": 1700000000,
        "text": text,
    }
    if reply:
        message["reply_to_message"] = reply
    return {"update_id": 1, "message": message}


async def feed(
    text: str,
    db: FakeDB,
    service: FakeService,
    user_id: int = 111,
    reply: dict | None = None,
    market: "FakeMarket | None" = None,
):
    session = FakeSession()
    bot = Bot(token="123456:TEST", session=session)
    update = Update.model_validate(build_update(text, user_id=user_id, reply=reply), context={"bot": bot})
    await dispatcher().feed_update(
        bot, update, db=db, service=service, market=market or FakeMarket()
    )
    await bot.session.close()
    return session


def sent_texts(session: FakeSession) -> list[str]:
    return [payload["text"] for name, payload in session.calls if name == "SendMessage"]


def test_dependency_injection_and_resolve_update_types():
    async def scenario():
        assert "message" in dispatcher().resolve_used_update_types()
        session = FakeSession()
        bot = Bot(token="123456:TEST", session=session)
        update = Update.model_validate(build_update("/start"), context={"bot": bot})
        await dispatcher().feed_update(
            bot, update, db=FakeDB(), service=FakeService(), market=FakeMarket()
        )
        assert "SendMessage" in [name for name, _ in session.calls]
        await bot.session.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("text", ["Северо-Юг", "северо-юг", "СЕВЕРО ЮГ", "североюг", "сЕвЕрО-юГ"])
def test_daily_drop_variants(text: str):
    async def scenario():
        db = FakeDB()
        session = await feed(text, db, FakeService())
        body = sent_texts(session)
        assert len(body) == 1, (text, session.calls)
        assert "Урон:" in body[0] and "HP:" in body[0]
        assert db.collection[111], "карта должна попасть в коллекцию"
        assert db.balance[111] > 0, "карта должна начислить очки на баланс"

    asyncio.run(scenario())


def test_daily_limit_blocks_second_drop():
    async def scenario():
        db = FakeDB()
        await feed("Северо-Юг", db, FakeService())
        session = await feed("Северо-Юг", db, FakeService())
        assert "кончились" in sent_texts(session)[0]

    asyncio.run(scenario())


def test_random_words_are_ignored():
    async def scenario():
        session = await feed("привет как дела", FakeDB(), FakeService())
        assert session.calls == []

    asyncio.run(scenario())


def test_collection_command():
    async def scenario():
        db = FakeDB()
        db.collection[111] = {"oleg": 2, "valeriya": 1}
        session = await feed("/my", db, FakeService())
        body = sent_texts(session)[0]
        # /my теперь компактное меню, карты живут на своих страницах
        assert "Коллекция" in body and "Карт:" in body
        payload = next(p for n, p in session.calls if n == "SendMessage")
        markup = payload.get("reply_markup") or {}
        labels = [
            button["text"]
            for row in markup.get("inline_keyboard", [])
            for button in row
        ]
        assert any("Карты" in label for label in labels), labels

    asyncio.run(scenario())


def test_pvp_without_reply_asks_for_reply():
    async def scenario():
        session = await feed("пвп", FakeDB(), FakeService())
        assert "ответь" in sent_texts(session)[0].lower()

    asyncio.run(scenario())


def test_pvp_reply_creates_battle():
    async def scenario():
        service = FakeService()
        reply = {
            "message_id": 5,
            "from": {"id": 222, "is_bot": False, "first_name": "Соперник"},
            "chat": {"id": -100123, "type": "supergroup", "title": "Группа"},
            "date": 1700000000,
            "text": "я тут",
        }
        await feed("ПВП", FakeDB(), service, user_id=111, reply=reply)
        assert service.created == [(111, 222)]

    asyncio.run(scenario())


def test_unknown_callback_is_answered():
    async def scenario():
        session = FakeSession()
        bot = Bot(token="123456:TEST", session=session)
        payload = {
            "update_id": 2,
            "callback_query": {
                "id": "cb1",
                "from": {"id": 111, "is_bot": False, "first_name": "Тест"},
                "chat_instance": "ci",
                "data": "noop",
                "message": {
                    "message_id": 11,
                    "date": 1700000000,
                    "chat": {"id": -100123, "type": "supergroup", "title": "Группа"},
                    "from": {"id": 555, "is_bot": True, "first_name": "bot"},
                    "text": "бой",
                },
            },
        }
        update = Update.model_validate(payload, context={"bot": bot})
        await dispatcher().feed_update(
            bot, update, db=FakeDB(), service=FakeService(), market=FakeMarket()
        )
        assert any(name == "AnswerCallbackQuery" for name, _ in session.calls)
        await bot.session.close()

    asyncio.run(scenario())

def test_decorate_lot_handles_case_lots():
    """У кейса card_id = NULL: раньше это роняло весь список рынка."""
    from app.handlers import decorate_lot

    case_lot = {"id": 1, "kind": "case", "card_id": None, "inventory_id": None, "price": 5000}
    decorated = decorate_lot(case_lot)
    assert decorated["stats"] is None
    assert decorated["bonus"] == {}
    assert decorated["aura"] is None


def test_decorate_lot_still_computes_card_stats():
    from app.handlers import decorate_lot

    card_lot = {"id": 2, "kind": "card", "card_id": "oleg", "inventory_id": None, "price": 400}
    decorated = decorate_lot(card_lot)
    from app.cards import get_card as _get_card

    oleg = _get_card("oleg")
    assert decorated["stats"] == {"atk": oleg.atk, "hp": oleg.hp, "def": 0}

def test_gift_actually_sends_the_card():
    """Регрессия: раньше cmd_gift обрывался и молча ничего не дарил."""
    async def scenario():
        market = FakeMarket()
        reply = {
            "message_id": 5,
            "from": {"id": 222, "is_bot": False, "first_name": "Получатель"},
            "chat": {"id": -100123, "type": "supergroup", "title": "Группа"},
            "date": 1700000000,
            "text": "я тут",
        }
        session = await feed("/gift #oleg", FakeDB(), FakeService(), user_id=111, reply=reply, market=market)
        assert market.gifted == [(111, "oleg", 222)], "карта должна уйти получателю"
        body = [p for n, p in session.calls if n == "SendMessage"][0]["text"]
        assert "Подарок отправлен" in body


    asyncio.run(scenario())

def build_callback(data: str, user_id: int = 111) -> dict:
    return {
        "update_id": 9,
        "callback_query": {
            "id": "cb9",
            "from": {"id": user_id, "is_bot": False, "first_name": "Тест"},
            "chat_instance": "ci",
            "data": data,
            "message": {
                "message_id": 77,
                "date": 1700000000,
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": 555, "is_bot": True, "first_name": "bot"},
                "text": "профиль",
            },
        },
    }


async def feed_callback(data: str, db: FakeDB, market: FakeMarket, user_id: int = 111):
    session = FakeSession()
    bot = Bot(token="123456:TEST", session=session)
    update = Update.model_validate(build_callback(data, user_id), context={"bot": bot})
    await dispatcher().feed_update(bot, update, db=db, service=FakeService(), market=market)
    await bot.session.close()
    return session


def test_profile_of_another_player_is_shown():
    async def scenario():
        db = FakeDB()
        db.names[333] = "Друг"
        session = await feed("/profile @friend", db, FakeService())
        body = sent_texts(session)[0]
        assert "Друг" in body, "должен показаться чужой профиль"
        markup = str([p for n, p in session.calls if n == "SendMessage"][0].get("reply_markup"))
        assert "pf:333" in markup, "кнопки профиля должны вести на чужой аккаунт"

    asyncio.run(scenario())


def test_unknown_username_gives_a_hint():
    async def scenario():
        session = await feed("/profile @никого", FakeDB(), FakeService())
        assert "не найден" in sent_texts(session)[0]

    asyncio.run(scenario())


def test_other_players_cards_and_stats_are_viewable():
    async def scenario():
        db = FakeDB()
        db.collection[333] = {"oleg": 1}
        market = FakeMarket()

        # список карт чужого профиля
        session = await feed_callback("pf:333:cards", db, market)
        edits = [p for n, p in session.calls if n == "EditMessageText"]
        assert edits, "сообщение должно перерисоваться"
        assert "pf:333:card:#oleg" in str(edits[0]), "кнопки должны вести на карты игрока 333"

        # статы конкретной чужой карты
        session = await feed_callback("pf:333:card:#oleg", db, market)
        edits = [p for n, p in session.calls if n == "EditMessageText"]
        body = edits[0]["text"]
        assert "Олег" in body and "Атака" in body
        assert "только просмотр" in body, "чужие карты нельзя продавать или улучшать"
        assert "/sell" not in body

    asyncio.run(scenario())


def test_own_card_detail_offers_actions():
    async def scenario():
        db = FakeDB()
        db.collection[111] = {"oleg": 1}
        session = await feed_callback("pf:111:card:#oleg", db, FakeMarket())
        edits = [p for n, p in session.calls if n == "EditMessageText"]
        body = edits[0]["text"]
        assert "/sell" in body and "/upgrade" in body

    asyncio.run(scenario())

def test_admin_command_is_closed_for_regular_players():
    async def scenario():
        session = await feed("/admin status", FakeDB(), FakeService(), user_id=222)
        assert "только для админа" in sent_texts(session)[0]

    asyncio.run(scenario())


def test_admin_help_is_shown_to_admin():
    async def scenario():
        session = await feed("/admin", FakeDB(), FakeService(), user_id=111)
        body = sent_texts(session)[0]
        assert "Админ-команды" in body and "give" in body

    asyncio.run(scenario())


def test_start_shows_main_menu_with_buttons():
    """Раньше /start перехватывался старым хэндлером, и меню с кнопками не показывалось."""
    async def scenario():
        session = await feed("/start", FakeDB(), FakeService())
        payload = next(p for n, p in session.calls if n == "SendMessage")
        markup = str(payload.get("reply_markup"))
        assert "my:home" in markup, "главное меню должно быть кнопочным"

    asyncio.run(scenario())


def test_buying_a_case_lot_does_not_crash():
    """Регрессия: у кейса card_id = NULL, get_card(None) ронял покупку."""
    async def scenario():
        session = await feed_callback("mb:1", FakeDB(), FakeMarket())
        assert any(name == "EditMessageText" for name, _ in session.calls)

    asyncio.run(scenario())


def test_mylots_handles_case_lots():
    """Регрессия: /mylots падал на лоте-кейсе."""
    async def scenario():
        session = await feed("/mylots", FakeDB(), FakeService(), market=FakeMarket())
        assert "Кейс" in sent_texts(session)[0]

    asyncio.run(scenario())


def test_roulette_jackpot_credits_points(monkeypatch):
    """Главный приз рулетки — карта; она тоже должна начислять свои очки."""
    async def scenario():
        import app.handlers as handlers

        monkeypatch.setattr(handlers, "roll_prize", lambda: ("card", "daniel"))
        db = FakeDB()
        await feed("/roulette", db, FakeService())
        assert db.collection[111]["daniel"] == 1
        assert db.balance[111] == get_card("daniel").points > 0

    asyncio.run(scenario())
