"""Быстрые игры казино: кости, футбол, баскетбол."""

from app import dice_casino


def test_game_aliases():
    assert dice_casino.normalize_game("кости") == dice_casino.GAME_DICE
    assert dice_casino.normalize_game("Кости") == dice_casino.GAME_DICE
    assert dice_casino.normalize_game("футбол") == dice_casino.GAME_FOOTBALL
    assert dice_casino.normalize_game("баскет") == dice_casino.GAME_BASKETBALL
    assert dice_casino.normalize_game("цвета") is None


def test_dice_parity():
    assert dice_casino.is_win("dice", "even", 4)
    assert not dice_casino.is_win("dice", "even", 3)
    assert dice_casino.is_win("dice", "odd", 3)
    assert not dice_casino.is_win("dice", "odd", 2)


def test_dice_digit():
    assert dice_casino.is_win("dice", "d5", 5)
    assert not dice_casino.is_win("dice", "d5", 4)
    assert dice_casino.multiplier("dice", "d5") == 3
    assert dice_casino.multiplier("dice", "even") == 2


def test_shot_games():
    assert dice_casino.is_win("football", "hit", 3)
    assert dice_casino.is_win("football", "hit", 5)
    assert dice_casino.is_win("football", "miss", 1)
    assert not dice_casino.is_win("football", "hit", 2)
    assert dice_casino.is_win("basketball", "hit", 4)
    assert dice_casino.multiplier("basketball", "miss") == 2


def test_choice_validation():
    assert dice_casino.is_choice_valid("dice", "even")
    assert dice_casino.is_choice_valid("dice", "d6")
    assert not dice_casino.is_choice_valid("dice", "d7")
    assert not dice_casino.is_choice_valid("dice", "d0")
    assert dice_casino.is_choice_valid("football", "hit")
    assert not dice_casino.is_choice_valid("football", "even")


def test_choice_labels():
    assert dice_casino.choice_label("dice", "even") == "Чёт"
    assert dice_casino.choice_label("dice", "d3") == "цифра 3"
    assert dice_casino.choice_label("basketball", "miss") == "Не попадёт"
