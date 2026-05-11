"""PulseWatch demo: создаёт юзера + сервер + правила + гонит фейковые метрики.

Запуск: `make demo` (поднимет стек + миграции + этот скрипт) или
        `uv run python scripts/demo.py`.

Идея: за минуту получить рабочую установку с триггером алертов, не возясь
с регистрацией и сборкой агента. Каждый запуск создаёт сервер со случайным
суффиксом, поэтому повторные запуски не конфликтуют. Старые demo-серверы
вычищай через бот: /delete <id>.
"""

import asyncio
import random
import secrets

import httpx

BASE_URL = "http://localhost:8000"
EMAIL = "demo@pulsewatch.local"
PASSWORD = "demopass123"
METRIC_INTERVAL_SECONDS = 5


async def setup(client: httpx.AsyncClient) -> tuple[int, str]:
    """Возвращает (server_id, api_key). Юзер reuse-ится, сервер уникальный per-run."""
    # 1. Регистрация (409 если уже есть — норма)
    r = await client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    if r.status_code not in (201, 409):
        r.raise_for_status()

    # 2. Login
    r = await client.post(
        "/auth/login",
        data={"username": EMAIL, "password": PASSWORD},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    r.raise_for_status()
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # 3. Уникальное имя сервера: каждый запуск свежий
    suffix = secrets.token_hex(2)
    server_name = f"demo-srv-{suffix}"
    r = await client.post(
        "/servers/register",
        json={"name": server_name},
        headers=headers,
    )
    r.raise_for_status()
    payload = r.json()
    server_id = payload["id"]
    api_key = payload["api_key"]

    # 4. Пара правил с низкими порогами — будут срабатывать часто
    rules = [
        {
            "name": f"{server_name} cpu high",
            "server_id": server_id,
            "metric_type": "system",
            "metric_field": "cpu_percent",
            "operator": "gt",
            "threshold_value": 60.0,
            "cooldown_seconds": 60,
        },
        {
            "name": f"{server_name} memory high",
            "server_id": server_id,
            "metric_type": "system",
            "metric_field": "memory_percent",
            "operator": "gt",
            "threshold_value": 60.0,
            "cooldown_seconds": 60,
        },
    ]
    for rule in rules:
        r = await client.post("/alerts/rules", json=rule, headers=headers)
        r.raise_for_status()

    print("✅ Demo-setup готов")
    print(f"   Email / password: {EMAIL} / {PASSWORD}")
    print(f"   Server: #{server_id} «{server_name}»")
    print(f"   API key: {api_key}")
    print("   Rules: cpu>60, memory>60 (cooldown 60s)")
    print(f"   UI: {BASE_URL}/")
    return server_id, api_key


async def fake_agent(client: httpx.AsyncClient, api_key: str) -> None:
    """Шлёт случайные метрики каждые METRIC_INTERVAL_SECONDS секунд.

    Разброс 20-90% — половина итераций пробивает порог 60%. Через минуту-две
    в `/alerts/events` появятся события, а если настроены Telegram/email —
    придёт уведомление.
    """
    headers = {"X-API-Key": api_key}
    print(f"\n🤖 Fake-agent шлёт метрики каждые {METRIC_INTERVAL_SECONDS}с (Ctrl+C для остановки)")
    while True:
        payload = {
            "cpu_percent": random.uniform(20, 90),
            "memory_percent": random.uniform(20, 90),
            "disk_percent": random.uniform(40, 70),
            "agent_version": "demo-fake-0.0.1",
        }
        status_label: str
        try:
            r = await client.post("/metrics", json=payload, headers=headers)
            status_label = str(r.status_code)
        except httpx.HTTPError as exc:
            status_label = f"err: {exc}"
        print(
            f"  cpu={payload['cpu_percent']:5.1f}% "
            f"mem={payload['memory_percent']:5.1f}% "
            f"disk={payload['disk_percent']:5.1f}% → {status_label}"
        )
        await asyncio.sleep(METRIC_INTERVAL_SECONDS)


async def main() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # Проверим что бэкенд жив
        try:
            r = await client.get("/health")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"❌ Бэкенд недоступен на {BASE_URL}: {exc}")
            print("   Подними стек: `make up` или `docker compose up -d`")
            return

        _server_id, api_key = await setup(client)
        try:
            await fake_agent(client, api_key)
        except KeyboardInterrupt:
            print("\nостановлен")


if __name__ == "__main__":
    asyncio.run(main())
