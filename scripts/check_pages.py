"""Проверка HTML-страниц мини-аппок перед деплоем.

Вытаскивает строки вида NAME_PAGE = r\"\"\"...\"\"\" из app/webapp.py и main.py и для
каждой страницы:

  * баланс тегов и уникальность id;
  * последний <script> прогоняется через `node --check`;
  * линт GLSL в шаблонных строках: баланс скобок, отсутствие не-ASCII;
  * с --smoke страница прогоняется в DOM-заглушке (scripts/page_smoke.js).

Примеры:

    .venv\\Scripts\\python.exe scripts\\check_pages.py
    .venv\\Scripts\\python.exe scripts\\check_pages.py --filter dungeon --smoke
"""

from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("app/webapp.py", "main.py")
SMOKE = ROOT / "scripts" / "page_smoke.js"
PAGE_HEAD = re.compile(r'^([A-Z0-9_]+_PAGE) = r"""(.*)$', re.M)
TAG_RE = r"<%s[\s>]"
IDS = re.compile(r'\bid="([^"]+)"')


def read_pages() -> list[tuple[str, str, str]]:
    """[(файл, имя, html)] по всем исходникам."""
    out: list[tuple[str, str, str]] = []
    for rel in SOURCES:
        path = ROOT / rel
        if not path.exists():
            continue
        src = io.open(path, encoding="utf-8").read()
        for match in PAGE_HEAD.finditer(src):
            name, first_line = match.group(1), match.group(2)
            end = src.index('\n"""', match.end())
            body = first_line + "\n" + src[match.end() + 1:end]
            out.append((rel, name, body))
    return out


def check_html(name: str, html: str) -> list[str]:
    problems: list[str] = []
    for tag in ("div", "canvas", "button", "script", "style"):
        opened = len(re.findall(TAG_RE % tag, html))
        closed = len(re.findall(r"</%s>" % tag, html))
        if opened != closed:
            problems.append("<%s>: %d открыто, %d закрыто" % (tag, opened, closed))
    ids = IDS.findall(html)
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        problems.append("повторяются id: " + ", ".join(duplicates))
    return problems


def check_glsl(name: str, html: str) -> list[str]:
    problems: list[str] = []
    for shader_name, source in re.findall(r"const (VS|FS_\w+) = `(.*?)`;", html, re.S):
        if source.count("{") != source.count("}") or "void main" not in source:
            problems.append("%s: %s — не сбалансирован" % (name, shader_name))
        if "\\" in source:
            problems.append("%s: %s — обратный слэш в GLSL" % (name, shader_name))
        for line in source.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and not stripped.isascii():
                problems.append("%s: %s — не-ASCII строка: %r" % (name, shader_name, stripped))
    return problems


def check_telegram(name: str, html: str) -> list[str]:
    """Страница, которая ходит в API с initData, должна грузить скрипт Telegram.

    Без него window.Telegram пуст, initData пустой, и все ручки отвечают 401 —
    так кооп-босс молча уходил в локальный бой.
    """
    if "X-Telegram-Init-Data" in html and "telegram-web-app.js" not in html:
        return ["%s: использует initData, но telegram-web-app.js не подключён" % name]
    return []


def last_script(html: str) -> str | None:
    found = re.findall(r"<script>(.*?)</script>", html, re.S)
    return found[-1] if found else None


def node_check(name: str, js: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / (name + ".js")
        io.open(path, "w", encoding="utf-8", newline="\n").write(js)
        try:
            proc = subprocess.run(["node", "--check", str(path)],
                                  capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return True, "node недоступен: %s" % exc
        except Exception as exc:  # noqa: BLE001 - любой сбой не должен валить проверку
            return True, "node не запустился: %s" % exc
        if proc.returncode != 0:
            text = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")
            return False, text.strip()
        return True, (path.name + ": синтаксис ok")


def smoke(name: str, js: str) -> tuple[bool, str]:
    if not SMOKE.exists():
        return True, "стенда нет — smoke пропущен"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / (name + ".js")
        io.open(path, "w", encoding="utf-8", newline="\n").write(js)
        try:
            proc = subprocess.run(["node", str(SMOKE), str(path)],
                                  capture_output=True, timeout=180)
        except Exception as exc:  # noqa: BLE001
            return True, "стенд не запустился: %s" % exc
    output = ((proc.stdout or b"") + (proc.stderr or b"")).decode("utf-8", "replace")
    return proc.returncode == 0, output.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка страниц мини-аппок")
    parser.add_argument("--filter", default="", help="подстрока имени страницы")
    parser.add_argument("--smoke", action="store_true", help="прогнать в DOM-заглушке")
    parser.add_argument("--quiet", action="store_true", help="только ошибки")
    args = parser.parse_args(argv)

    pages = read_pages()
    if args.filter:
        needle = args.filter.upper()
        pages = [p for p in pages if needle in p[1].upper()]
    if not pages:
        print("страницы не найдены")
        return 1

    failed = 0
    for rel, name, html in pages:
        problems = check_html(name, html) + check_glsl(name, html) + check_telegram(name, html)
        js = last_script(html)
        ok = js is not None
        note = "скрипта нет"
        if js:
            ok, note = node_check(name, js)
            if not ok:
                problems.append("node --check: " + note)
        if args.smoke and js:
            s_ok, s_out = smoke(name, js)
            if not s_ok:
                problems.append("стенд: " + s_out)
            elif not args.quiet:
                note += " · " + s_out.splitlines()[-1]
        if problems:
            failed += 1
            print("FAIL %s (%s)" % (name, rel))
            for problem in problems:
                print("   - " + problem)
        elif not args.quiet:
            print("ok   %-22s %5d строк html · %d id · %s" % (name, html.count("\n") + 1,
                                                             len(IDS.findall(html)), note))
    print("\nстраниц: %d, с проблемами: %d" % (len(pages), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
