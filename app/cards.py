"""Каталог карт «Северо-Юг».

32 карты. Имена повторяются (два Амира, два Данияра, два Тамерлана),
поэтому уникальный идентификатор — slug card_id, а не имя.

Урон НЕ зависит от редкости и от очков: редкость влияет только на внешний
вид, очки — только на счёт коллекции. У каждой карты свои HP, свой базовый
урон и своя уникальная способность. Сила карт сбалансирована: budget()
(HP + 10*ATK) держится в узком коридоре, а способности компенсируют разницу.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------- #
# Редкости и веса выпадения
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Rarity:
    key: str
    name: str
    weight: float
    emoji: str


RARITIES: dict[str, Rarity] = {
    "rare": Rarity("rare", "Редкий", 0.400, "⚪"),
    "superrare": Rarity("superrare", "Сверхредкий", 0.290, "🔵"),
    "epic": Rarity("epic", "Эпический", 0.200, "🟣"),
    "mythic": Rarity("mythic", "Мифический", 0.080, "🔴"),
    "legendary": Rarity("legendary", "Легендарный", 0.020, "🟡"),
    "secret": Rarity("secret", "Секретный", 0.007, "⚫"),
    "ultra": Rarity("ultra", "Ультралегендарный", 0.003, "🌈"),
}

RARITY_ORDER: tuple[str, ...] = (
    "ultra",
    "secret",
    "legendary",
    "mythic",
    "epic",
    "superrare",
    "rare",
)


def rarity_name(key: str) -> str:
    return RARITIES[key].name


# --------------------------------------------------------------------------- #
# Карты
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Ability:
    """Уникальная способность карты.

    effects — словарь с ключами движка (см. app/battle.py):
      damage / hits / ignore_shield — урон (по удару, число ударов)
      steal      — снять HP у цели и вылечить себя на столько же
      heal       — лечение себя
      shield     — щит себе (поглощает урон)
      poison / poison_turns — яд на цель
      stun       — оглушение цели (пропуск хода)
      silence    — цель не может использовать способность
      dodge      — уклонение себе (сколько атак пропустить)
      counter / counter_turns — контрудар по атакующему
      weaken / weaken_turns   — снижение урона цели
      cleanse    — снять с себя яд/оглушение/немоту/ослабление
      self_stun  — расплата: свой следующий ход пропускается
    """

    name: str
    cooldown: int
    effects: dict[str, Any]


@dataclass(frozen=True)
class Card:
    card_id: str
    name: str
    rarity: str
    points: int
    hp: int
    atk: int
    ability: Ability

    @property
    def budget(self) -> int:
        """Приблизительная боевая мощь: HP + 10*ATK."""
        return self.hp + self.atk * 10

    @property
    def rarity_title(self) -> str:
        return RARITIES[self.rarity].name

    @property
    def rarity_emoji(self) -> str:
        return RARITIES[self.rarity].emoji


def _c(
    card_id: str,
    name: str,
    rarity: str,
    points: int,
    hp: int,
    atk: int,
    ability: str,
    cooldown: int,
    **effects: Any,
) -> Card:
    return Card(
        card_id=card_id,
        name=name,
        rarity=rarity,
        points=points,
        hp=hp,
        atk=atk,
        ability=Ability(name=ability, cooldown=cooldown, effects=effects),
    )


CARDS: tuple[Card, ...] = (
    # --- Легендарный (3) ---
    _c("daniel", "Даниэль", "legendary", 10000, 110, 10, "Архангел", 2, heal=15, damage=8),
    _c("rustam", "Рустам", "legendary", 12000, 115, 11, "Богатырский замах", 3, damage=20),
    _c("konstantin", "Константин", "legendary", 9000, 110, 10, "Императорский суд", 2, damage=12, heal=12),
    # --- Мифический (8) ---
    _c("rafael", "Рафаэль", "mythic", 5000, 105, 9, "Исцеляющий свет", 3, heal=20, cleanse=True),
    _c("tamerlan_mif", "Тамерлан", "mythic", 7500, 110, 9, "Железные стены", 2, shield=25),
    _c("daniyar_mif", "Данияр", "mythic", 6500, 100, 10, "Контрудар", 2, shield=10, damage=10),
    _c("amaliya", "Амалия", "mythic", 5000, 95, 9, "Чародейский щит", 3, shield=20, cleanse=True),
    _c("arina", "Арина", "mythic", 5000, 95, 10, "Прозрение", 3, damage=12, dodge=1),
    _c("glafira", "Глафира", "mythic", 7500, 100, 9, "Благословение", 3, heal=25),
    _c("trofim", "Трофим", "mythic", 7500, 110, 9, "Лесная хватка", 3, damage=10, silence=1),
    _c("emin", "Эмин", "mythic", 6500, 100, 10, "Гром", 2, damage=15, poison=5, poison_turns=1),
    # --- Секретный (2) ---
    _c("amiliya_secret", "Амилия", "secret", 11000, 100, 10, "Тайный ритуал", 2, steal=15),
    _c("timur_secret", "Тимур", "secret", 11000, 115, 12, "Завоеватель", 3, damage=20, self_stun=1),
    # --- Ультралегендарный (1) ---
    _c("valeriya", "Валерия", "ultra", 15000, 120, 12, "Абсолют", 4, damage=25),
    # --- Эпический (10) ---
    _c("azat", "Азат", "epic", 3000, 100, 11, "Ярость", 2, damage=15),
    _c("ravil", "Равиль", "epic", 4000, 100, 10, "Кровопийца", 2, damage=10, heal=10),
    _c("masha", "Маша", "epic", 3000, 105, 12, "Медвежья сила", 3, damage=18),
    _c("amir_1", "Амир", "epic", 5000, 95, 10, "Песчаная буря", 2, damage=8, poison=6, poison_turns=2),
    _c("amir_2", "Амир", "epic", 5000, 95, 11, "Клинок ветра", 2, damage=8, hits=2),
    _c("yana", "Яна", "epic", 5000, 90, 10, "Очарование", 3, damage=6, stun=1),
    _c("daniyar_epic", "Данияр", "epic", 3500, 105, 9, "Стойкость", 3, shield=15, heal=10),
    _c("milana", "Милана", "epic", 2500, 88, 9, "Грация", 3, dodge=1, counter=10, counter_turns=2),
    _c("evelina", "Эвелина", "epic", 3500, 92, 10, "Вихрь", 2, damage=6, poison=4, poison_turns=2),
    _c("tamerlan_epic", "Тамерлан", "epic", 4000, 105, 11, "Натиск", 2, damage=14, shield=6),
    # --- Сверхредкий (4) ---
    _c("elizaveta", "Елизавета", "superrare", 2000, 95, 11, "Имперский указ", 3, stun=1),
    _c("evita", "Эвита", "superrare", 1000, 88, 9, "Танец", 3, damage=8, dodge=1),
    _c("elen", "Элен", "superrare", 1000, 92, 9, "Лунный свет", 3, heal=15, shield=10),
    _c("amelia", "Амелия", "superrare", 2500, 95, 9, "Милосердие", 3, heal=20, cleanse=True),
    # --- Редкий (4) ---
    _c("karina", "Карина", "rare", 500, 90, 9, "Точный удар", 2, damage=10, ignore_shield=True),
    _c("kamila", "Камила", "rare", 500, 90, 10, "Двойной выстрел", 2, damage=7, hits=2),
    _c("egor", "Егор", "rare", 500, 90, 9, "Разведка", 3, damage=8, weaken=5, weaken_turns=2),
    _c("oleg", "Олег", "rare", 250, 95, 10, "Простой мужик", 2, damage=12),
)

CARDS_BY_ID: dict[str, Card] = {card.card_id: card for card in CARDS}

CARDS_BY_RARITY: dict[str, tuple[Card, ...]] = {
    key: tuple(card for card in CARDS if card.rarity == key) for key in RARITIES
}

# Редкости в порядке возрастания «крутости» — для сортировки коллекции.
SORTED_RARITY_INDEX: dict[str, int] = {key: i for i, key in enumerate(reversed(RARITY_ORDER))}


def get_card(card_id: str) -> Card:
    return CARDS_BY_ID[card_id]


def cards_sorted_for_user(card_ids: list[str] | set[str]) -> list[Card]:
    """Карты пользователя: от самой редкой к обычной, внутри — по очкам."""
    return sorted(
        (CARDS_BY_ID[cid] for cid in card_ids if cid in CARDS_BY_ID),
        key=lambda c: (-SORTED_RARITY_INDEX[c.rarity], -c.points, c.name),
    )

def card_rows() -> list[tuple[object, ...]]:
    """Строки для upsert в таблицу cards."""
    import json

    return [
        (
            card.card_id,
            card.name,
            card.rarity,
            card.points,
            card.hp,
            card.atk,
            card.ability.name,
            card.ability.cooldown,
            json.dumps(card.ability.effects, ensure_ascii=False),
        )
        for card in CARDS
    ]
