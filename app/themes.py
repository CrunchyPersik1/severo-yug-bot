"""Стили мини-аппок: каталог тем, покупка и применение.

Тема — это набор CSS-переменных. Мини-аппка не переписывается: она подгружает
активную тему и подменяет переменные на лету, поэтому один и тот же код
выглядит по-разному у каждого игрока.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    price: int
    bg: str
    panel: str
    panel2: str
    line: str
    ink: str
    muted: str
    acc: str
    acc2: str
    particles: str  # что падает на фоне

    @property
    def vars(self) -> dict[str, str]:
        return {
            "bg": self.bg,
            "panel": self.panel,
            "panel2": self.panel2,
            "line": self.line,
            "ink": self.ink,
            "muted": self.muted,
            "acc": self.acc,
            "acc2": self.acc2,
        }

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["vars"] = self.vars
        return data


DEFAULT_THEME = "classic"


THEMES: tuple[Theme, ...] = (
    Theme(
        "classic", "Классика", 0,
        "#0a0c11", "#141822", "#1b2130", "#242c3d",
        "#eef2f8", "#7b8698", "#f59e0b", "#ffc53d", "leaf",
    ),
    Theme(
        "mono", "Чёрно-белая", 50_000,
        "#0b0b0c", "#151517", "#1d1d20", "#2a2a2e",
        "#f4f4f5", "#8a8a90", "#e5e5e5", "#ffffff", "snow",
    ),
    Theme(
        "astra", "Астра", 120_000,
        "#0a0714", "#150f26", "#1d1533", "#2c2145",
        "#efe9ff", "#8b7fae", "#a855f7", "#e9d5ff", "star",
    ),
    Theme(
        "violet", "Фиолетовый", 150_000,
        "#0d0716", "#180e28", "#221335", "#33204d",
        "#f2eaff", "#9b86b8", "#8b5cf6", "#c4b5fd", "star",
    ),
    Theme(
        "green", "Зелёный", 150_000,
        "#05100c", "#0d1d16", "#12271e", "#1e3a2c",
        "#e6fff4", "#7fa894", "#10b981", "#6ee7b7", "leaf",
    ),
    Theme(
        "acid", "Кислотный", 300_000,
        "#050704", "#0e120c", "#151c12", "#22301a",
        "#eaffdd", "#8aa87a", "#a3e635", "#d9f99d", "spark",
    ),
    Theme(
        "electric", "Электрик", 350_000,
        "#040814", "#0a1226", "#0f1a33", "#1b2a4d",
        "#e6f0ff", "#7f92b8", "#3b82f6", "#93c5fd", "spark",
    ),
    Theme(
        "blood", "Кровавый", 400_000,
        "#0a0405", "#170a0c", "#200e11", "#3a171c",
        "#ffe9eb", "#b8848a", "#dc2626", "#fca5a5", "ember",
    ),
    Theme(
        "rust", "Ржавчина", 450_000,
        "#0f0a06", "#1c1309", "#26190d", "#3d2a14",
        "#ffeeda", "#b89975", "#ea580c", "#fdba74", "leaf",
    ),
    Theme(
        "graphite", "Графит", 500_000,
        "#101114", "#1a1c21", "#23262c", "#33363d",
        "#f4f4f6", "#9a9ba1", "#f9a8d4", "#fbcfe8", "snow",
    ),
)

THEMES_BY_ID: dict[str, Theme] = {theme.id: theme for theme in THEMES}


def get(theme_id: str | None) -> Theme:
    """Тема по id. Незнакомая или пустая — классика."""
    if theme_id and theme_id in THEMES_BY_ID:
        return THEMES_BY_ID[theme_id]
    return THEMES_BY_ID[DEFAULT_THEME]


def shop_entries():
    """Темы для магазина: бесплатную не продаём."""
    return [theme for theme in THEMES if theme.price > 0]


def describe(theme: Theme) -> str:
    return f"{theme.name} — {'бесплатно' if not theme.price else str(theme.price) + ' очков'}"


def css_vars(theme: Theme) -> str:
    body = ";".join(f"--{key}:{value}" for key, value in theme.vars.items())
    return f":root{{{body}}}"
