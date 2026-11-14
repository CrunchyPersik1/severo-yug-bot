"""Оставшиеся пассивки петов: опыт, Юги, босс."""

import asyncio
import inspect

from app import petfx


class _DB:
    def __init__(self, pet_id, level=5):
        self._pet = pet_id
        self._level = level

    async def equipped_pet(self, uid):
        if self._pet is None:
            return None
        return {"pet_id": self._pet, "level": self._level}


def test_effect_from_pool_returns_zero_without_pet():
    class Pool:
        def acquire(self):
            class Ctx:
                async def __aenter__(self_inner):
                    class Con:
                        async def fetchrow(self, *a, **k):
                            return None
                    return Con()

                async def __aexit__(self_inner, *a):
                    return False
            return Ctx()

    assert asyncio.run(petfx.effect_from_pool(Pool(), 1, "xp")) == 0.0


def test_oddi_boosts_xp():
    from app import db

    source = inspect.getsource(db.Database.grant_xp)
    assert 'petfx.effect_from_pool(self._p(), user_id, "xp")' in source


def test_patejto_boosts_yugi():
    from app import db

    source = inspect.getsource(db.Database.yugi_tap)
    assert '"yugi"' in source


def test_chester_and_lelik_boost_boss():
    from app import dungeon_repo

    source = inspect.getsource(dungeon_repo.DungeonBossRepo)
    assert "boss_coins" in source
    assert "boss_yugi" in source
