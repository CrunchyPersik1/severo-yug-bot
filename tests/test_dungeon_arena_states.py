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
    tail = DUNGEON_PAGE.split('b.cd = Math.max(700, 2200 - ARENA.zi * 140', 1)[1][:120]
    assert "}" in tail.split("b.x = Math.max")[0]
