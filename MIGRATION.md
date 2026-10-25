# Переезд с Render на бесплатный хостинг

Render заморозил аккаунт: закончились 750 инстанс-часов. Код и база целы,
нужен только новый сервер.

## Что нужно знать

Бот — это **постоянный процесс**: webhook от Telegram + фоновые воркеры
(курс акций, ивенты, тикеры). Поэтому **serverless не подойдёт**
(Vercel, Netlify, Cloudflare Workers) — там нет фоновых задач.
Нужен контейнер: Fly.io, Koyeb, Railway или VPS.

## Переменные окружения

Обязательные:

```
BOT_TOKEN=8835185511:AAG_TTsJmLf1fN4v6DCcBP3SKABNR7l86-Y
DATABASE_URL=postgresql://postgres.mcobvefvmlwdxludagkf:mas7aEdziuNoWiGJ@aws-0-eu-west-1.pooler.supabase.com:5432/postgres
ADMIN_IDS=1806176773
```

Генерируются автоматически на Render (задать любые случайные строки):

```
WEBHOOK_SECRET=<любая случайная строка>
WEBHOOK_TOKEN=<любая случайная строка>
```

Опциональные: `PORT` (обычно даёт хостинг), `WEBAPP_URL` (публичный адрес
сервиса — нужен для кнопок мини-аппок).

## Вариант 1 — Fly.io (рекомендую)

Бесплатно: 3 машины shared-cpu-1x. Регион fra (Франкфурт) — ближе к базе.

```bash
# 1. Установить CLI (Windows PowerShell)
iwr https://fly.io/install.ps1 -useb | iex

# 2. Войти
fly auth signup     # или fly auth login

# 3. В папке репозитория
cd severo-yug-bot
fly launch --no-deploy --copy-config

# 4. Секреты (по одному)
fly secrets set BOT_TOKEN="8835185511:AAG_TTsJmLf1fN4v6DCcBP3SKABNR7l86-Y"
fly secrets set DATABASE_URL="postgresql://postgres.mcobvefvmlwdxludagkf:mas7aEdziuNoWiGJ@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
fly secrets set ADMIN_IDS="1806176773"
fly secrets set WEBHOOK_SECRET="$(openssl rand -hex 16)"
fly secrets set WEBHOOK_TOKEN="$(openssl rand -hex 16)"

# 5. Задеплоить
fly deploy

# 6. Проверить
fly open /            # должен ответить {"ok":true,...}
```

После деплоя адрес будет вида `https://severo-yug-bot.fly.dev` — его надо
прописать в `WEBAPP_URL` и переустановить webhook (см. ниже).

## Вариант 2 — Koyeb

Бесплатно: 1 web-сервис, 512 МБ. Засыпает при простое — история курса
будет копиться хуже, но бот работает.

1. Регистрация: https://app.koyeb.com
2. **Create Service → GitHub** → выбрать `CrunchyPersik1/severo-yug-bot`
3. Builder: **Dockerfile** (он уже в репозитории)
4. Port: **8000**, Protocol: **HTTP**
5. Environment variables — те же шесть из блока выше
6. Instance: **Free** (nano)
7. Deploy

## Вариант 3 — VPS (150–300 ₽/мес, но не засыпает никогда)

Самый стабильный: бот работает круглосуточно, история курса не рвётся.

```bash
# на сервере (Ubuntu)
apt update && apt install -y docker.io git
git clone https://github.com/CrunchyPersik1/severo-yug-bot.git
cd severo-yug-bot
docker build -t severo-yug .
docker run -d --restart=always --name bot \
  -p 8000:8000 \
  -e BOT_TOKEN="..." \
  -e DATABASE_URL="..." \
  -e ADMIN_IDS="1806176773" \
  -e WEBHOOK_SECRET="..." \
  -e WEBHOOK_TOKEN="..." \
  severo-yug
```

Плюс nginx + домен для HTTPS (Telegram требует https для webhook).

## После переезда — переставить webhook

Формально бот ставит его сам при старте (если задан `WEBAPP_URL`).
Если нет — вручную:

```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook?url=https://<новый-адрес>/tg/<WEBHOOK_SECRET>"
```

Проверить:

```bash
curl "https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo"
```

Должно быть `"url": "https://..."` и `"last_error_message"` отсутствует.

## Что НЕ надо переносить

- **База** — Supabase живёт отдельно, все 34 игрока, карты, балансы на месте
- **Код** — тот же репозиторий, последний коммит в `main`
- **Картинки** — в папке `images/`, попадут в образ

## Если что-то пошло не так

Проверить, что процесс поднялся:

```bash
curl https://<адрес>/     # {"ok":true,"service":"severo-yug-bot","db":true,...}
```

`db: true` — база подключилась. Если `db: false` — неверный `DATABASE_URL`.
Если ответа нет — сервис не стартовал, смотри логи хостинга.
