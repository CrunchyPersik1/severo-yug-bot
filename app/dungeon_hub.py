"""Кто где стоит в подземелье: реестр позиций в памяти процесса.

Позиции не пишутся в базу: на Render один процесс и один воркер, а опрос
каждые 0.6 секунды превращался в лишние запросы на каждый такт. Здесь всё
живёт в памяти: страница присылает свою точку, получает чужие.

Транспорта два:
  * WebSocket /ws/dungeon — по умолчанию, 10 тактов в секунду;
  * POST /api/dungeon/presence — запасной путь, если сокет не поднялся.

Метка живёт TTL_SECONDS без обновления: закрыл вкладку — пропал с карты.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

TTL_SECONDS = 6.0        # дольше этого точку не показываем
MAX_REMOTE = 24          # больше в кадр всё равно не влезет
MAX_COORD = 4000.0       # ширина мира — экран, высота 11 000
ANIMS = ("idle", "run", "attack")
WEAPONS = ("sword", "bow", "staff")


def clamp_coord(value: object, limit: float = MAX_COORD) -> float:
    """Любой мусор — в ноль, иначе в границы мира."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    if number != number or number in (float("inf"), float("-inf")):
        return 0.0
    return max(0.0, min(limit, number))


def clamp_int(value: object, low: int, high: int) -> int:
    try:
        number = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return low
    return max(low, min(high, number))


def clamp_anim(value: object) -> str:
    text = str(value or "").lower()
    return text if text in ANIMS else "idle"


def clamp_weapon(value: object) -> str:
    text = str(value or "").lower()
    return text if text in WEAPONS else "sword"


def fresh(seen: float, now: float, ttl: float = TTL_SECONDS) -> bool:
    return (now - seen) <= ttl


@dataclass
class Spot:
    """Одна точка на карте: кто, где, что делает."""

    user_id: int
    name: str
    zone: int
    x: float
    y: float
    facing: int
    anim: str
    hp: int
    max_hp: int
    weapon: str
    seen: float

    def payload(self) -> dict:
        return {
            "id": self.user_id,
            "name": self.name,
            "zone": self.zone,
            "x": round(self.x, 1),
            "y": round(self.y, 1),
            "facing": self.facing,
            "anim": self.anim,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "weapon": self.weapon,
        }


class DungeonHub:
    """Реестр позиций. Один на процесс, потоков не касается (только asyncio)."""

    def __init__(self) -> None:
        self._spots: dict[int, Spot] = {}

    def __len__(self) -> int:
        return len(self._spots)

    def touch(
        self, user_id: int, name: str, payload: dict, now: float | None = None
    ) -> Spot:
        moment = time_now() if now is None else now
        spot = Spot(
            user_id=int(user_id),
            name=str(name or "Игрок")[:32],
            zone=clamp_int(payload.get("zone"), 0, 9),
            x=clamp_coord(payload.get("x")),
            y=clamp_coord(payload.get("y"), 20000.0),
            facing=clamp_int(payload.get("facing"), 0, 3),
            anim=clamp_anim(payload.get("anim")),
            hp=clamp_int(payload.get("hp"), 0, 1_000_000),
            max_hp=clamp_int(payload.get("max_hp"), 0, 1_000_000),
            weapon=clamp_weapon(payload.get("weapon")),
            seen=moment,
        )
        self._spots[spot.user_id] = spot
        return spot

    def snapshot(
        self, user_id: int, zone: int | None = None, now: float | None = None
    ) -> list[dict]:
        """Чужие точки рядом: соседние локации, свежие, себя не показываем."""
        moment = time_now() if now is None else now
        mine = self._spots.get(int(user_id))
        base_zone = mine.zone if (zone is None and mine is not None) else (
            clamp_int(zone, 0, 9) if zone is not None else 0
        )
        result: list[dict] = []
        for spot in sorted(self._spots.values(), key=lambda s: s.seen, reverse=True):
            if spot.user_id == int(user_id):
                continue
            if not fresh(spot.seen, moment):
                continue
            if abs(spot.zone - base_zone) > 1:
                continue
            result.append(spot.payload())
            if len(result) >= MAX_REMOTE:
                break
        return result

    def drop(self, user_id: int) -> None:
        self._spots.pop(int(user_id), None)

    def prune(self, now: float | None = None) -> int:
        """Выкидывает протухшие точки; возвращает, сколько убрали."""
        moment = time_now() if now is None else now
        gone = [uid for uid, spot in self._spots.items() if not fresh(spot.seen, moment)]
        for uid in gone:
            self._spots.pop(uid, None)
        return len(gone)


def time_now() -> float:
    return datetime.now(timezone.utc).timestamp()


def stale_before(now: datetime, ttl: float = TTL_SECONDS) -> datetime:
    return now - timedelta(seconds=ttl)
