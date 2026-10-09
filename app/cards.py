"""Каталог карт «Северо-Юг».

Сезон 3, школьно-осенний. Коричневая редкость «Учителя» — сезонное
событие. Шкала боя: базовая карта около 600 HP и 40 урона, способности
учеников — до 50. Учителя крепче (850–920 HP) и бьют способностью на
120–170, у каждого своя роль из общего набора эффектов.

У каждой карты свой характер: танки с большим HP и слабым ударом,
стеклянные пушки с малым HP и злым уроном, лекари, контроллеры и
уклонисты. Имена повторяются (два Амира, два Данияра, два Тамерлана),
поэтому уникальный идентификатор — slug card_id, а не имя.

ВАЖНО: пять сюжетных («стабильных») карт добавит владелец в субботу —
места под них помечены ниже, выдумывать их не нужно.
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
    "rare": Rarity("rare", "Редкий", 0.4200, "⚪"),
    "superrare": Rarity("superrare", "Сверхредкий", 0.3025, "🔵"),
    "epic": Rarity("epic", "Эпический", 0.1800, "🟣"),
    "mythic": Rarity("mythic", "Мифический", 0.0700, "🔴"),
    "legendary": Rarity("legendary", "Легендарный", 0.0150, "🟡"),
    "secret": Rarity("secret", "Секретный", 0.0100, "⚫"),
    "ultra": Rarity("ultra", "Ультралегендарный", 0.0005, "🌈"),
    "teacher": Rarity("teacher", "Учителя", 0.0020, "🟤"),
}

RARITY_ORDER: tuple[str, ...] = (
    "teacher",
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
      heal       — лечение
      shield     — щит (поглощает урон)
      poison / poison_turns — яд на цель
      stun       — оглушение цели (пропуск хода)
      silence    — цель не может использовать способность
      dodge      — уклонение себе (сколько атак пропустить)
      counter / counter_turns — контрудар по атакующему
      weaken / weaken_turns   — снижение урона цели
      cleanse    — снять с себя яд/оглушение/немоту/ослабление
      self_stun  — расплата: свой следующий ход пропускается
      drain      — вечная утечка HP в свою пользу
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
    # Фамилия нужна только там, где имена совпадают (два Тамерлана и т.д.)
    surname: str | None = None
    # Короткая фраза о персонаже — показывается в карточке, FAQ и магазине.
    description: str | None = None

    @property
    def display_name(self) -> str:
        return f"{self.name} {self.surname}" if self.surname else self.name

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
    surname: str | None = None,
    description: str | None = None,
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
        surname=surname,
        description=description,
    )


CARDS: tuple[Card, ...] = (
    # ======================================================================= #
    # УЧИТЕЛЯ (13) — сезонное событие, коричневая редкость
    # Сезон 3: учителя перестали быть «одним ударом на 100» — у каждого своя
    # роль и своя способность из общего набора движка. Обычный удар теперь
    # сопоставим с учениками, а способность бьёт больно и по-разному.
    # ======================================================================= #
    _c("irina_val", "Ирина Валерьевна", "teacher", 45000, 860, 44, "Классный час", 3,
       description="Классная руководительница", damage=120, silence=1),
    _c("filaria", "Филария Талгатовна", "teacher", 40000, 860, 44, "Историческая справка", 3,
       description="Лучшая историчка", damage=140, weaken=25, weaken_turns=2),
    _c("guzel", "Гузель Ахметовна", "teacher", 50000, 850, 45, "Диктант", 3,
       description="Русичка", damage=135, stun=1),
    _c("dilara", "Дилара Галимовна", "teacher", 38000, 850, 46, "Эстафета", 3,
       description="Учитель физкультуры", damage=70, hits=2, dodge=1),
    _c("nasima", "Насима Зуфаровна", "teacher", 47000, 870, 38, "Биологический яд", 3,
       description="Биологичка", poison=30, poison_turns=3, drain=6),
    _c("elmira_rad", "Эльмира Радиковна", "teacher", 55000, 840, 47, "Резвый наскок", 2,
       description="Башкирёнок", damage=60, hits=2, steal=20),
    _c("mikhail_nik", "Михаил Николаевич", "teacher", 42000, 870, 36, "Тёплое течение", 3,
       description="Учитель географии · М + Г = ❤️", heal=55, shield=35),
    _c("natalya_nik", "Наталья Николаевна", "teacher", 39000, 890, 42, "Системный сбой", 4,
       description="Главная в школе, информатичка", damage=160, silence=1, stun=1),
    _c("ilgiz", "Ильгиз Винерович", "teacher", 41000, 900, 40, "Кросс", 3,
       description="Учитель физкультуры", counter=35, counter_turns=2, dodge=1),
    _c("gulsum", "Гульсум Муратовна", "teacher", 36000, 880, 30, "Курай", 3,
       description="Башкирёнок", heal=70, cleanse=True),
    _c("elvira", "Эльвира Хасановна", "teacher", 35000, 900, 34, "Стаж 40 лет", 4,
       description="Старый учитель", damage=150, shield=40),
    _c("valeriy_akr", "Валерий Акрамович", "teacher", 43000, 880, 48, "Контрольная работа", 3,
       description="Математик", damage=130, ignore_shield=True),
    # секретка по промокоду OCEHb — в магазине её нет
    _c("elmira_secret", "Эльмира Ракидовна", "teacher", 60000, 920, 52, "Строгий выговор", 3,
       description="Завуч — только за промокод", damage=170, stun=1, heal=40),

    # ======================================================================= #
    # ЛЕГЕНДАРНЫЙ (3)
    # ======================================================================= #
    _c("daniel", "Даниэль", "legendary", 10000, 700, 36, "Архангел", 2, damage=18, heal=35),
    _c("rustam", "Рустам", "legendary", 12000, 680, 48, "Богатырский замах", 3, damage=45),
    _c("konstantin", "Константин", "legendary", 9000, 660, 42, "Императорский суд", 2, damage=26, heal=26),

    # ======================================================================= #
    # МИФИЧЕСКИЙ (11, включая три новые)
    # ======================================================================= #
    _c("rafael", "Рафаэль", "mythic", 5000, 640, 34, "Исцеляющий свет", 3, heal=45, cleanse=True),
    _c("tamerlan_mif", "Тамерлан", "mythic", 7500, 760, 32, "Железные стены", 2, surname="Гиндуллин", shield=55),
    _c("daniyar_mif", "Данияр", "mythic", 6500, 620, 42, "Контрудар", 2, surname="Жайлибаев", shield=20, damage=22),
    _c("amaliya", "Амалия", "mythic", 5000, 600, 34, "Чародейский щит", 3, shield=45, cleanse=True),
    _c("arina", "Арина", "mythic", 5000, 580, 44, "Прозрение", 3, damage=26, dodge=1),
    _c("glafira", "Глафира", "mythic", 7500, 640, 34, "Благословение", 3,
       description="Влюблена в Михаила Николаевича ❤️", heal=60),
    _c("trofim", "Трофим", "mythic", 7500, 680, 34, "Удушающая", 3, damage=26, silence=1),
    _c("emin", "Эмин", "mythic", 6500, 620, 40, "Словесное исцеление", 2, steal=18, drain=2),
    # --- новые карты, продаются паками в магазине ---
    _c("misya", "Мися", "mythic", 8000, 650, 40, "Мурлыканье", 3, heal=38, cleanse=True),
    _c("misha", "Миша", "legendary", 10000, 680, 46, "Дружеский подкат", 3, damage=30, shield=20),

    # ======================================================================= #
    # СЕКРЕТНЫЙ (5)
    # ======================================================================= #
    _c("amiliya_secret", "Амилия", "secret", 11000, 600, 40, "Тайный ритуал", 2, steal=32),
    _c("timur_secret", "Тимур", "secret", 11000, 640, 56, "Завоеватель", 3, damage=45, self_stun=1),
    _c("daniel_sult", "Даниэль Султангулов", "secret", 11000, 620, 40, "Султанский приказ", 3, damage=22, stun=1),
    _c("saida", "Саида", "secret", 11000, 660, 38, "Восточная мудрость", 3, heal=45, cleanse=True),
    _c("artem", "Артём", "secret", 11000, 580, 46, "Двойной удар", 2, damage=20, hits=2),

    # ======================================================================= #
    # УЛЬТРАЛЕГЕНДАРНЫЙ (1)
    # ======================================================================= #
    _c("valeriya", "Валерия", "ultra", 15000, 740, 50, "Абсолют", 4, damage=50),

    # ======================================================================= #
    # ЭПИЧЕСКИЙ (10)
    # ======================================================================= #
    _c("azat", "Азат", "epic", 3000, 600, 48, "Ярость", 2, damage=32),
    _c("ravil", "Равиль", "epic", 4000, 620, 40, "Кровопийца", 2, damage=22, heal=22),
    _c("masha", "Маша", "epic", 3000, 680, 46, "Медвежья сила", 3, damage=38),
    _c("amir_1", "Амир", "epic", 5000, 560, 40, "Песчаная буря", 2, surname="Насибуллин", damage=16, poison=14, poison_turns=2),
    _c("amir_2", "Амир", "epic", 5000, 580, 44, "Клинок ветра", 2, surname="Нугуманов", damage=18, hits=2),
    _c("yana", "Яна", "epic", 5000, 540, 38, "Очарование", 3, damage=12, stun=1),
    _c("daniyar_epic", "Данияр", "epic", 3500, 700, 34, "Стойкость", 3, surname="Садыков", shield=35, heal=20),
    _c("milana", "Милана", "epic", 2500, 520, 36, "Грация", 3, dodge=1, counter=25, counter_turns=2),
    _c("evelina", "Эвелина", "epic", 3500, 560, 42, "Вихрь", 2, damage=12, poison=10, poison_turns=2),
    _c("tamerlan_epic", "Тамерлан", "epic", 4000, 620, 46, "Натиск", 2, surname="Хазиатметов", damage=30, shield=12),

    # ======================================================================= #
    # СВЕРХРЕДКИЙ (4)
    # ======================================================================= #
    _c("elizaveta", "Елизавета", "superrare", 2000, 580, 44, "Имперский указ", 3, stun=1),
    _c("evita", "Эвита", "superrare", 1000, 520, 38, "Танец", 3, damage=18, dodge=1),
    _c("elen", "Элен", "superrare", 1000, 600, 36, "Лунный свет", 3, heal=32, shield=22),
    _c("amelia", "Амелия", "superrare", 2500, 580, 36, "Милосердие", 3, heal=45, cleanse=True),

    # ======================================================================= #
    # РЕДКИЙ (4)
    # ======================================================================= #
    _c("karina", "Карина", "rare", 500, 540, 38, "Точный удар", 2, damage=22, ignore_shield=True),
    _c("kamila", "Камила", "rare", 500, 540, 40, "Двойной выстрел", 2, damage=15, hits=2),
    _c("egor", "Егор", "rare", 500, 560, 36, "Разведка", 3, damage=18, weaken=12, weaken_turns=2),
    _c("oleg", "Олег", "rare", 250, 580, 42, "Простой мужик", 2, damage=26),

    # ======================================================================= #
    # ЗАРЕЗЕРВИРОВАНО: пять сюжетных («стабильных») карт
    # Владелец добавит их в субботу — здесь их выдумывать не нужно.
    # Формат строки:
    #   _c("card_id", "Имя", "rarity", points, hp, atk, "Способность", cd, **effect)
    # ======================================================================= #
)

CARDS_BY_ID: dict[str, Card] = {card.card_id: card for card in CARDS}

# Карты, которые нельзя ни купить в магазине, ни выбить случайно:
# они выдаются только промокодом.
PROMO_ONLY_CARD_IDS: frozenset[str] = frozenset({"elmira_secret"})

# Парные карты: когда обе в одной команде, поддерживают друг друга.
# Михаил Николаевич (географ) и Глафира — «М + Г = ❤️».
CARD_PAIRS: dict[str, str] = {
    "glafira": "mikhail_nik",
    "mikhail_nik": "glafira",
}

CARDS_BY_RARITY: dict[str, tuple[Card, ...]] = {
    key: tuple(card for card in CARDS if card.rarity == key) for key in RARITIES
}

# Редкости в порядке возрастания «крутости» — для сортировки коллекции.
SORTED_RARITY_INDEX: dict[str, int] = {key: i for i, key in enumerate(reversed(RARITY_ORDER))}


# Картинки лежат файлами в репозитории и раздаются самим Render как статика.
# В базе НЕ хранятся: Supabase не занимают. Репозиторий приватный, поэтому
# raw.githubusercontent.com не подходит — он требует авторизацию.
IMAGE_PATH = "/images/"

CARD_IMAGES: dict[str, str] = {
    "amir_1": "amir_1.jpg",
    "arina": "arina.jpg",
    "daniel": "daniel.jpg",
    "daniyar_mif": "daniyar_mif.jpg",
    "egor": "egor.jpg",
    "konstantin": "konstantin.jpg",
    "misha": "misha.jpg",
    "oleg": "oleg.jpg",
    "rustam": "rustam.jpg",
    "trofim": "trofim.jpg",
    "valeriya": "valeriya.jpg",
    "yana": "yana.jpg",
}


def image_file(card_id: str) -> str | None:
    """Имя файла арта. None, если арта ещё нет."""
    return CARD_IMAGES.get(card_id)


def image_url(card_id: str, base: str = "") -> str | None:
    """Ссылка на арт. base нужен там, где требуется полный адрес (Telegram)."""
    name = CARD_IMAGES.get(card_id)
    if not name:
        return None
    return f"{base.rstrip('/')}{IMAGE_PATH}{name}"


def get_card(card_id: str) -> Card:
    return CARDS_BY_ID[card_id]


def cards_sorted_for_user(card_ids: list[str] | set[str]) -> list[Card]:
    """Карты пользователя: от самой редкой к обычной, внутри — по очкам."""
    return sorted(
        (CARDS_BY_ID[cid] for cid in card_ids if cid in CARDS_BY_ID),
        key=lambda c: (-SORTED_RARITY_INDEX[c.rarity], -c.points, c.display_name),
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
            card.surname,
        )
        for card in CARDS
    ]
