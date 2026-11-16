"""Версия игры и файл истории обновлений."""

import pathlib
import re

from app import version

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_version_format():
    assert re.fullmatch(r"\d+\.\d+\.\d+", version.VERSION), version.VERSION
    assert version.BUILD > 300


def test_changelog_exists_and_has_current_version():
    text = (ROOT / "CHANGELOG.txt").read_text(encoding="utf-8")
    assert "ИСТОРИЯ ОБНОВЛЕНИЙ" in text
    assert f"Сейчас в игре: {version.VERSION}" in text


def test_changelog_lists_every_commit():
    text = (ROOT / "CHANGELOG.txt").read_text(encoding="utf-8")
    entries = re.findall(r"\(([0-9a-f]{7})\)", text)
    assert len(entries) == version.BUILD


def test_major_versions_are_marked():
    text = (ROOT / "CHANGELOG.txt").read_text(encoding="utf-8")
    assert "крупное обновление" in text
    assert text.count("крупное обновление") >= 5


def test_settings_show_version():
    from app import webtheme

    source = pathlib.Path(webtheme.__file__).read_text(encoding="utf-8")
    assert "window.__APP_VERSION" in source
    assert "Версия " in source
