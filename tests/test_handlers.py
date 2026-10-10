"""Сквозной тест хэндлеров на фейковой Telegram-сессии и фейковой БД.

Проверяет: разбор Update, инъекцию зависимостей aiogram (db/service),
фильтр «Северо-Юг» без учёта регистра и формат ответа.

Роутер приложения подключается к одному Dispatcher на весь модуль:
aiogram запрещает привязывать один Router к нескольким родителям.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import Chat, Dice, Message, Update, User

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
        if type(method).__name__ == "SendDice":
            return Message(
                message_id=1000,
                date=datetime.now(timezone.utc),
                chat=Chat(id=getattr(method, "chat_id", 1), type="private"),
                dice=Dice(emoji=getattr(method, "emoji", None) or "🎲", value=5),
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
        # рефералка: живое состояние, чтобы прогнать полный сценарий
        self.ref_links: dict[str, dict[str, Any]] = {}
        self.referrals: dict[int, int] = {}
        self.drop_grants: list[tuple[int, int]] = []
        self.boss_rewards: tuple[int, int, int] | None = None
        self.settings: dict[str, str] = {}
        self.spin_grants: list[tuple[int, int]] = []
        self.cases: list[tuple[int, str]] = []

    async def add_points(self, user_id: int, amount: int) -> int:
        self.balance[user_id] = self.balance.get(user_id, 0) + int(amount)
        return self.balance[user_id]

    async def ensure_player(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def get_setting(self, key: str) -> str | None:
        return self.settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self.settings[key] = str(value)

    async def broadcast_targets(self) -> list[int]:
        return []

    async def all_player_ids(self) -> list[int]:
        return []

    async def grant_boss_rewards(
        self,
        drop_day: Any,
        spin_day: Any,
        drops: int,
        spins: int,
        cases: int,
    ) -> int:
        self.boss_rewards = (int(drops), int(spins), int(cases))
        return 0

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

    async def claim_casino(self, user_id: int, day: Any, limit: int = 25) -> int | None:
        return int(limit) - 1

    async def casino_stats(self, user_id: int) -> dict[str, int]:
        return {
            "point_bets": 4,
            "staked": 40000,
            "returned": 55000,
            "won_points": 30000,
            "lost_points": 15000,
            "card_bets": 2,
            "card_wins": 1,
            "card_deleted": 1,
        }

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

    async def redeem_promo(self, user_id: int, code: str) -> bool:
        return True

    async def grant_drop_limit(
        self, user_id: int, day: Any, amount: int, default_limit: int = 1
    ) -> int:
        self.drop_grants.append((user_id, int(amount)))
        return int(default_limit) + int(amount)

    async def grant_spin_limit(
        self, user_id: int, day: Any, amount: int, default_limit: int = 1
    ) -> int:
        self.spin_grants.append((user_id, int(amount)))
        return int(default_limit) + int(amount)

    async def add_case(self, user_id: int, source: str = "clicker") -> int:
        self.cases.append((int(user_id), source))
        return len(self.cases)

    async def latest_ref_link(self, user_id: int):
        links = [l for l in self.ref_links.values() if l["owner_id"] == user_id]
        return max(links, key=lambda l: l["created_at"]) if links else None

    async def insert_ref_link(self, user_id: int, code: str, max_uses: int = 25):
        link = {
            "code": code,
            "owner_id": user_id,
            "uses": 0,
            "max_uses": int(max_uses),
            "active": True,
            "created_at": datetime.now(timezone.utc),
        }
        self.ref_links[code] = link
        return dict(link)

    async def claim_referral(self, referred_id: int, code: str):
        if referred_id in self.referrals:
            return None
        link = self.ref_links.get(code)
        if link is None or not link["active"] or link["uses"] >= link["max_uses"]:
            return None
        if int(link["owner_id"]) == int(referred_id):
            return None
        self.referrals[referred_id] = int(link["owner_id"])
        link["uses"] += 1
        link["active"] = link["uses"] < link["max_uses"]
        return {
            "owner_id": int(link["owner_id"]),
            "uses": link["uses"],
            "max_uses": int(link["max_uses"]),
            "exhausted": not link["active"],
        }

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
        return 1_000_000

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

    async def find_player(self, raw: str):
        clean = (raw or "").strip().lstrip("@").lower()
        if clean in {"friend", "333"}:
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


class FakeBossRepo:
    """Рейд-босс в памяти: без базы, но с настоящим вычитанием HP."""

    def __init__(self) -> None:
        self.raid: dict[str, Any] | None = None
        self.hits: list[tuple[int, int]] = []
        self.rewarded = False

    async def start(self, name: str, hp: int, chat_id: int | None = None):
        self.raid = {
            "id": 1,
            "name": name,
            "hp": int(hp),
            "max_hp": int(hp),
            "hit_damage": 50,
            "status": "active",
            "chat_id": chat_id,
        }
        return dict(self.raid)

    async def active(self):
        return dict(self.raid) if self.raid else None

    async def get(self, boss_id: int):
        return dict(self.raid) if self.raid else None

    async def attach(self, boss_id: int, chat_id: int, message_id: int) -> None:
        return None

    async def my_hits(self, boss_id: int, user_id: int) -> dict:
        return {"hits": 0, "damage": 0}

    async def stats(self, boss_id: int) -> dict:
        return {"people": len(self.hits), "hits": len(self.hits), "damage": 0}

    async def top(self, boss_id: int, limit: int = 5) -> list[dict]:
        return []

    async def hit(self, boss_id: int, user_id: int, now):
        assert self.raid is not None
        self.hits.append((boss_id, user_id))
        damage = int(self.raid["hit_damage"])
        hp = max(0, int(self.raid["hp"]) - damage)
        self.raid["hp"] = hp
        if hp <= 0:
            self.raid["status"] = "dead"
        return {
            "cooldown": False,
            "hp": hp,
            "max_hp": int(self.raid["max_hp"]),
            "damage": damage,
            "dead": hp <= 0,
        }

    async def mark_rewarded(self, boss_id: int) -> bool:
        if self.rewarded:
            return False
        self.rewarded = True
        return True


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
    boss_repo: "FakeBossRepo | None" = None,
):
    session = FakeSession()
    bot = Bot(token="123456:TEST", session=session)
    update = Update.model_validate(build_update(text, user_id=user_id, reply=reply), context={"bot": bot})
    await dispatcher().feed_update(
        bot,
        update,
        db=db,
        service=service,
        market=market or FakeMarket(),
        boss_repo=boss_repo or FakeBossRepo(),
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
            bot,
            update,
            db=FakeDB(),
            service=FakeService(),
            market=FakeMarket(),
            boss_repo=FakeBossRepo(),
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
            bot,
            update,
            db=FakeDB(),
            service=FakeService(),
            market=FakeMarket(),
            boss_repo=FakeBossRepo(),
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

def build_callback(
    data: str, user_id: int = 111, thread_id: int | None = None, photo: bool = False
) -> dict:
    message: dict[str, Any] = {
        "message_id": 77,
        "date": 1700000000,
        "chat": {"id": user_id, "type": "private"},
        "from": {"id": 555, "is_bot": True, "first_name": "bot"},
        "text": "профиль",
    }
    if photo:
        message.pop("text", None)
        message["photo"] = [
            {"file_id": "p1", "file_unique_id": "u1", "width": 100, "height": 100}
        ]
    if thread_id is not None:
        message["message_thread_id"] = thread_id
        message["is_topic_message"] = True
    return {
        "update_id": 9,
        "callback_query": {
            "id": "cb9",
            "from": {"id": user_id, "is_bot": False, "first_name": "Тест"},
            "chat_instance": "ci",
            "data": data,
            "message": message,
        },
    }


async def feed_callback(
    data: str,
    db: FakeDB,
    market: FakeMarket,
    user_id: int = 111,
    thread_id: int | None = None,
    photo: bool = False,
    boss_repo: "FakeBossRepo | None" = None,
):
    session = FakeSession()
    bot = Bot(token="123456:TEST", session=session)
    update = Update.model_validate(
        build_callback(data, user_id, thread_id, photo), context={"bot": bot}
    )
    await dispatcher().feed_update(
        bot,
        update,
        db=db,
        service=FakeService(),
        market=market,
        boss_repo=boss_repo or FakeBossRepo(),
    )
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
        assert "pf:333:d:#oleg" in str(edits[0]), "кнопки должны вести на карты игрока 333"

        # статы конкретной чужой карты
        session = await feed_callback("pf:333:d:#oleg", db, market)
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

def test_admin_starts_clicker_and_tap_gives_a_reward():
    """Кликер: включается админом, тап что-то выдаёт."""

    async def scenario():
        db = FakeDB()
        session = await feed("/admin clicker", db, FakeService(), user_id=111)
        assert db.settings.get("clicker_live") == "1"
        markup = str(
            [p for n, p in session.calls if n == "SendMessage"][0].get("reply_markup")
        )
        assert "clicker:tap" in markup, markup

        session = await feed_callback("clicker:tap", db, FakeMarket())
        answers = [
            p.get("text", "") for n, p in session.calls if n == "AnswerCallbackQuery"
        ]
        assert answers, "тап должен что-то ответить"

    asyncio.run(scenario())


def test_clicker_tap_is_closed_when_off():
    async def scenario():
        db = FakeDB()
        await feed_callback("clicker:tap", db, FakeMarket())
        # флаг не выставлен — ничего не начисляем
        assert not db.spin_grants and not db.cases

    asyncio.run(scenario())


def test_update_word_turns_on_the_new_miniapps():
    """Рубильник обновления: срабатывает только у админа и только на слово."""

    async def scenario():
        db = FakeDB()
        session = await feed("ОБНОВЛЕНИЕ", db, FakeService(), user_id=111)
        assert db.settings.get("miniapps_live") == "1"
        assert any("ОБНОВЛЕНИЕ" in text for text in sent_texts(session))

        other = FakeDB()
        await feed("ОБНОВЛЕНИЕ", other, FakeService(), user_id=222)
        assert other.settings.get("miniapps_live") is None

    asyncio.run(scenario())


def test_case_and_roulette_switch_to_miniapps_after_update():
    async def scenario():
        db = FakeDB()
        db.settings["miniapps_live"] = "1"

        session = await feed("/case", db, FakeService())
        markup = str(
            [p for n, p in session.calls if n == "SendMessage"][0].get("reply_markup")
        )
        assert "caseapp" in markup, markup

        session = await feed("/roulette", db, FakeService())
        markup = str(
            [p for n, p in session.calls if n == "SendMessage"][0].get("reply_markup")
        )
        assert "rouletteapp" in markup, markup

    asyncio.run(scenario())


def test_admin_starts_boss_and_hits_reduce_hp():
    """Рейд-босс: админ запускает, любой тап снимает 50 HP."""

    async def scenario():
        db = FakeDB()
        repo = FakeBossRepo()
        session = await feed("/admin boss 100", db, FakeService(), boss_repo=repo)
        assert repo.raid is not None and repo.raid["hp"] == 100
        sent = [p for n, p in session.calls if n == "SendMessage"]
        assert any("Ударить" in str(p.get("reply_markup")) for p in sent), (
            "в карточке босса должна быть кнопка удара"
        )

        session = await feed_callback("boss:hit", db, FakeMarket(), boss_repo=repo)
        assert repo.raid["hp"] == 50, "один удар — минус 50 HP"
        answers = [
            p.get("text", "") for n, p in session.calls if n == "AnswerCallbackQuery"
        ]
        assert any("50" in text for text in answers)

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


def test_profile_shows_title_favorite_and_activity():
    from app.render import render_profile

    profile = {
        "user_id": 1,
        "first_name": "Тест",
        "username": None,
        "wins": 3,
        "losses": 1,
        "draws": 0,
        "kills": 5,
        "bonus_points": 100,
        "card_points": 500,
        "unique_cards": 4,
        "total_cards": 6,
        "card_kills": 2,
        "rank": 1,
        "total": 100,
        "upgraded": 1,
        "drops": 7,
        "casino_bets": 3,
        "shop_buys": 1,
        "market_deals": 2,
        "gifts_sent": 1,
        "invited": 1,
        "promos": 1,
        "favorite_card_id": "oleg",
        "favorite_kills": 2,
        "favorite_copies": 3,
    }
    text = render_profile(profile, 50)
    assert "Титул" in text
    assert "Любимая карта" in text and "Олег" in text
    assert "Чем занимался" in text
    assert "казино" in text


def test_back_from_an_art_card_sends_text_not_a_caption():
    """Регрессия: из карточки с артом «Назад» оставлял чужую картинку."""
    async def scenario():
        session = await feed_callback("my:home", FakeDB(), FakeMarket(), photo=True)
        names = [name for name, _ in session.calls]
        assert "DeleteMessage" in names, "старое фото должно убираться"
        assert "SendMessage" in names, "новый экран должен приходить текстом"

    asyncio.run(scenario())


def test_faq_drops_lists_every_rarity():
    from app.render import faq_drops

    text, keyboard = faq_drops()
    assert "Шансы выпадения" in text
    for name in (
        "Редкий",
        "Сверхредкий",
        "Эпический",
        "Мифический",
        "Легендарный",
        "Секретный",
        "Ультралегендарный",
        "Учителя",
    ):
        assert name in text, name
    assert "42.00%" in text
    assert "Кейс" in text
    callbacks = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert "fq:menu" in callbacks


def test_casino_stats_command():
    async def scenario():
        session = await feed(
            "/casinostats", FakeDB(), FakeService(), market=FakeMarket()
        )
        body = sent_texts(session)[0]
        assert "Казино" in body
        assert "Выиграно" in body and "Слито" in body
        assert "в плюсе" in body
        assert "картами" in body

    asyncio.run(scenario())


def test_casino_stats_by_explicit_argument():
    async def scenario():
        session = await feed(
            "/casinostats @friend", FakeDB(), FakeService(), market=FakeMarket()
        )
        assert "Друг" in sent_texts(session)[0]

    asyncio.run(scenario())


def test_casino_stats_argument_wins_over_reply():
    async def scenario():
        reply = {
            "message_id": 5,
            "from": {"id": 222, "is_bot": False, "first_name": "Соперник"},
            "chat": {"id": -100123, "type": "supergroup", "title": "Группа"},
            "date": 1700000000,
            "text": "я тут",
        }
        session = await feed(
            "/casinostats @friend",
            FakeDB(),
            FakeService(),
            reply=reply,
            market=FakeMarket(),
        )
        body = sent_texts(session)[0]
        assert "Друг" in body and "Соперник" not in body

    asyncio.run(scenario())


def test_casino_stats_unknown_player_is_reported():
    async def scenario():
        session = await feed(
            "/casinostats @nobody", FakeDB(), FakeService(), market=FakeMarket()
        )
        body = sent_texts(session)[0]
        assert "не найден" in body

    asyncio.run(scenario())


def test_casino_stats_via_alias():
    async def scenario():
        session = await feed(
            "/casino stats", FakeDB(), FakeService(), market=FakeMarket()
        )
        assert "Выиграно" in sent_texts(session)[0]

    asyncio.run(scenario())


def test_casino_dice_shows_choices():
    async def scenario():
        session = await feed(
            "/casino кости 10000", FakeDB(), FakeService(), market=FakeMarket()
        )
        body = sent_texts(session)[0]
        assert "Кости" in body
        payload = next(p for n, p in session.calls if n == "SendMessage")
        markup = str(payload.get("reply_markup"))
        assert "cg:dice:p:10000:even" in markup
        assert "cg:dice:p:10000:d6" in markup

    asyncio.run(scenario())


def test_dice_callback_sends_the_real_emoji(monkeypatch):
    """Колбэк костей обязан отправить анимированный 🎲 и считать по нему."""
    async def scenario():
        import app.handlers as handlers

        played: dict[str, Any] = {}

        class FakeCasinoRepo:
            def __init__(self, db: Any, market: Any) -> None:
                pass

            async def play_points(self, user_id, bet, won, multiplier, game, choice, rolled_value):
                played.update(
                    bet=bet, won=won, multiplier=multiplier, value=int(rolled_value)
                )
                return {
                    "kind": "points",
                    "bet": bet,
                    "won": won,
                    "multiplier": multiplier,
                    "payout": bet * multiplier,
                    "delta": bet * (multiplier - 1),
                    "balance": 1_000_000,
                    "game": game,
                    "choice": choice,
                    "rolled": int(rolled_value),
                }

            async def play_card(self, *args: Any, **kwargs: Any):
                raise AssertionError("карта тут не ставится")

        monkeypatch.setattr(handlers, "CasinoRepo", FakeCasinoRepo)
        # в тесте не ждём анимацию кубика
        monkeypatch.setattr(handlers.dice_casino, "DICE_PAUSE_SECONDS", 0)
        session = await feed_callback(
            "cg:dice:p:10000:d5", FakeDB(), FakeMarket(), thread_id=42
        )
        names = [name for name, _ in session.calls]
        assert "SendDice" in names, names
        dice_call = next(p for n, p in session.calls if n == "SendDice")
        assert dice_call.get("message_thread_id") == 42, "кубик летит в тот же топик"
        assert played["value"] == 5, "результат берём из кубика"
        assert played["won"] is True and played["multiplier"] == 3
        assert any(name == "EditMessageText" for name in names)

    asyncio.run(scenario())


def test_ref_creates_a_personal_link():
    async def scenario():
        session = await feed("/ref", FakeDB(), FakeService())
        body = sent_texts(session)[0]
        assert "t.me/" in body and "start=ref_" in body

    asyncio.run(scenario())


def test_referral_flow_end_to_end():
    """Полная симуляция: /ref -> друг открывает ссылку -> инвайтеру +1 попытка."""
    async def scenario():
        db = FakeDB()
        session = await feed("/ref", db, FakeService(), user_id=1)
        body = sent_texts(session)[0]
        found = re.search(r"start=(ref_[A-Za-z0-9_]+)", body)
        assert found, body
        payload = found.group(1)
        assert db.ref_links, "ссылка сохранена"

        before = len(db.drop_grants)
        session2 = await feed(f"/start {payload}", db, FakeService(), user_id=2)
        assert db.referrals == {2: 1}, "друг привязан к пригласившему"
        assert len(db.drop_grants) == before + 1
        assert db.drop_grants[-1] == (1, 1), "награда ушла пригласившему"
        notified = [
            p.get("chat_id")
            for n, p in session2.calls
            if n == "SendMessage" and p.get("chat_id") == 1
        ]
        assert notified, "пригласивший получил уведомление"

        # повторный переход от того же друга награду не даёт
        await feed(f"/start {payload}", db, FakeService(), user_id=2)
        assert len(db.drop_grants) == before + 1

    asyncio.run(scenario())


def test_ref_reuses_the_weekly_link():
    async def scenario():
        db = FakeDB()
        await feed("/ref", db, FakeService(), user_id=1)
        await feed("/ref", db, FakeService(), user_id=1)
        assert len(db.ref_links) == 1, "вторую ссылку за неделю не создаём"

    asyncio.run(scenario())


def test_referral_link_stops_at_25_people():
    async def scenario():
        db = FakeDB()
        await feed("/ref", db, FakeService(), user_id=1)
        code = next(iter(db.ref_links))
        for friend in range(2, 29):  # 27 друзей при лимите 25
            await feed(f"/start ref_{code}", db, FakeService(), user_id=friend)
        assert db.ref_links[code]["uses"] == 25
        assert len(db.referrals) == 25
        assert db.ref_links[code]["active"] is False

    asyncio.run(scenario())


def test_promo_with_a_space_in_the_code():
    """Код «северо юн» состоит из двух слов: /promo должен склеивать аргументы."""
    async def scenario():
        session = await feed("/promo северо юн", FakeDB(), FakeService())
        assert "Промокод принят" in sent_texts(session)[0]

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
