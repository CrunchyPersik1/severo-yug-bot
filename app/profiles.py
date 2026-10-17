"""Профили игроков: баннер, описание, статус, музыка, награды и теги.

Награды и теги выдаёт только админ — за победы и за помощь проекту.
"""

from __future__ import annotations

from typing import Any

# Баннеры: градиенты, чтобы не грузить картинки и не зависеть от хостинга.
BANNERS: dict[str, dict[str, str]] = {
    "sunset": {"name": "Закат", "a": "#f59e0b", "b": "#dc2626"},
    "ocean": {"name": "Океан", "a": "#0ea5e9", "b": "#1e3a8a"},
    "forest": {"name": "Лес", "a": "#22c55e", "b": "#064e3b"},
    "violet": {"name": "Аметист", "a": "#a855f7", "b": "#4c1d95"},
    "mono": {"name": "Графит", "a": "#64748b", "b": "#0f172a"},
    "candy": {"name": "Карамель", "a": "#f472b6", "b": "#7c3aed"},
    "gold": {"name": "Золото", "a": "#facc15", "b": "#78350f"},
}
DEFAULT_BANNER = "sunset"

# Теги, которые можно выдать. Только админ.
TAGS: dict[str, str] = {
    "supporter": "💕💕 саппортер",
    "veteran": "🎖 ветеран",
    "champion": "🏆 чемпион",
    "artist": "🎨 художник",
}

MAX_BIO = 160
MAX_STATUS = 40
MAX_MUSIC = 60
MAX_REWARDS = 8


def banner_css(key: str | None) -> str:
    spec = BANNERS.get(key or DEFAULT_BANNER) or BANNERS[DEFAULT_BANNER]
    return f"linear-gradient(135deg,{spec['a']},{spec['b']})"


def banner_name(key: str | None) -> str:
    spec = BANNERS.get(key or DEFAULT_BANNER) or BANNERS[DEFAULT_BANNER]
    return str(spec["name"])


def clean(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    return value[:limit]


def tag_label(tag: str) -> str:
    return TAGS.get(tag, tag)


def clean_url(text: Any, limit: int = 400) -> str:
    """Ссылка на картинку: только http(s). Иначе пусто."""
    value = str(text or "").strip()
    if not value:
        return ""
    low = value.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        return ""
    return value[:limit]


def initial(name: str | None) -> str:
    value = (name or "?").strip()
    return value[:1].upper() if value else "?"


def avatar_color(seed: str | None) -> str:
    """Цвет аватарки по нику — стабильный, без картинок."""
    palette = [
        "#e879f9", "#60a5fa", "#34d399", "#fbbf24",
        "#f87171", "#a78bfa", "#2dd4bf", "#fb923c",
    ]
    key = sum(ord(ch) for ch in (seed or "?"))
    return palette[key % len(palette)]
