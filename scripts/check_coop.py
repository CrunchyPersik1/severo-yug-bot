"""Живая проверка кооп-босса: поднимает мини-сервер и бьёт его по HTTP.

Что проверяется:
  * настоящая проверка подписи initData (без неё — 401);
  * join/state/hit/leave через реальные ручки /api/dungeon/boss/*;
  * второй игрок попадает в ту же комнату, HP босса умножается;
  * удар снимает HP, кулдаун держит, босс бьёт по времени;
  * за собой убираем: тестовые игроки и комнаты удаляются.

Запуск (DSN берётся из DATABASE_URL или из admin.local.bat):

    .venv\\Scripts\\python.exe scripts\\check_coop.py
    .venv\\Scripts\\python.exe scripts\\check_coop.py --port 8811 --keep-rows
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_USERS = (900001, 900002)
PROBLEMS = 0


def check(label: str, got, want=None, cmp=None) -> None:
    global PROBLEMS
    ok = cmp(got, want) if cmp else got == want
    if not ok:
        PROBLEMS += 1
    print(("  ok   " if ok else "  FAIL ") + label + ": " + repr(got) +
          ("" if ok else " (ждали " + repr(want) + ")"))


def find_dsn() -> str:
    env = os.environ.get("DATABASE_URL", "").strip()
    if env:
        return env
    local = ROOT / "admin.local.bat"
    if local.exists():
        text = io.open(local, encoding="utf-8", errors="replace").read()
        found = re.search(r'DATABASE_URL=([^"\r\n]+)', text)
        if found:
            return found.group(1).strip()
    raise SystemExit("нет DATABASE_URL: задай переменную окружения")


def sign_init_data(token: str, user_id: int, name: str) -> str:
    """Такую же строку присылает Telegram в заголовке X-Telegram-Init-Data."""
    pairs = {
        "auth_date": "1700000000",
        "query_id": "AA" + str(user_id),
        "user": json.dumps({"id": user_id, "first_name": name}, ensure_ascii=False),
    }
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(pairs)


def http(method: str, url: str, init_data: str, body: dict | None = None):
    data = None
    headers = {"X-Telegram-Init-Data": init_data}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            return error.code, json.loads(raw)
        except ValueError:
            return error.code, {"raw": raw}


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Живая проверка кооп-босса")
    parser.add_argument("--port", type=int, default=8811)
    parser.add_argument("--keep-rows", action="store_true", help="не чистить базу")
    args = parser.parse_args(argv)

    dsn = find_dsn()
    token = "123456:COOP_CHECK_TOKEN"
    os.environ.setdefault("BOT_TOKEN", token)
    os.environ.setdefault("DATABASE_URL", dsn)
    os.environ.setdefault("ADMIN_IDS", "111")
    os.environ.setdefault("PUBLIC_URL", "http://127.0.0.1")

    sys.path.insert(0, str(ROOT))
    import uvicorn
    from fastapi import FastAPI

    from app.config import settings
    from app.db import Database
    from app import dungeon as dungeon_rules
    from app import webapp as webapp_module
    from app import dungeon_hero as hero_rules
    from app.dungeon_hero import DungeonHeroRepo
    from app.dungeon_hub import DungeonHub
    from app.dungeon_repo import DungeonBossRepo
    from app.quest_repo import QuestRepo
    from app.webapp import router as webapp_router

    db = Database(dsn)
    await db.connect()
    await db.init_schema()

    repo = DungeonBossRepo(db)
    hub = DungeonHub()
    hero_repo = DungeonHeroRepo(db)
    api = FastAPI()
    api.include_router(webapp_router)
    api.state.settings = settings
    api.state.db = db
    api.state.dungeon = repo
    api.state.hub = hub
    api.state.hero = hero_repo
    api.state.quests = QuestRepo(db)

    config = uvicorn.Config(api, host="127.0.0.1", port=args.port, log_level="error")
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.05)
    if not server.started:
        server.should_exit = True
        await serving
        raise SystemExit("сервер не поднялся")

    base = f"http://127.0.0.1:{args.port}"
    first = sign_init_data(token, TEST_USERS[0], "Тимка")
    second = sign_init_data(token, TEST_USERS[1], "Саня")

    async def call(method: str, path: str, init_data: str, body: dict | None = None):
        return await asyncio.to_thread(http, method, base + path, init_data, body)

    async def wipe() -> None:
        async with db._p().acquire() as con:
            await con.execute(
                "delete from dungeon_boss_players where user_id = any($1::bigint[])",
                list(TEST_USERS),
            )
            await con.execute(
                "delete from dungeon_boss where id not in "
                "(select boss_id from dungeon_boss_players)"
            )
            await con.execute(
                "delete from players where user_id = any($1::bigint[])", list(TEST_USERS)
            )
            await con.execute(
                "delete from dungeon_hero where user_id = any($1::bigint[])",
                list(TEST_USERS),
            )
            await con.execute(
                "delete from quest_claim where user_id = any($1::bigint[])",
                list(TEST_USERS),
            )
            await con.execute(
                "delete from cases where user_id = any($1::bigint[])", list(TEST_USERS)
            )
            await con.execute(
                "delete from upgrader_log where user_id = any($1::bigint[])",
                list(TEST_USERS),
            )

    if not args.keep_rows:
        await wipe()

    try:
        status, denied = await call("POST", "/api/dungeon/boss/join", "", {"zone": 0})
        check("без подписи — отказ", status, 401)
        check("текст отказа на месте", isinstance(denied.get("error"), str), True)

        # Гонка: оба ждут 10 секунд и жмут «в бой» одновременно.
        # Без блокировки каждый создал бы свою комнату и дрался один.
        pair = await asyncio.gather(
            call("POST", "/api/dungeon/boss/join", first, {"zone": 7}),
            call("POST", "/api/dungeon/boss/join", second, {"zone": 7}),
        )
        ids = [((body.get("boss") or {}).get("id")) for _status, body in pair]
        check("одновременный вход: комнаты совпали", len(set(ids)), 1)
        status, together = await call("GET", "/api/dungeon/boss/state", first)
        check("одновременный вход: двое в комнате",
              len((together.get("boss") or {}).get("players") or []), 2)
        check("одновременный вход: кооп", (together.get("boss") or {}).get("coop"), True)
        await call("POST", "/api/dungeon/boss/leave", first, {})
        await call("POST", "/api/dungeon/boss/leave", second, {})

        status, joined = await call("POST", "/api/dungeon/boss/join", first, {"zone": 0})
        check("join отвечает 200", status, 200)
        room = joined.get("boss") or {}
        check("комната в ожидании", room.get("status"), "waiting")
        check("HP одиночного босса", room.get("max_hp"), 300)
        boss_id = room.get("id")
        # Один запрос через пулер идёт около двух секунд, а окно ожидания — 10.
        # Растягиваем окно, иначе тест проверяет сеть, а не логику.
        await hold_room(db, boss_id, 120)

        status, partner = await call("POST", "/api/dungeon/boss/join", second, {"zone": 0})
        partner_room = partner.get("boss") or {}
        check("второй попал в ту же комнату", partner_room.get("id"), boss_id)
        check("бой начался", partner_room.get("status"), "fight")
        check("кооп-множитель HP", partner_room.get("max_hp"), 540)
        check("флаг коопа", partner_room.get("coop"), True)

        status, polled = await call("GET", "/api/dungeon/boss/state", first)
        check("state отвечает 200", status, 200)
        check("state показывает двоих", len((polled.get("boss") or {}).get("players") or []), 2)

        status, punch = await call("POST", "/api/dungeon/boss/hit", first, {"damage": 120})
        hit_room = punch.get("boss") or {}
        check("удар снял HP", hit_room.get("hp"), 420)
        check("урон записан", hit_room.get("hit"), 120)
        check("кулдаун включился", (hit_room.get("cooldown") or 0) > 0, True)

        # Кулдаун проверяем на уровне репозитория: по HTTP между двумя
        # запросами легко проходит больше 0.55 с, и тест станет плавающим.
        from datetime import datetime, timedelta, timezone

        moment = datetime.now(timezone.utc)
        blocked_a = await repo.hit(TEST_USERS[0], 50, moment)
        blocked_b = await repo.hit(TEST_USERS[0], 50, moment + timedelta(milliseconds=50))
        check("кулдаун держит", (blocked_b.get("cooldown") or 0) > 0, True)
        check("HP не изменился", blocked_b["hp"], blocked_a["hp"])

        status, left = await call("POST", "/api/dungeon/boss/leave", first, {})
        check("выход принят", status, 200)
        check("вышел из комнаты", (left.get("left") or {}).get("status"), "left")

        status, alone = await call("GET", "/api/dungeon/boss/state", second)
        check("второй остался", (alone.get("boss") or {}).get("status"), "fight")
        check("кооп-флаг снят", (alone.get("boss") or {}).get("coop"), False)

        status, closed = await call("POST", "/api/dungeon/boss/leave", second, {})
        check("второй вышел", status, 200)

        status, empty = await call("GET", "/api/dungeon/boss/state", first)
        check("комнаты больше нет", (empty.get("boss") or {}).get("status"), "none")

        status, fresh = await call("POST", "/api/dungeon/boss/join", first, {"zone": 2})
        fresh_room = fresh.get("boss") or {}
        check("новая локация", fresh_room.get("zone"), 2)
        await start_room(db, fresh_room.get("id"))
        await call("GET", "/api/dungeon/boss/state", first)
        await rewind(db, fresh_room.get("id"), 30)
        status, hurt = await call("GET", "/api/dungeon/boss/state", first)
        me = ((hurt.get("boss") or {}).get("me") or {})
        check("босс бьёт, пока не смотришь", me.get("hp", 120) < 120, True)
        await call("POST", "/api/dungeon/boss/leave", first, {})

        # Напарник опоздал: бой уже идёт соло, но место свободно —
        # второй должен подсесть в тот же бой, а HP босса подрасти.
        status, late_host = await call("POST", "/api/dungeon/boss/join", first, {"zone": 4})
        host_room = late_host.get("boss") or {}
        await start_room(db, host_room.get("id"))
        status, solo = await call("GET", "/api/dungeon/boss/state", first)
        solo_room = solo.get("boss") or {}
        check("соло-бой уже идёт", solo_room.get("status"), "fight")
        check("соло без коопа", solo_room.get("coop"), False)

        status, late = await call("POST", "/api/dungeon/boss/join", second, {"zone": 4})
        late_room = late.get("boss") or {}
        check("опоздавший в том же бою", late_room.get("id"), host_room.get("id"))
        check("кооп включился на ходу", late_room.get("coop"), True)
        check("HP босса выросло", late_room.get("max_hp") > solo_room.get("max_hp"), True)
        check("в комнате двое", len(late_room.get("players") or []), 2)
        await call("POST", "/api/dungeon/boss/leave", first, {})
        await call("POST", "/api/dungeon/boss/leave", second, {})

        # Победа: добиваем босса и проверяем награду
        async with db._p().acquire() as con:
            yugi_before = float(
                await con.fetchval(
                    "select coalesce(balance, 0) from yugi where user_id = $1::bigint",
                    TEST_USERS[0],
                )
                or 0
            )
        kill_room = await repo.join(TEST_USERS[0], 3, datetime.now(timezone.utc))
        await start_room(db, kill_room["id"])
        await call("GET", "/api/dungeon/boss/state", first)
        last = None
        for _ in range(10):
            await ready_cooldown(db, kill_room["id"])
            last = await repo.hit(TEST_USERS[0], 400, datetime.now(timezone.utc))
            if last["status"] != "fight":
                break
        check("босс добит", (last or {}).get("status"), "dead")
        check("награда за победу", ((last or {}).get("reward") or {}).get("coins"), 264)
        check("убийство зачтено", ((last or {}).get("reward") or {}).get("kills"), 1)
        check("награда в Югах",
              ((last or {}).get("reward") or {}).get("yugi"), dungeon_rules.boss_yugi(3))
        boss_loot = ((last or {}).get("reward") or {}).get("weapon") or ""
        check("оружие с босса: формат",
              bool(__import__("re").match(r"^(sword|bow|staff)_[0-9]_[0-4]$", boss_loot)), True)
        check("оружие с босса: не низкий тир", int(boss_loot.split("_")[1]) >= 2
              if boss_loot else False, True)
        async with db._p().acquire() as con:
            yugi_after = float(
                await con.fetchval(
                    "select coalesce(balance, 0) from yugi where user_id = $1::bigint",
                    TEST_USERS[0],
                )
                or 0
            )
        check("Юги зачислены в кликер", yugi_after - yugi_before,
              float(dungeon_rules.boss_yugi(3)))
        await call("POST", "/api/dungeon/boss/leave", first, {})

        # Живая карта: каждый видит другого с его координатами и анимацией.
        status, mine = await call("POST", "/api/dungeon/presence", first, {
            "x": 100, "y": 9000, "zone": 0, "facing": 2, "anim": "run",
            "hp": 120, "max_hp": 120, "weapon": "bow"})
        check("presence принят", status, 200)
        check("себя в списке нет", len(mine.get("players") or []), 0)
        await call("POST", "/api/dungeon/presence", second, {
            "x": 300, "y": 9100, "zone": 0, "facing": 0, "anim": "attack",
            "hp": 90, "max_hp": 120, "weapon": "sword"})
        status, seen = await call("POST", "/api/dungeon/presence", first, {
            "x": 100, "y": 9000, "zone": 0, "facing": 2, "anim": "idle",
            "hp": 120, "max_hp": 120, "weapon": "bow"})
        others = seen.get("players") or []
        check("видно второго игрока", len(others), 1)
        check("его координаты",
              (others[0]["x"], others[0]["y"]) if others else None, (300.0, 9100.0))
        check("его анимация", others[0]["anim"] if others else None, "attack")
        check("его имя", (others[0]["name"] if others else ""), "Саня")
        await call("POST", "/api/dungeon/presence", second, {
            "x": 300, "y": 100, "zone": 9, "facing": 0, "anim": "idle",
            "hp": 90, "max_hp": 120, "weapon": "sword"})
        status, far = await call("POST", "/api/dungeon/presence", first, {
            "x": 100, "y": 9000, "zone": 0})
        check("через полкарты не видно", len(far.get("players") or []), 0)

        # Основной транспорт: сокет, 10 тактов в секунду, без базы.
        import websockets

        ws_url = f"ws://127.0.0.1:{args.port}/ws/dungeon"
        hub.prune()
        async with websockets.connect(ws_url) as sock_a, \
                websockets.connect(ws_url) as sock_b:
            await sock_a.send(json.dumps({
                "init": first, "x": 500, "y": 9000, "zone": 0, "facing": 1,
                "anim": "run", "hp": 120, "max_hp": 120, "weapon": "bow"}))
            hello = json.loads(await asyncio.wait_for(sock_a.recv(), 10))
            check("сокет: свой игрок принят", hello.get("ok"), True)

            await sock_b.send(json.dumps({
                "init": second, "x": 640, "y": 9050, "zone": 0, "facing": 2,
                "anim": "attack", "hp": 80, "max_hp": 120, "weapon": "sword"}))
            await asyncio.wait_for(sock_b.recv(), 10)

            await sock_a.send(json.dumps({
                "init": first, "x": 510, "y": 9010, "zone": 0, "facing": 1,
                "anim": "run", "hp": 120, "max_hp": 120, "weapon": "bow"}))
            snapshot = json.loads(await asyncio.wait_for(sock_a.recv(), 10))
            others = snapshot.get("players") or []
            check("сокет: видно напарника", len(others), 1)
            check("сокет: его координаты",
                  (others[0]["x"], others[0]["y"]) if others else None, (640.0, 9050.0))
            check("сокет: его анимация", others[0]["anim"] if others else None, "attack")

        async with websockets.connect(ws_url) as sock_x:
            await sock_x.send(json.dumps({"init": "плохая подпись", "x": 1, "y": 1, "zone": 0}))
            denied = json.loads(await asyncio.wait_for(sock_x.recv(), 10))
            check("сокет: без подписи отказ", isinstance(denied.get("error"), str), True)
        for _ in range(20):
            if len(hub) == 0:
                break
            await asyncio.sleep(0.1)
        check("сокет: точки не остались в памяти", len(hub), 0)

        # Чат: тот же сокет, отдельный кадр, общий на всех в подземелье
        async with websockets.connect(ws_url) as sock_a, \
                websockets.connect(ws_url) as sock_b:
            for sock, init_data, spot_x in ((sock_a, first, 500), (sock_b, second, 640)):
                await sock.send(json.dumps({
                    "init": init_data, "x": spot_x, "y": 9000, "zone": 0}))
                await asyncio.wait_for(sock.recv(), 10)          # снапшот на вход
            await sock_a.send(json.dumps({"type": "chat", "text": "  привет   карта  "}))
            mine_msg = json.loads(await asyncio.wait_for(sock_a.recv(), 10))
            other_msg = json.loads(await asyncio.wait_for(sock_b.recv(), 10))
            check("чат: тип кадра", mine_msg.get("type"), "chat")
            check("чат: лишние пробелы убраны", mine_msg.get("text"), "привет карта")
            check("чат: имя отправителя", mine_msg.get("name"), "Тимка")
            check("чат: дошло второму", other_msg.get("text"), "привет карта")

        # Прогресс героя: сохраняется в базе и переживает перезагрузку страницы
        status, fresh_hero = await call("GET", "/api/dungeon/hero", first)
        check("герой: пустой прогресс по умолчанию",
              (fresh_hero.get("hero") or {}).get("level"), 1)
        status, saved = await call("POST", "/api/dungeon/hero", first, {
            "level": 27, "exp": 430, "coins": 51234, "kills": 210,
            "weapon": "bow_3_1", "bag": ["bow_3_1", "мусор", "bow_3_1", "sword_1_0"]})
        hero_data = saved.get("hero") or {}
        check("герой: сохранён", status, 200)
        check("герой: уровень", hero_data.get("level"), 27)
        check("герой: монеты", hero_data.get("coins"), 51234)
        check("герой: мусор из сумки выкинут", hero_data.get("bag"),
              ["bow_3_1", "sword_1_0"])
        check("герой: оружие в руках", hero_data.get("weapon"), "bow_3_1")
        status, again = await call("GET", "/api/dungeon/hero", first)
        check("герой: читается после записи",
              (again.get("hero") or {}).get("level"), 27)
        status, clipped = await call("POST", "/api/dungeon/hero", first, {
            "level": 100000, "coins": -5, "weapon": "ракета", "bag": "не список"})
        clipped_hero = clipped.get("hero") or {}
        check("герой: уровень обрезан", clipped_hero.get("level"), 999)
        check("герой: монеты не отрицательные", clipped_hero.get("coins"), 0)
        check("герой: пушка из ракеты не вышла", clipped_hero.get("weapon") in (None, "bow_3_1"),
              True)

        # Улучшение оружия: цена на сервере, монеты списываются из прогресса
        await call("POST", "/api/dungeon/hero", first, {
            "level": 27, "coins": 5000, "weapon": "bow_3_1", "bag": ["bow_3_1"]})
        status, offer = await call("GET", "/api/dungeon/hero", first)
        offer_data = (offer.get("hero") or {}).get("upgrade") or {}
        check("улучшение: оффер есть", offer_data.get("next"), "bow_4_1")
        check("улучшение: цена", offer_data.get("price"), hero_rules.upgrade_price("bow_3_1"))
        status, upgraded = await call("POST", "/api/dungeon/upgrade", first,
                                      {"weapon": "bow_3_1"})
        upgraded_hero = upgraded.get("hero") or {}
        check("улучшение: оружие стало выше", upgraded_hero.get("weapon"), "bow_4_1")
        check("улучшение: монеты списаны", upgraded_hero.get("coins"),
              5000 - hero_rules.upgrade_price("bow_3_1"))
        check("улучшение: в сумке тоже", upgraded_hero.get("bag"), ["bow_4_1"])
        status, broke = await call("POST", "/api/dungeon/upgrade", first,
                                   {"weapon": "bow_4_1"})
        check("улучшение: без монет отказ", status, 400)
        check("улучшение: текст ошибки", isinstance((broke or {}).get("error"), str), True)
        status, wrong = await call("POST", "/api/dungeon/upgrade", first,
                                   {"weapon": "sword_1_1"})
        check("улучшение: чужое оружие отказ", status, 400)
        status, maxed = await call("POST", "/api/dungeon/upgrade", first,
                                   {"weapon": "bow_9_0"})
        check("улучшение: максимум отказ", status, 400)

        # Броня за Юги и таблица лидеров
        await call("POST", "/api/dungeon/hero", first, {
            "level": 5, "coins": 0, "weapon": "bow_3_1", "bag": ["bow_3_1"]})
        async with db._p().acquire() as con:
            await con.execute(
                "insert into yugi (user_id, balance, total) values ($1::bigint, 5000, 5000) "
                "on conflict (user_id) do update set balance = 5000",
                TEST_USERS[0],
            )
        status, armor1 = await call("POST", "/api/dungeon/armor", first, {})
        hero1 = armor1.get("hero") or {}
        check("броня: куплена", hero1.get("armor"), 1)
        check("броня: скидка урона", hero1.get("armor_discount"), 0.04)
        async with db._p().acquire() as con:
            yugi_left = float(
                await con.fetchval(
                    "select balance from yugi where user_id = $1::bigint",
                    TEST_USERS[0],
                )
                or 0
            )
        check("броня: Юги списаны", yugi_left, 4500.0)
        check("броня: следующая ступень дороже",
              (hero1.get("armor_offer") or {}).get("price"),
              dungeon_rules.armor_price(1, 0))
        async with db._p().acquire() as con:
            await con.execute(
                "update yugi set balance = 0 where user_id = $1::bigint", TEST_USERS[0]
            )
        status, armor_broke = await call("POST", "/api/dungeon/armor", first, {})
        check("броня: без Югов отказ", status, 400)

        status, top = await call("GET", "/api/dungeon/top", first)
        top_rows = top.get("players") or []
        check("лидеры: список не пустой", len(top_rows) >= 1, True)
        check("лидеры: я в таблице",
              any(row["id"] == TEST_USERS[0] for row in top_rows), True)
        check("лидеры: поля на месте",
              sorted(top_rows[0].keys()) if top_rows else [],
              ["armor", "coins", "id", "kills", "level", "name"])

        # Оффлайн: точка сохраняется, и игрока видно спящим в углу локации
        await call("POST", "/api/dungeon/hero", second, {
            "level": 4, "coins": 10, "weapon": "bow_1_1", "bag": ["bow_1_1"]})
        await hero_repo.save_spot(TEST_USERS[1], 2, 300, 4500)
        async with db._p().acquire() as con:
            await con.execute(
                "update dungeon_hero set seen_at = now() - interval '40 seconds' "
                "where user_id = $1::bigint",
                TEST_USERS[1],
            )
        webapp_module._OFFLINE_CACHE["at"] = 0.0
        async with websockets.connect(ws_url) as sock:
            await sock.send(json.dumps({"init": first, "x": 100, "y": 9000, "zone": 2}))
            frame = json.loads(await asyncio.wait_for(sock.recv(), 10))
            sleeping = frame.get("offline") or []
            check("оффлайн: видно спящего",
                  any(row["id"] == TEST_USERS[1] for row in sleeping), True)
            his = next((row for row in sleeping if row["id"] == TEST_USERS[1]), {})
            check("оффлайн: его локация", his.get("zone"), 2)
            check("оффлайн: его имя", his.get("name"), "Саня")
        status, woke = await call("GET", "/api/dungeon/hero", second)
        hero_woke = woke.get("hero") or {}
        check("пробуждение: локация помнится", hero_woke.get("zone"), 2)
        check("пробуждение: точка помнится", round(hero_woke.get("x") or 0), 300)

        # Древо кликера: список узлов и покупка за фишки
        status, yugi_state = await call("GET", "/api/yugi", first)
        check("древо: узлов в пуле", len(yugi_state.get("tree_pool") or []), 110)
        async with db._p().acquire() as con:
            await con.execute(
                "update players set yugi_chips = 10, yugi_tree = '[]'::jsonb "
                "where user_id = $1::bigint",
                TEST_USERS[0],
            )
        status, bought = await call("POST", "/api/yugi/tree", first, {"id": "t_cur_0"})
        check("древо: покупка", status, 200)
        check("древо: списано фишек", bought.get("spent"), 1)
        status, again = await call("POST", "/api/yugi/tree", first, {"id": "t_cur_0"})
        check("древо: повторно нельзя", status, 400)
        status, after = await call("GET", "/api/yugi", first)
        check("древо: узел засчитан", "t_cur_0" in (after.get("tree") or []), True)
        check("древо: фишки убавились", int(after.get("chips") or 0), 9)

        status, tapped = await call("POST", "/api/yugi/tap", first, {"count": 5})
        check("кликер: тап не теряет древо",
              len(tapped.get("tree_pool") or []), 110)
        check("кликер: тап отдаёт фишки", int(tapped.get("chips") or -1), 9)

        # Профили: поиск по имени и чужой профиль по ?u=
        status, found = await call("GET", "/api/profile/search?q=", first)
        check("профиль: запрос без букв", status, 200)
        status, fresh = await call("GET", "/api/profile?u=" + str(TEST_USERS[1]), first)
        check("профиль: чужой по u=", status, 200)
        check("профиль: is_me false", (fresh or {}).get("is_me"), False)
        check("профиль: имя есть", bool((fresh or {}).get("name")), True)
        check("профиль: баннер и аватар",
              bool((fresh or {}).get("banner_css")) and bool((fresh or {}).get("initial")), True)

        # Квесты: награда забирается кнопкой, ровно один раз
        async with db._p().acquire() as con:
            await con.execute(
                "insert into upgrader_log (user_id, from_card, to_card, chance, won) "
                "values ($1::bigint, 'a', 'b', 0.5, true)",
                TEST_USERS[0],
            )
        status, quest_list = await call("GET", "/api/quests", first)
        items = {q["key"]: q for q in (quest_list.get("quests") or [])}
        check("квесты: весь список", len(items), 7)
        check("квесты: апгрейд засчитан", (items.get("upgrades") or {}).get("done"), True)
        check("квесты: ещё не забран", (items.get("upgrades") or {}).get("claimed"), False)
        check("квесты: награда описана",
              isinstance((items.get("upgrades") or {}).get("reward_text"), str), True)
        status, claim = await call("POST", "/api/quests/claim", first, {"key": "upgrades"})
        check("квесты: награда выдана", status, 200)
        check("квесты: очки", (claim.get("reward") or {}).get("points"), 20000)
        check("квесты: награда без кейса", (claim.get("reward") or {}).get("cases"), None)
        check("квесты: баланс вырос", (claim.get("balance") or 0) >= 20000, True)
        status, again_claim = await call("POST", "/api/quests/claim", first,
                                         {"key": "upgrades"})
        check("квесты: второй раз отказ", status, 400)
        status, not_done = await call("POST", "/api/quests/claim", first, {"key": "casino"})
        check("квесты: невыполненный отказ", status, 400)
        status, unknown = await call("POST", "/api/quests/claim", first,
                                     {"key": "нет такого"})
        check("квесты: неизвестный отказ", status, 400)
        status, after = await call("GET", "/api/quests", first)
        after_items = {q["key"]: q for q in (after.get("quests") or [])}
        check("квесты: помечено полученным",
              (after_items.get("upgrades") or {}).get("claimed"), True)
    finally:
        if not args.keep_rows:
            await wipe()
        server.should_exit = True
        await serving
        await db.close()

    print("\nпроблем: %d" % PROBLEMS)
    return 1 if PROBLEMS else 0


async def rewind(db, boss_id, seconds: int) -> None:
    async with db._p().acquire() as con:
        await con.execute(
            "update dungeon_boss_players set "
            "last_boss_hit_at = now() - ($2::int * interval '1 second'), "
            "seen_at = now() where boss_id = $1::bigint",
            int(boss_id or 0),
            int(seconds),
        )


async def ready_cooldown(db, boss_id) -> None:
    """Снимаем кулдаун удара игрока, чтобы не спать по полсекунды."""
    async with db._p().acquire() as con:
        await con.execute(
            "update dungeon_boss_players set last_hit_at = now() - interval '2 seconds' "
            "where boss_id = $1::bigint",
            int(boss_id or 0),
        )


async def start_room(db, boss_id) -> None:
    """Сдвигаем ожидание в прошлое, чтобы бой начался без десяти секунд."""
    async with db._p().acquire() as con:
        await con.execute(
            "update dungeon_boss set ready_at = now() - interval '1 second' "
            "where id = $1::bigint",
            int(boss_id or 0),
        )


async def hold_room(db, boss_id, seconds: int) -> None:
    """Растягиваем окно ожидания, чтобы медленная сеть не ломала сценарий."""
    async with db._p().acquire() as con:
        await con.execute(
            "update dungeon_boss set ready_at = now() + ($2::int * interval '1 second') "
            "where id = $1::bigint",
            int(boss_id or 0),
            int(seconds),
        )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
