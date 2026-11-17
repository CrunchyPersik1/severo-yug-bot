"""Меню команд Telegram: то, что всплывает при вводе «/».

Порядок в списке = порядок в меню. Названия только [a-z0-9_], описания на русском.
"""

from __future__ import annotations

from aiogram.types import BotCommand

COMMANDS: list[BotCommand] = [
    # старт и помощь
    BotCommand(command="start", description="Справка и меню игры"),
    BotCommand(command="tutorial", description="Обучение с нуля: что где нажимать"),
    BotCommand(command="help", description="Все команды списком"),
    # карточки
    BotCommand(command="drop", description="Карта дня «Северо-Юг»"),
    BotCommand(command="my", description="Коллекция, кейсы и копии"),
    BotCommand(command="find", description="Поиск карты: /find имя"),
    BotCommand(command="upgrade", description="Улучшить карту: /upgrade #id"),
    BotCommand(command="fav", description="Любимая карта: /fav #id"),
    BotCommand(command="profile", description="Профиль: свой или /profile @игрок"),
    # экономика
    BotCommand(command="shop", description="Магазин: учителя, наборы, аксессуары"),
    BotCommand(command="stocks", description="Биржа: акции, курсы, портфель"),
    BotCommand(command="casino", description="Казино: ставка очками или картой"),
    BotCommand(command="casinostats", description="Статистика казино"),
    # рынок
    BotCommand(command="market", description="Рынок: лоты игроков"),
    BotCommand(command="sell", description="Выставить лот: /sell #id цена"),
    BotCommand(command="mylots", description="Свои лоты"),
    BotCommand(command="changeprice", description="Изменить цену лота"),
    BotCommand(command="gift", description="Подарить карту: /gift #id @игрок"),
    BotCommand(command="buyer", description="Скупщик: продать карты сразу"),
    # игры
    BotCommand(command="case", description="Открыть кейс"),
    BotCommand(command="roulette", description="Рулетка"),
    BotCommand(command="dungeon", description="Подземелье: мобы и боссы"),
    BotCommand(command="boss", description="Рейд-босс: бить всем вместе"),
    BotCommand(command="kopilka", description="Копилка ивента"),
    BotCommand(command="upgrader", description="Апгрейдер карт"),
    BotCommand(command="pass", description="Северо-Пасс: сезон и награды"),
    # бои
    BotCommand(command="pvp", description="Вызвать на бой ответом на сообщение"),
    BotCommand(command="pvprating", description="Топ PvP"),
    BotCommand(command="stop", description="Остановить свой бой"),
    # прочее
    BotCommand(command="style", description="Оформление мини-аппок"),
    BotCommand(command="top", description="Топ по очкам"),
    BotCommand(command="levels", description="Топ по уровням"),
    BotCommand(command="rating", description="Репутация торговца"),
    BotCommand(command="ref", description="Реферальная ссылка"),
    BotCommand(command="promo", description="Ввести промокод"),
    BotCommand(command="vip", description="VIP-подписка"),
    BotCommand(command="faq", description="Частые вопросы и правила"),
]

# Админу меню показывается отдельно — обычным игрокам админка не светится.
ADMIN_COMMANDS: list[BotCommand] = COMMANDS + [
    BotCommand(command="admin", description="Админка: сводка, выдачи, рассылка"),
    BotCommand(command="pointsaudit", description="Правки баланса в базе"),
    BotCommand(command="ban", description="Забанить игрока"),
    BotCommand(command="unban", description="Разбанить игрока"),
    BotCommand(command="bans", description="Список банов"),
]
