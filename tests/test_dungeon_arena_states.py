"""Босс не залипает в одной атаке."""

from app.webapp import DUNGEON_PAGE


def test_recover_checked_before_tell_branch():
    # recover должен стоять первым в цепочке состояний, иначе босс
    # застревает в нём и больше не атакует
    recover = DUNGEON_PAGE.index('if (b.state === "recover"){')
    idle = DUNGEON_PAGE.index('} else if (b.state === "idle" || b.state === "walk"){')
    tell = DUNGEON_PAGE.index('} else if (b.tell <= 0){')
    assert recover < idle < tell


def test_state_machine_closes_before_draw():
    # после блока состояний идёт зажим координат босса, значит цепочка закрыта
    tail = DUNGEON_PAGE.split("b.cd = Math.max(450, 1500 - ARENA.zi * 90", 1)[1][:200]
    assert "b.x = Math.max(30, Math.min(w - 30, b.x));" in tail
