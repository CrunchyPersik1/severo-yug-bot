
"""Сборка CHANGELOG.txt и app/version.py из истории git.

Версия: КРУПНАЯ.ФИЧИ.ФИКСЫ[.СБОРКА]
  крупная — новая большая часть игры (метка в MAJOR_MARKS)
  фичи   — сколько новых функций добавлено внутри крупной
  фиксы  — сколько правок/багфиксов внутри текущей фичи
"""

from __future__ import annotations

import re
import subprocess
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "CHANGELOG.txt"
VERSION_FILE = ROOT / "app" / "version.py"

# Начала крупных обновлений: подстрока из темы коммита → новая мажорная версия
MAJOR_MARKS = (
    "карточки, гача и PvP",              # 1.0.0 — ядро игры
    "магазин и Telegram Mini App",       # 2.0.0 — магазин и первое приложение
    "биржа — отдельная мини-аппка",      # 3.0.0 — биржа
    "главное приложение игры (/hub)",    # 4.0.0 — хаб
    "Подземелье Тимура",                 # 5.0.0 — подземелье
    "Юга-кликер",                        # 6.0.0 — кликер
    "квесты дня, выдача наград",         # 7.0.0 — ивент «Санта Егор»
    "9 стилей для мини-аппок",           # 8.0.0 — стили
    "арена боссов",                      # 9.0.0 — боевая арена
)

# balance/test/docs/chore — это правки, а не новые функции
TYPE_FEAT = ("feat", "добав", "нов", "прототип")


def git_log() -> list[tuple[str, str, str]]:
    # без pipe: в этом окружении дочерние процессы не могут писать в канал,
    # поэтому git пишет прямо в файл
    import tempfile

    with tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False, encoding="utf-8") as fh:
        dump = fh.name
    with open(dump, "w", encoding="utf-8") as out:
        subprocess.run(
            ["git", "log", "--reverse", "--pretty=%H%x09%ad%x09%s", "--date=short"],
            cwd=ROOT,
            stdout=out,
            check=True,
        )
    with open(dump, encoding="utf-8") as fh:
        out = fh.read()
    Path(dump).unlink(missing_ok=True)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            rows.append((parts[0], parts[1], parts[2]))
    return rows


def is_long(mark: str) -> int:
    return len(mark)


def major_index(subject: str, marks: list[tuple[int, str]]) -> int | None:
    for index, mark in marks:
        if mark in subject:
            return index
    return None


def build() -> tuple[str, list[dict]]:
    commits = git_log()
    marks = [(i + 1, mark) for i, mark in enumerate(MAJOR_MARKS)]
    major = minor = patch = 0
    version = "0.0.0"
    entries: list[dict] = []
    for number, (sha, day, subject) in enumerate(commits, start=1):
        mark = major_index(subject, marks)
        if mark is not None:
            major = mark
            minor = 0
            patch = 0
        else:
            kind = re.split(r"[:(]", subject, maxsplit=1)[0].strip().lower()
            if kind in TYPE_FEAT or any(word in subject.lower() for word in TYPE_FEAT):
                minor += 1
                patch = 0
            else:
                patch += 1
        version = f"{major}.{minor}.{patch}"
        entries.append(
            {
                "n": number,
                "sha": sha[:7],
                "day": day,
                "subject": subject,
                "version": version,
                "major": mark is not None,
            }
        )
    return version, entries


def render(entries: list[dict]) -> str:
    latest = entries[-1]["version"] if entries else "0.0.0"
    today = date.today().isoformat()
    lines = [
        "СЕВЕРО-ЮГ · ИСТОРИЯ ОБНОВЛЕНИЙ",
        "",
        "Формат версии: КРУПНАЯ.ФИЧИ.ФИКСЫ",
        "  КРУПНАЯ — новая большая часть игры (новая цифра в начале)",
        "  ФИЧИ   — сколько новых функций добавлено внутри крупной",
        "  ФИКСЫ  — сколько правок и багфиксов внутри текущей фичи",
        "",
        f"Сейчас в игре: {latest} · собрано {len(entries)} коммитов · {today}",
        "",
    ]
    current = None
    for entry in reversed(entries):
        if entry["version"] != current:
            current = entry["version"]
            mark = "  ← крупное обновление" if entry["major"] else ""
            lines.append("")
            lines.append(f"[{current}]  {entry['day']}{mark}")
        lines.append(f"   · {entry['subject']}  ({entry['sha']})")
    lines.append("")
    return "\n".join(lines)


def write_all() -> str:
    version, entries = build()
    CHANGELOG.write_text(render(entries), encoding="utf-8", newline="\n")
    VERSION_FILE.write_text(
        '"""Версия игры. Генерируется scripts/changelog.py — не править руками."""\n\n'
        f'VERSION = "{version}"\n'
        f"BUILD = {len(entries)}\n"
        f'RELEASED = "{date.today().isoformat()}"\n',
        encoding="utf-8",
        newline="\n",
    )
    return version


if __name__ == "__main__":
    print("версия:", write_all(), "· файлы:", CHANGELOG.name, VERSION_FILE.name)
