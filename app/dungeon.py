"""Кооп-босс подземелья: правила боя без базы.

Один босс на двоих. Игрок стоит на точке 10 секунд — комната открывается,
второй игрок в той же локации присоединяется к ней, дальше общий HP босса
и удары по кнопке.

Прототип: награды в экономику не пишутся, страница /proto_dungeon живёт
отдельно от базы. Здесь только математика, вся работа с БД — в dungeon_repo.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

# Названия и множители совпадают с ZONES на странице /proto_dungeon.
ZONES: tuple[tuple[str, float], ...] = (
    ("Опушка", 1.0),
    ("Дубовая роща", 1.3),
    ("Болото", 1.7),
    ("Каменный перевал", 2.2),
    ("Пепельный лес", 2.8),
    ("Костяные поля", 3.4),
    ("Багровые шахты", 4.1),
    ("Ледяные залы", 4.9),
    ("Тёмный алтарь", 5.8),
    ("Бездна", 7.0),
)

WAIT_SECONDS = 10.0         # сколько ждём второго игрока на точке
JOIN_GRACE = 20.0           # столько после старта ещё можно подсесть в бой
MAX_PLAYERS = 2             # один босс на двоих — больше не пускаем
PLAYER_HP = 120             # столько же, сколько у героя на странице
BOSS_HIT_EVERY = 2.0        # босс бьёт раз в две секунды
HIT_COOLDOWN = 0.55         # игрок не чаще двух ударов в секунду
COOP_HP_FACTOR = 1.8        # на двоих боссу больше HP
BASE_HP = 600               # HP босса в первой локации для одного
IDLE_SECONDS = 20.0         # столько комната живёт без заглядываний
MAX_DAMAGE = 400            # защита от абсурда из запроса
MIN_DAMAGE = 1

# --- оружие: без тиров, урон по рангу и капу локации -----------------
# Страница генерирует 3 вида x 10 рангов x 5 вариантов = 150 стволов,
# у каждого своё имя ("Пламенный Ятаган"). Урон считается от ранга, а
# локация ограничивает, что вообще может выпасть: в Опушке — до 40,
# в Бездне — до 400. Поэтому имбовый ствол в начале не выпадет физически.
WEAPON_KINDS = ("sword", "bow", "staff")
MOB_DROP_CHANCE = 0.05

# сколько урона даёт ранг (0..9) и его варианты (0..4)
WEAPON_RANK_DMG = (10, 22, 36, 52, 72, 96, 128, 168, 220, 300)
WEAPON_RANK_STEP = (2, 3, 4, 5, 6, 8, 10, 12, 15, 25)

# потолок урона по локациям 1..10 и HP мобов там же
ZONE_DMG_CAP = (40, 55, 75, 100, 130, 170, 215, 265, 320, 400)
ZONE_MOB_HP = (250, 500, 1_000, 1_350, 2_000, 2_500, 3_000, 3_500, 4_500, 10_000)


def weapon_dmg(rank: int, variant: int) -> int:
    """Урон ствола по рангу и варианту — та же формула, что на странице."""
    rank = max(0, min(9, int(rank)))
    variant = max(0, min(4, int(variant)))
    return WEAPON_RANK_DMG[rank] + variant * WEAPON_RANK_STEP[rank]


def zone_cap(zone: int) -> int:
    return ZONE_DMG_CAP[max(0, min(9, int(zone)))]


def zone_mob_hp(zone: int) -> int:
    return ZONE_MOB_HP[max(0, min(9, int(zone)))]

BOSS_COINS = 120            # награда за босса в первой локации
COOP_COIN_BONUS = 1.5       # вдвоём — больше
CHAT_COOLDOWN = 1.2         # секунд между сообщениями чата
CHAT_MAX = 80               # символов в сообщении


def zone_count() -> int:
    return len(ZONES)


def clamp_zone(value: object) -> int:
    """Любой мусор из запроса превращается в номер существующей локации."""
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(zone_count() - 1, number))


def zone_name(zone: int) -> str:
    return ZONES[clamp_zone(zone)][0]


def zone_factor(zone: int) -> float:
    return ZONES[clamp_zone(zone)][1]


def clamp_damage(value: object) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return MIN_DAMAGE
    return max(MIN_DAMAGE, min(MAX_DAMAGE, number))


def hp_factor(players: int) -> float:
    return COOP_HP_FACTOR if int(players) > 1 else 1.0


QUEST_HOUR = 3600


def quest_for(user_id: int, level: int, moment: datetime) -> dict:
    """Квест НПС на текущий час: детерминирован по (игрок, час).

    Час назад был один квест, сейчас другой — и он не меняется, сколько
    бы раз игрок ни обновил страницу.
    """
    hour_key = int(moment.timestamp()) // QUEST_HOUR
    digest = hashlib.sha256(("quest:%d:%d" % (int(user_id), hour_key)).encode()).digest()
    level = max(1, int(level or 1))
    zone = max(0, min(9, level // 3))
    kind = "boss" if digest[0] % 4 == 0 else "hunt"
    if kind == "hunt":
        need = min(12, 3 + level // 4)
    else:
        need = 1
    coins = 60 + zone * 80 + (needed_bonus(kind, need))
    xp = 100 + zone * 120
    return {
        "hour": hour_key,
        "kind": kind,
        "zone": zone,
        "zone_name": ZONES[zone][0],
        "need": need,
        "coins": int(coins),
        "xp": int(xp),
        "expires_in": int(QUEST_HOUR - (int(moment.timestamp()) % QUEST_HOUR)),
    }


def needed_bonus(kind: str, need: int) -> int:
    return 120 if kind == "boss" else need * 15


def quest_text(quest: dict) -> str:
    """Что НПС просит словами."""
    if quest.get("kind") == "boss":
        return "убить босса в «%s»" % quest.get("zone_name", "?")
    return "убить %d мобов в «%s»" % (int(quest.get("need", 1)),
                                      quest.get("zone_name", "?"))


def base_hp(zone: int, players: int = 1) -> int:
    """HP босса: в глубине больше пяти тысяч, вдвоём — ещё выше."""
    hp = BASE_HP + 900 * max(0, int(zone))
    return int(round(hp * hp_factor(players)))


def boss_damage(zone: int) -> int:
    """Сколько снимает босс за один свой удар."""
    return int(round(5 + clamp_zone(zone) * 3))


# Броня за Юги (валюта кликера). Цена базовая x 1.5^перерождения,
# снимает 4% урона босса за уровень.
ARMOR_BASE = 500
ARMOR_MAX = 10
ARMOR_STEP = 0.04
RESET_MULT = 1.5


def _clamp_int(value: object, low: int, high: int) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return low
    return max(low, min(high, number))


def armor_discount(armor: object) -> float:
    """Доля, на которую броня срезает урон босса (0..0.4)."""
    return round(_clamp_int(armor, 0, ARMOR_MAX) * ARMOR_STEP, 4)


def armor_price(armor: object, resets: object = 0) -> int | None:
    """Сколько Югов стоит следующая броня. None — уже максимум."""
    level = _clamp_int(armor, 0, ARMOR_MAX)
    if level >= ARMOR_MAX:
        return None
    return int(round(ARMOR_BASE * (level + 1) * (RESET_MULT ** _clamp_int(resets, 0, 50))))


def armor_offer(armor: object, resets: object = 0) -> dict | None:
    price = armor_price(armor, resets)
    if price is None:
        return None
    level = _clamp_int(armor, 0, ARMOR_MAX)
    return {
        "price": price,
        "level": level,
        "next": level + 1,
        "discount": armor_discount(level),
        "next_discount": armor_discount(level + 1),
    }


def boss_yugi(zone: int) -> int:
    """Сколько Югов падает за босса: связка кликера и подземелья."""
    return max(5, int(round(BOSS_COINS * zone_factor(zone) / 12)))


def boss_weapon(seed: int, zone: int = 0) -> str:
    """Оружие с босса: из лучших стволов, доступных в этой локации.

    Детерминировано по seed (комната + игрок), чтобы не менялось при
    повторных запросах статуса боя.
    """
    cap = zone_cap(zone)
    floor = cap * 0.8
    pool = [
        (rank, variant)
        for rank in range(10)
        for variant in range(5)
        if floor <= weapon_dmg(rank, variant) <= cap
    ]
    if not pool:
        pool = [(0, 0)]
    digest = hashlib.sha256(str(int(seed)).encode()).digest()
    rank, variant = pool[int.from_bytes(digest[:4], "big") % len(pool)]
    kind = WEAPON_KINDS[int.from_bytes(digest[4:6], "big") % len(WEAPON_KINDS)]
    return "%s_%d_%d" % (kind, rank, variant)


def boss_reward(zone: int, players: int = 1) -> dict:
    """Награда за победу: монеты и зачёт убийства.

    Начисляет клиент (он же хозяин прогресса героя), а число приходит с
    сервера — чтобы за двоих платили честно и одинаково.
    """
    coins = int(round(BOSS_COINS * zone_factor(zone) * (COOP_COIN_BONUS if players > 1 else 1.0)))
    return {"coins": max(1, coins), "kills": 1, "yugi": boss_yugi(zone)}


def ticks_since(last: datetime | None, now: datetime, every: float = BOSS_HIT_EVERY) -> int:
    """Сколько ударов босс успел нанести с прошлого раза."""
    if last is None:
        return 0
    if every <= 0:
        return 0
    seconds = (now - last).total_seconds()
    if seconds <= 0:
        return 0
    return int(seconds // every)


def next_tick_at(last: datetime | None, ticks: int, every: float = BOSS_HIT_EVERY) -> datetime | None:
    """Сдвигаем расписание, чтобы фаза ударов не уезжала от опроса."""
    if last is None:
        return None
    return last + timedelta(seconds=max(0, int(ticks)) * every)


def cooldown_left(last_hit: datetime | None, now: datetime) -> float:
    """Сколько ещё ждать до следующего удара игрока."""
    if last_hit is None:
        return 0.0
    left = HIT_COOLDOWN - (now - last_hit).total_seconds()
    return max(0.0, min(HIT_COOLDOWN, left))


def ready_in(ready_at: datetime | None, now: datetime) -> int:
    """Секунды до конца ожидания; 0 — уже можно драться."""
    if ready_at is None:
        return 0
    return max(0, int(round((ready_at - now).total_seconds())))


def zone_lock(zone: int) -> int:
    """Ключ advisory-блокировки на локацию.

    Два игрока ждут на точке ровно 10 секунд и нажимают «в бой» почти
    одновременно. Без блокировки оба не видят комнату друг друга и создают
    по своей — каждый дерётся один.
    """
    return 9_100_000 + clamp_zone(zone)


def room_is_open(status: str) -> bool:
    """В такой бой ещё можно зайти или его надо опрашивать."""
    return status in ("waiting", "fight")


def status_text(status: str) -> str:
    return {
        "waiting": "ждём второго",
        "fight": "бой",
        "dead": "босс повержен",
        "failed": "все пали",
        "closed": "комната закрыта",
        "none": "боя нет",
    }.get(status, status)
