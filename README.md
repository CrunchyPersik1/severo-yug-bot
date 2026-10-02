# Северо-Юг — Telegram-бот с карточками и PvP

Коллекционные карточки (32 шт.) + PvP-бои. Хостинг: **Render free Web Service**,
режим **webhook**, данные — во внешней **PostgreSQL (Supabase)**, потому что
persistent disk на free-тарифе нет.

## Что внутри

| Файл | Назначение |
| --- | --- |
| `main.py` | FastAPI: `GET /` (health-check), вебхук, фоновый воркер таймаутов |
| `app/cards.py` | 32 карты: HP, ATK, способность, редкость, очки |
| `app/battle.py` | Боевой движок (чистые функции, без БД и Telegram) |
| `app/battle_service.py` | Транзакции боёв, выбор карт, таймауты, публикация сообщения |
| `app/db.py` | asyncpg-пул и все запросы |
| `app/gacha.py` | Веса редкостей и суточный сброс в 07:00 UTC |
| `app/handlers.py` | aiogram-роутеры |
| `app/render.py` | Тексты и инлайн-клавиатуры |
| `schema.sql` | Схема БД (применяется автоматически при старте) |

## Команды

- **«Северо-Юг»** (регистр и дефисы не важны) — выбить карту, 1 раз в сутки на пользователя.
  Сброс в **12:00 по ЕКБ** (07:00 UTC).
- **«пвп»** *ответом* на сообщение игрока — вызов на бой. Каждый выбирает карту из своей
  коллекции, бой идёт в одном сообщении, которое бот редактирует.
- `/my` — коллекция, `/top` — лидерборд, `/start` — справка.

## Правила боя

- HP у каждой карты своё, базовый «Удар» тоже свой; урон **не зависит** от редкости и очков.
- У каждой карты уникальная способность с перезарядкой (щит, яд, оглушение, кража HP,
  уклонение, контрудар, лечение, немота, ослабление).
- Победитель — тот, у кого HP врага дойдёт до 0. 30 ходов суммарно — ничья.
- 60 секунд без нажатия — автоудар, 3 автоудара подряд — техническое поражение.
- Состояние боя хранится в БД: перезапуск Render бой не ломает.
- В PvP доступны **только карты из коллекции игрока**.

## Деплой на Render

1. Создай проект в Supabase и возьми **pooler**-строку подключения
   (Project Settings → Database → Connection string → **Session pooler**, IPv4):
   `postgresql://postgres.<ref>:<пароль>@aws-0-<регион>.pooler.supabase.com:5432/postgres`
2. Render → **New + → Blueprint** → выбери репозиторий (файл `render.yaml` уже в корне).
3. Впиши переменные:
   - `BOT_TOKEN` — токен от [@BotFather](https://t.me/BotFather)
   - `DATABASE_URL` — строка из Supabase
   - `WEBHOOK_SECRET` и `WEBHOOK_TOKEN` Render сгенерирует сам
4. Оффлайн в @BotFather: **Bot Settings → Group Privacy → Turn off**, иначе бот не увидит
   сообщения в группах.
5. Вебхук ставится автоматически при старте, из `RENDER_EXTERNAL_URL`. Руками ничего не нужно.

Схема БД создаётся при первом старте. `GET /` отдаёт `200` — подходит для внешнего пингера
каждые 10 минут, чтобы сервис не засыпал.

## Локальный запуск

```bash
python -m venv .venv && . .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # заполни BOT_TOKEN и DATABASE_URL
uvicorn main:app --reload --port 8000
```

Для локальной отладки без вебхука укажи `PUBLIC_URL` через туннель (ngrok/cloudflared) —
приложение само вызовет `setWebhook`.

## Тесты

```bash
pytest -q                      # юнит-тесты движка, карт и весов
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/severo pytest -q
```

В GitHub Actions (`.github/workflows/ci.yml`) тесты гоняются вместе с настоящим Postgres.
