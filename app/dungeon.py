"""Кооп-босс подземелья: правила боя без базы.

Один босс на двоих. Игрок стоит на точке 10 секунд — комната открывается,
второй игрок в той же локации присоединяется к ней, дальше общий HP босса
и удары по кнопке.

Прототип: награды в экономику не пишутся, страница /proto_dungeon живёт
отдельно от базы. Здесь только математика, вся работа с БД — в dungeon_repo.
"""

from __future__ import annotations

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
BASE_HP = 300               # HP босса в первой локации для одного
IDLE_SECONDS = 20.0         # столько комната живёт без заглядываний
MAX_DAMAGE = 400            # защита от абсурда из запроса
MIN_DAMAGE = 1


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


def base_hp(zone: int, players: int = 1) -> int:
    """HP босса: растёт по локациям и ещё раз — если бьются двое."""
    return int(round(BASE_HP * zone_factor(zone) * hp_factor(players)))


def boss_damage(zone: int) -> int:
    """Сколько снимает босс за один свой удар."""
    return int(round(5 + clamp_zone(zone) * 3))


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
