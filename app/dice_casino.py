"""Быстрые игры казино: кости, футбол, баскетбол.

Отдельно от старого казино (цвета) — его правила не меняем. Здесь всё крутится
вокруг анимированных эмодзи Телеграма: бот шлёт кубик, Телеграм показывает
анимацию, а в ответ приходит число value.

Правила:
  кости (🎲, 1-6): чёт/нечёт — ×2, угадать точную цифру — ×3;
  футбол (⚽, 1-5) и баскетбол (🏀, 1-5): «попадёт»/«не попадёт» — ×2.

Проигрыш обрабатывается так же, как в обычном казино.
"""

from __future__ import annotations

GAME_DICE = "dice"
GAME_FOOTBALL = "football"
GAME_BASKETBALL = "basketball"

GAMES: dict[str, dict[str, object]] = {
    GAME_DICE: {"emoji": "🎲", "title": "Кости", "faces": 6},
    GAME_FOOTBALL: {"emoji": "⚽", "title": "Футбол", "faces": 5},
    GAME_BASKETBALL: {"emoji": "🏀", "title": "Баскетбол", "faces": 5},
}

# Как игроки пишут название игры в команде.
ALIASES: dict[str, str] = {
    "кости": GAME_DICE,
    "кубик": GAME_DICE,
    "кубики": GAME_DICE,
    "dice": GAME_DICE,
    "футбол": GAME_FOOTBALL,
    "фут": GAME_FOOTBALL,
    "football": GAME_FOOTBALL,
    "баскет": GAME_BASKETBALL,
    "баскетбол": GAME_BASKETBALL,
    "basketball": GAME_BASKETBALL,
}

# Выборы.
CHOICE_EVEN = "even"
CHOICE_ODD = "odd"
CHOICE_HIT = "hit"
CHOICE_MISS = "miss"

PARITY_MULT = 2
DIGIT_MULT = 3
SHOT_MULT = 2

# Сколько дать анимации Телеграма проиграться, прежде чем показать итог.
# Число уже известно сразу, но так «падают числа» на глазах, а не мгновенно.
DICE_PAUSE_SECONDS = 2.5

# «Попадёт» у футбола/баскетбола: считаем попаданием value >= 3 (то есть 3 из 5).
SHOT_HIT_FROM = 3


def normalize_game(raw: str) -> str | None:
    return ALIASES.get((raw or "").strip().lower().lstrip("/"))


def emoji(game: str) -> str:
    return str(GAMES[game]["emoji"])


def title(game: str) -> str:
    return str(GAMES[game]["title"])


def digit_choices() -> tuple[int, ...]:
    return (1, 2, 3, 4, 5, 6)


def choice_label(game: str, choice: str) -> str:
    if choice == CHOICE_EVEN:
        return "Чёт"
    if choice == CHOICE_ODD:
        return "Нечёт"
    if choice == CHOICE_HIT:
        return "Попадёт"
    if choice == CHOICE_MISS:
        return "Не попадёт"
    if choice.startswith("d") and choice[1:].isdigit():
        return f"цифра {choice[1:]}"
    return choice


def is_choice_valid(game: str, choice: str) -> bool:
    if game == GAME_DICE:
        if choice in (CHOICE_EVEN, CHOICE_ODD):
            return True
        return choice.startswith("d") and choice[1:].isdigit() and 1 <= int(choice[1:]) <= 6
    if game in (GAME_FOOTBALL, GAME_BASKETBALL):
        return choice in (CHOICE_HIT, CHOICE_MISS)
    return False


def multiplier(game: str, choice: str) -> int:
    if game == GAME_DICE and choice.startswith("d"):
        return DIGIT_MULT
    if game == GAME_DICE:
        return PARITY_MULT
    return SHOT_MULT


def is_win(game: str, choice: str, value: int) -> bool:
    value = int(value)
    if game == GAME_DICE:
        if choice == CHOICE_EVEN:
            return value % 2 == 0
        if choice == CHOICE_ODD:
            return value % 2 == 1
        if choice.startswith("d"):
            return value == int(choice[1:])
        return False
    if game in (GAME_FOOTBALL, GAME_BASKETBALL):
        hit = value >= SHOT_HIT_FROM
        return hit if choice == CHOICE_HIT else not hit
    return False


def face_count(game: str) -> int:
    return int(GAMES[game]["faces"])  # type: ignore[arg-type]
