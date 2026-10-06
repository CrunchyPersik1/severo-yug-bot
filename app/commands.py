"""Меню команд Telegram: то, что всплывает при вводе «/».

Порядок в списке = порядок в меню. Названия только [a-z0-9_], описания на русском.
"""

from __future__ import annotations

from aiogram.types import BotCommand

COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Справка и правила игры"),
    BotCommand(command="drop", description="Выбить карту «Северо-Юг» (раз в сутки)"),
    BotCommand(command="roulette", description="Рулетка — раз в сутки в 20:00 по ЕКБ"),
    BotCommand(command="case", description="Открыть кейс: карта от эпической и выше"),
    BotCommand(command="my", description="Коллекция, кейсы, копии и их id"),
    BotCommand(command="upgrade", description="Улучшить карту за 750: /upgrade #id"),
    BotCommand(command="market", description="Рынок: лоты с кнопкой «Купить»"),
    BotCommand(command="casino", description="Казино: ставка очками или картой"),
    BotCommand(command="sell", description="Выставить лот: /sell #id цена"),
    BotCommand(command="mylots", description="Свои лоты на рынке"),
    BotCommand(command="changeprice", description="Изменить цену: /changeprice id цена"),
    BotCommand(command="gift", description="Подарить карту: /gift #id @игрок"),
    BotCommand(command="pvp", description="Вызвать на бой — ответом на сообщение"),
    BotCommand(command="pvprating", description="Топ PvP: победы и убийства карт"),
    BotCommand(command="rating", description="Репутация торговца: /rating @игрок"),
    BotCommand(command="top", description="Топ по очкам коллекции"),
    BotCommand(command="profile", description="Профиль и карты: свой или /profile @игрок"),
    BotCommand(command="help", description="Справка"),
]
