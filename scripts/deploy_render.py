"""Автодеплой на Render через Render API + проверка вебхука в Telegram.

Запуск (нужны VPN/доступ к api.render.com и api.telegram.org):

  python scripts/deploy_render.py

Переменные окружения:
  RENDER_API_KEY   - Account Settings -> API Keys (обязательно)
  BOT_TOKEN        - токен бота от @BotFather (обязательно)
  DATABASE_URL     - строка Supabase (обязательно)
  GITHUB_REPO      - по умолчанию https://github.com/CrunchyPersik1/severo-yug-bot
  SERVICE_NAME     - по умолчанию severo-yug-bot
  REGION           - по умолчанию frankfurt
  DRY_RUN=1        - только показать план, ничего не менять

Скрипт идемпотентен: если сервис уже есть, он обновит переменные окружения
и запустит новый деплой, а не создаст дубль.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.render.com/v1"
REPO = os.getenv("GITHUB_REPO", "https://github.com/CrunchyPersik1/severo-yug-bot")
SERVICE_NAME = os.getenv("SERVICE_NAME", "severo-yug-bot")
REGION = os.getenv("REGION", "frankfurt")
DRY_RUN = os.getenv("DRY_RUN") == "1"

BUILD_COMMAND = "pip install -r requirements.txt"
START_COMMAND = "uvicorn main:app --host 0.0.0.0 --port $PORT"


def need(name: str) -> str:
    value = os.getenv(name)
    if not value:
        sys.exit(f"Не задана переменная окружения {name}")
    return value


def call(method: str, path: str, body: dict | list | None = None) -> object:
    key = need("RENDER_API_KEY")
    request = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode()
    except urllib.error.HTTPError as error:
        detail = error.read().decode()[:800]
        sys.exit(f"Render API {method} {path} -> {error.code}\n{detail}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def find_owner() -> str:
    owners = call("GET", "/owners?limit=20")
    if not owners:
        sys.exit("Не нашёл workspace в Render. Проверь ключ.")
    owner = owners[0]["owner"]
    print(f"· workspace: {owner['name']} ({owner['id']})")
    return owner["id"]


def find_service(name: str) -> dict | None:
    services = call("GET", "/services?limit=100") or []
    for item in services:
        service = item["service"]
        if service["name"] == name:
            return service
    return None


def create_service(owner_id: str) -> dict:
    details = {
        "env": "python",
        "plan": "free",
        "region": REGION,
        "healthCheckPath": "/",
        "envSpecificDetails": {
            "buildCommand": BUILD_COMMAND,
            "startCommand": START_COMMAND,
        },
    }
    payload = {
        "type": "web_service",
        "name": SERVICE_NAME,
        "ownerId": owner_id,
        "repo": REPO,
        "branch": "main",
        "autoDeploy": "yes",
        "serviceDetails": details,
    }
    try:
        created = call("POST", "/services", payload)
    except SystemExit as error:
        # некоторые версии API ждут поля верхнего уровня
        print("· плоская схема запроса:", error)
        payload = {
            "type": "web_service",
            "name": SERVICE_NAME,
            "ownerId": owner_id,
            "repo": REPO,
            "branch": "main",
            "autoDeploy": "yes",
            **details,
        }
        created = call("POST", "/services", payload)
    assert isinstance(created, dict)
    service = created.get("service", created)
    print(f"· сервис создан: {service['id']}")
    return service


def push_env(service_id: str, bot_token: str, database_url: str) -> None:
    headers_env = [
        {"key": "PYTHON_VERSION", "value": "3.12.7"},
        {"key": "BOT_TOKEN", "value": bot_token},
        {"key": "DATABASE_URL", "value": database_url},
        {"key": "WEBHOOK_SECRET", "generateValue": True},
        {"key": "WEBHOOK_TOKEN", "generateValue": True},
    ]
    call("PUT", f"/services/{service_id}/env-vars", headers_env)
    print("· переменные окружения обновлены")


def latest_deploy(service_id: str) -> dict | None:
    deploys = call("GET", f"/services/{service_id}/deploys?limit=1")
    if not deploys:
        return None
    return deploys[0]["deploy"]


def wait_for_deploy(service_id: str, timeout: int = 900) -> dict:
    started = time.time()
    seen = None
    while time.time() - started < timeout:
        deploy = latest_deploy(service_id)
        if deploy and deploy["id"] != seen:
            seen = deploy["id"]
            print(f"· деплой {seen}: {deploy['status']}")
        if deploy and deploy["status"] in {"live", "build_failed", "update_failed", "canceled"}:
            return deploy
        time.sleep(15)
    sys.exit("Деплой не завершился за отведённое время")


def telegram(method: str, token: str, params: dict | None = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        return json.loads(error.read().decode())


def main() -> None:
    bot_token = need("BOT_TOKEN")
    database_url = need("DATABASE_URL")
    need("RENDER_API_KEY")

    me = telegram("getMe", bot_token)
    if not me.get("ok"):
        sys.exit(f"Токен бота не работает: {me}")
    print(f"· бот: @{me['result']['username']}")

    database_url = database_url.replace("-pooler", "-pooler")  # на всякий случай
    if "sslmode" not in database_url and "supabase" in database_url:
        database_url += ("&" if "?" in database_url else "?") + "sslmode=require"

    if DRY_RUN:
        print("DRY_RUN: сервис, переменные и вебхук не трогаем")
        return

    owner_id = find_owner()
    service = find_service(SERVICE_NAME) or create_service(owner_id)
    service_id = service["id"]
    push_env(service_id, bot_token, database_url)

    deploy = call("POST", f"/services/{service_id}/deploys", {"clearCache": "do_not_clear"})
    print(f"· запущен деплой: {deploy.get('id') if isinstance(deploy, dict) else deploy}")
    result = wait_for_deploy(service_id)

    service = call("GET", f"/services/{service_id}")
    assert isinstance(service, dict)
    url = service.get("serviceDetails", {}).get("url") or service.get("service", {}).get("serviceDetails", {}).get("url")
    print(f"· статус: {result['status']}")
    print(f"· адрес: {url}")
    if result["status"] != "live":
        sys.exit("Деплой не удался — смотри логи в дашборде Render")

    hook = telegram("getWebhookInfo", bot_token)
    print("· webhook:", json.dumps(hook.get("result", {}), ensure_ascii=False))


if __name__ == "__main__":
    main()
