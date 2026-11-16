"""Анимация атаки героя и звуки боя на арене."""

from app.webapp import DUNGEON_PAGE


def test_hero_attack_uses_second_sheet_row():
    assert "const srcY = shooting ? heroSheet.fh : 0;" in DUNGEON_PAGE
    assert "const shooting = h1.atkCd > 0.12;" in DUNGEON_PAGE


def test_arena_has_sound_effects():
    assert "function arenaBeep(freq, dur, type)" in DUNGEON_PAGE
    for freq in ("680", "300", "220", "120", "880"):
        assert "arenaBeep(" + freq in DUNGEON_PAGE


def test_sound_never_breaks_battle():
    body = DUNGEON_PAGE[DUNGEON_PAGE.index("function arenaBeep"):][:700]
    assert "try {" in body and "catch (e) {}" in body
    assert "ctxA.state === \"suspended\"" in body


def test_no_external_audio_files():
    # звук синтезируется, файлов не тянем
    assert ".mp3" not in DUNGEON_PAGE and ".ogg" not in DUNGEON_PAGE
