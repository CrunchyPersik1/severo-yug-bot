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
    ("927f659", "1.0.0 — карточки, гача и PvP"),
    ("e93909f", "2.0.0 — магазин и первое мини-приложение"),
    ("40af28d", "3.0.0 — биржа отдельным приложением"),
    ("f9c57a3", "4.0.0 — девять стилей мини-аппок"),
    ("24c0740", "5.0.0 — главный экран игры (/hub)"),
    ("721e5e0", "6.0.0 — Юга-кликер"),
    ("f049895", "7.0.0 — ивент «Санта Егор»"),
    ("2671060", "8.0.0 — подземелье Тимура"),
    ("2e3e347", "9.0.0 — арена боссов"),
    ("34eabfd", "10.0.0 — Северо-Пасс"),
)

def major_index(sha: str, marks: list[tuple[str, str]]) -> int | None:
    """Какая эпоха начинается этим коммитом."""
    for index, (mark_sha, _) in enumerate(marks, start=1):
        if sha.startswith(mark_sha):
            return index
    return None


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


def build() -> tuple[str, list[dict]]:
    commits = git_log()
    marks = list(MAJOR_MARKS)
    major = minor = patch = 0
    version = "0.0.0"
    entries: list[dict] = []
    for number, (sha, day, subject) in enumerate(commits, start=1):
        mark = major_index(sha, marks)
        # эпоха только растёт: иначе старый маркер в тексте коммита
        # откатывал счётчик назад и версии прыгали (5.86 после 6.x)
        if mark is not None and mark > major:
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
        "  КРУПНАЯ — эпоха: новая большая часть игры (новая цифра в начале)",
        "  ФИЧИ   — сколько новых функций добавлено внутри эпохи",
        "  ФИКСЫ  — сколько правок и багфиксов внутри текущей фичи",
        "",
        f"Сейчас в игре: {latest} · собрано {len(entries)} коммитов · {today}",
        "",
    ]

    # эпохи идут от новой к старой, внутри эпохи версии тоже сверху вниз
    era_titles = {index: title for index, (_, title) in enumerate(MAJOR_MARKS, start=1)}
    eras: dict[int, list[dict]] = {}
    for entry in entries:
        era = int(entry["version"].split(".")[0])
        eras.setdefault(era, []).append(entry)

    for era in sorted(eras, reverse=True):
        group = eras[era]
        first = group[0]
        title = era_titles.get(era, "")
        lines.append("")
        lines.append("=" * 62)
        lines.append(f"ЭПОХА {era} · {title.split(' — ')[-1].upper()}")
        lines.append(f"началась {first['day']} · коммитов в эпохе: {len(group)}")
        lines.append("=" * 62)

        current = None
        for entry in reversed(group):
            if entry["version"] != current:
                current = entry["version"]
                lines.append("")
                lines.append(f"[{current}]  {entry['day']}")
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
