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
    personal: bool = False   # личная тема: не продаётся, выдаётся вручную
    light: bool = False      # светлая: тёмный текст на светлом фоне

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
    # Зима пришла: осенняя тема стала снежной (чёрный + голубой).
    Theme(
        "classic", "Зима", 0,
        "#0c1220", "#121b2c", "#18233a", "#243350",
        "#eaf2ff", "#93a6c4", "#3b9ae8", "#8fd0ff", "#04121f", "snow",
    ),
    # Светлая снежная тема: белый + голубой.
    Theme(
        "snowlight", "Снег", 0,
        "#eef5fd", "#ffffff", "#e4eefb", "#cfe0f5",
        "#16233a", "#5b7291", "#2f8ce0", "#6fc0ff", "#ffffff", "snow",
        light=True,
    ),
    # Две бесплатные темы каждому игроку.
    Theme(
        "mint", "Мята", 0,
        "#0f1b18", "#16261f", "#1d3129", "#2a4638",
        "#e9f8f1", "#93b3a4", "#38b48a", "#7be0bd", "#04140f", "spark",
    ),
    Theme(
        "clay", "Терракота", 0,
        "#1e1613", "#2a1e19", "#362621", "#4a362e",
        "#f7ece4", "#bfa08c", "#c4713e", "#eba679", "#20100a", "ember",
    ),
    # Личная тема Трофима: чистый чёрный и белый, без оттенков.
    Theme(
        "trofim", "Чёрно-белая", 0,
        "#000000", "#0a0a0a", "#141414", "#262626",
        "#ffffff", "#9a9a9a", "#ffffff", "#e6e6e6", "#000000", "spark",
        personal=True,
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
    """В магазине — только платные и не личные."""
    return [theme for theme in THEMES if theme.price > 0 and not theme.personal]


def is_free(theme: Theme) -> bool:
    """Бесплатная — значит доступна всем сразу, без покупки."""
    return theme.price <= 0 and not theme.personal


def granted_only(theme: Theme) -> bool:
    return bool(theme.personal)


def describe(theme: Theme) -> str:
    price = "бесплатно" if not theme.price else f"{theme.price} очков"
    return f"{theme.name} — {price}"


def css_vars(theme: Theme) -> str:
    body = ";".join(f"--{key}:{value}" for key, value in theme.vars.items())
    return f":root{{{body}}}"
