from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field


def _env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _ids(raw: str | None) -> tuple[int, ...]:
    if not raw:
        return ()
    out: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            out.append(int(part))
    return tuple(out)


@dataclass(frozen=True)
class Settings:
    """Конфигурация, целиком собираемая из переменных окружения."""

    bot_token: str
    database_url: str
    webhook_secret: str
    webhook_token: str
    public_url: str | None
    admin_ids: tuple[int, ...] = field(default_factory=tuple)

    # Сброс ежедневного лимита: 12:00 ЕКБ (UTC+5) == 07:00 UTC.
    reset_hour_utc: int = 7

    # Бой
    battle_timeout_seconds: int = 60
    battle_max_turns: int = 0   # 0 — без лимита ходов, бой идёт до победы или «Сдаться»
    battle_max_timeouts: int = 3
    pick_timeout_seconds: int = 600
    cards_per_page: int = 8

    @property
    def webhook_path(self) -> str:
        return f"/{self.webhook_secret}"

    def webhook_url(self) -> str | None:
        if not self.public_url:
            return None
        return self.public_url.rstrip("/") + self.webhook_path

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_ids


def _load() -> Settings:
    bot_token = _env("BOT_TOKEN", "TELEGRAM_BOT_TOKEN", "BOT_API_TOKEN")
    database_url = _env("DATABASE_URL", "PG_DSN", "POSTGRES_URL")
    if not bot_token:
        raise RuntimeError("Не задан BOT_TOKEN (переменная окружения).")
    if not database_url:
        raise RuntimeError("Не задан DATABASE_URL (переменная окружения).")

    secret = _env("WEBHOOK_SECRET")
    if not secret:
        # Стабильный путь без дополнительной настройки: одинаков при каждом старте.
        secret = hashlib.sha256(bot_token.encode("utf-8")).hexdigest()[:32]

    token = _env("WEBHOOK_TOKEN") or hashlib.sha256(
        (bot_token + ":telegram").encode("utf-8")
    ).hexdigest()[:48]

    public_url = _env("PUBLIC_URL", "RENDER_EXTERNAL_URL", "WEBHOOK_BASE_URL")
    if public_url and not public_url.startswith(("http://", "https://")):
        public_url = "https://" + public_url

    return Settings(
        bot_token=bot_token,
        database_url=database_url,
        webhook_secret=secret.strip("/"),
        webhook_token=token,
        public_url=public_url,
        admin_ids=_ids(_env("ADMIN_IDS")),
    )


settings = _load()
