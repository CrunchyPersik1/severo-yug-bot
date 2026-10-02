"""Общие фикстуры и подстановка тестовых переменных окружения.

app.config читает BOT_TOKEN и DATABASE_URL на импорте, поэтому их надо
задать до первого импорта модулей приложения.
"""

import os

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/severo_test")
os.environ.setdefault("PUBLIC_URL", "https://severo-yug-bot.onrender.com")
