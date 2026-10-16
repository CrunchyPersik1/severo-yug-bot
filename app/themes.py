"""Стили мини-аппок: каталог тем, покупка и применение.

Палитры специально НЕ чёрные: глубокие, но мягкие тона, чтобы не вырвиглазило.
Тема — это набор CSS-переменных; аппки подменяют их на лету.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    price: int
    bg: str        # фон
    panel: str     # поверхность карточек
    panel2: str    # вложенная поверхность
    line: str      # границы
    ink: str       # основной текст
    muted: str     # второстепенный текст
    acc: str       # акцент (кнопки)
    acc2: str      # светлый акцент
    acc_ink: str   # цвет текста НА акценте
    particles: str

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
            "acc-ink": self.acc_ink,
        }

    def payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["vars"] = self.vars
        return data


DEFAULT_THEME = "classic"

THEMES: tuple[Theme, ...] = (
    Theme(
        "classic", "Осень", 0,
        "#1b1613", "#241d19", "#2e251f", "#3d3229",
        "#f4ece4", "#a8968a", "#dc8a3f", "#f0b276", "#1b1206", "leaf",
    ),
    Theme(
        "mono", "Мел", 50_000,
        "#202226", "#292c31", "#33373d", "#434850",
        "#f2f4f6", "#a6abb3", "#cfd4da", "#ffffff", "#1c1e22", "snow",
    ),
    Theme(
        "astra", "Астра", 120_000,
        "#1e1932", "#282246", "#332b56", "#453a6b",
        "#efebff", "#a99ecb", "#9b7cf0", "#c9b6ff", "#170f2e", "star",
    ),
    Theme(
        "violet", "Фиолетовый", 150_000,
        "#221a35", "#2c2248", "#372b5a", "#4a3b72",
        "#f3ecff", "#b2a0cb", "#a274f3", "#cdb4ff", "#1c1233", "star",
    ),
    Theme(
        "green", "Хвоя", 150_000,
        "#17261e", "#203127", "#283d31", "#375143",
        "#e9f6ef", "#97b2a1", "#43a273", "#84d3a8", "#0d2318", "leaf",
    ),
    Theme(
        "acid", "Кислота", 300_000,
        "#1d2614", "#27311b", "#313d22", "#44532f",
        "#f1f8e6", "#a8b792", "#9dc941", "#c6e274", "#182207", "spark",
    ),
    Theme(
        "electric", "Электрик", 350_000,
        "#15213b", "#1c2c4c", "#24365c", "#324972",
        "#e9f1ff", "#96a8c7", "#4d88e8", "#8db8f6", "#0c1730", "spark",
    ),
    Theme(
        "blood", "Кровавый", 400_000,
        "#2b181a", "#351f22", "#402629", "#573539",
        "#f8eaeb", "#bd9599", "#c9454e", "#e28d92", "#2b0f12", "ember",
    ),
    Theme(
        "rust", "Ржавчина", 450_000,
        "#251b13", "#2f2319", "#3a2c1f", "#4e3d2a",
        "#f8eee3", "#bfa68b", "#d06d2c", "#e7a46f", "#2a1608", "leaf",
    ),
    Theme(
        "graphite", "Графит", 500_000,
        "#1d1f24", "#262930", "#30343c", "#3f444e",
        "#eff1f4", "#9da3ac", "#e9a7c5", "#f6cadb", "#2a1622", "snow",
    ),
)

THEMES_BY_ID: dict[str, Theme] = {theme.id: theme for theme in THEMES}


def get(theme_id: str | None) -> Theme:
    if theme_id and theme_id in THEMES_BY_ID:
        return THEMES_BY_ID[theme_id]
    return THEMES_BY_ID[DEFAULT_THEME]


def shop_entries() -> list[Theme]:
    return [theme for theme in THEMES if theme.price > 0]


def describe(theme: Theme) -> str:
    price = "бесплатно" if not theme.price else f"{theme.price} очков"
    return f"{theme.name} — {price}"


def css_vars(theme: Theme) -> str:
    body = ";".join(f"--{key}:{value}" for key, value in theme.vars.items())
    return f":root{{{body}}}"
