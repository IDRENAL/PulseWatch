# PulseWatch

Self-hosted система мониторинга серверов: агенты собирают метрики (CPU/RAM/диск + Docker-контейнеры + journald-логи), отправляют на бэкенд, который сохраняет в Postgres, агрегирует, проверяет алерт-правила, шлёт уведомления в Telegram и отдаёт реал-тайм поток через WebSocket.

Учебный проект, реализующий 7-этапный план разработки. Текущее состояние: этапы 1–7 закрыты, в TODO остаются frontend-дашборд и привязка Telegram через `/start`-бот.

## Архитектура

```
┌─────────┐  HTTP+JSON     ┌──────────┐    SQL     ┌──────────┐
│ agent   │ ─────────────▶ │ backend  │ ─────────▶ │ Postgres │
│ (psutil)│  metrics+logs  │ FastAPI  │            └──────────┘
│ docker  │                │          │  pub/sub   ┌──────────┐
│ logs    │ ◀──── WS ────▶ │          │ ─────────▶ │  Redis   │
└─────────┘                └──────────┘            └──────────┘
                                ▲                        │
                                │ subscribe              │
                                ▼                        ▼
                        ┌──────────────┐         ┌──────────────┐
                        │ dashboard    │         │ Celery worker│
                        │ (WebSocket)  │         │ + Beat       │
                        └──────────────┘         │ (агрегация,  │
                                                 │  heartbeat)  │
                                                 └──────────────┘
```

**Кто за что отвечает:**

- **Агент** — Python-процесс на наблюдаемом сервере. `psutil` для системных метрик, Docker SDK для контейнеров, journalctl для логов. Шлёт раз в 10 секунд через `httpx`.
- **Backend (FastAPI)** — приём метрик, JWT-аутентификация юзеров, API-ключи для агентов, REST + WebSocket эндпоинты.
- **Postgres** — хранит юзеров (с привязкой к Telegram-чату), серверы, raw-метрики (24ч), агрегаты (`metric_aggregates`, `docker_aggregates`), алерт-правила и события.
- **Redis** — Pub/Sub для real-time дашборда, кэш дашборда (10s TTL), хранилище rate-лимитов (db=3), Celery broker (db=1) и backend (db=2).
- **Celery + Beat** — 5-минутная/почасовая/посуточная агрегация, heartbeat-проверка (помечает сервер неактивным, если метрик нет >5 мин), auto-resolve алертов, отправка уведомлений в Telegram.

## Стек

| Компонент | Версия |
|---|---|
| Python | 3.12+ |
| FastAPI | 0.136+ |
| SQLAlchemy | 2.0 (async) |
| Postgres | 16 |
| Redis | 7 |
| Celery | 5.4+ |
| Alembic | 1.18+ |
| psutil | 6.1+ |
| docker SDK | 7.1+ |
| pytest + pytest-asyncio | 9 / 1.3 |
| uv | менеджер зависимостей |

## Быстрый старт

Требования: Docker + Docker Compose v2, [`uv`](https://github.com/astral-sh/uv) для локальной разработки.

```bash
# 1. .env
cp .env.example .env
# отредактируй DB_PASSWORD, SECRET_KEY (для SECRET_KEY: python -c "import secrets; print(secrets.token_urlsafe(32))")

# 2. Поднять стек (Postgres + Redis + backend + Celery worker + Celery beat)
make up

# 3. Прогнать миграции
make migrate

# 4. Зарегистрировать юзера и получить токен
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"me@example.com","password":"secret123"}'

curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=me@example.com&password=secret123"
# → {"access_token": "<JWT>", "token_type": "bearer"}

# 5. Зарегистрировать сервер и получить API-ключ для агента
curl -X POST http://localhost:8000/servers/register \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{"name":"web-prod-01"}'
# → {"id": 1, "api_key": "1.<секрет>", ...} — секрет показывается ОДИН раз
```

Сервис доступен на `http://localhost:8000`. OpenAPI: `http://localhost:8000/docs`.

> Контейнеры `worker` и `beat` (Celery) поднимаются автоматически вместе с `app`. Если работаешь локально без Docker — запусти их вручную: `uv run celery -A app.tasks.celery_app worker -l info` и `uv run celery -A app.tasks.celery_app beat -l info` в разных терминалах.

## Переменные окружения

| Имя | Описание |
|---|---|
| `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME` | Postgres-подключение |
| `REDIS_HOST`, `REDIS_PORT` | Redis-подключение |
| `SECRET_KEY` | Ключ для подписи JWT. Не дефолтный, не пустой |
| `ALGORITHM` | Алгоритм JWT (по умолчанию `HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | TTL access-токена |
| `TELEGRAM_BOT_TOKEN` | Токен бота от `@BotFather`. Опционально — если пусто, уведомления отключены |
| `AGENT_API_URL` | URL бэкенда для агента |
| `AGENT_API_KEY` | API-ключ от `/servers/register`, формат `<server_id>.<secret>` |
| `AGENT_SEND_INTERVAL_SECONDS` | Период отправки метрик (по умолчанию 10с) |

## API

Все защищённые эндпоинты требуют `Authorization: Bearer <JWT>`. Эндпоинты приёма метрик от агента — `X-API-Key: <server_id>.<secret>`.

### Auth
- `POST /auth/register` — регистрация юзера. Лимит **3/min на IP**.
- `POST /auth/login` — логин (form-encoded). Лимит **5/min на IP**.
- `GET /auth/me` — текущий юзер.
- `PATCH /auth/me/telegram` — привязать/отвязать Telegram chat_id. Тело: `{"chat_id": "12345"}` или `{"chat_id": null}`.

### Серверы
- `POST /servers/register` — создать сервер, получить API-ключ.
- `GET /servers/me` — список своих серверов.
- `GET /servers/dashboard` — сводка с последними метриками (10s Redis-кэш).

### Метрики
- `POST /metrics` *(агент)* — отправить системную метрику.
- `GET /servers/{id}/metrics?limit=N` — последние N метрик.
- `GET /servers/{id}/metrics/aggregate?period=fivemin|hourly|daily&limit=N` — агрегаты.
- `GET /servers/{id}/metrics/export?start=&end=&granularity=raw|fivemin|hourly|daily` — CSV-экспорт.

### Docker-метрики
- `POST /docker-metrics` *(агент)* — отправить пачку метрик контейнеров.
- `GET /servers/{id}/docker-metrics?container_id=X&limit=N`
- `GET /servers/{id}/docker-metrics/aggregate?period=...&container_name=X`
- `GET /servers/{id}/docker-metrics/export?start=&end=&granularity=...&container_name=X` — CSV.

### Алерты
- `POST/GET/PATCH/DELETE /alerts/rules` — CRUD правил порогов.
- `GET /alerts/events` — история срабатываний (с полем `resolved_at`).
- При срабатывании: задача в Celery шлёт сообщение в Telegram (если у юзера привязан chat_id и токен бота настроен), плюс публикация в Redis Pub/Sub.
- Auto-resolve: раз в минуту Celery-beat проверяет открытые системные события — если последняя метрика больше не пробивает порог, в `resolved_at` ставится текущее время.

### WebSocket
- `WS /ws/metrics/{server_id}?token=<JWT>` — real-time поток метрик владельцу сервера.
- `WS /ws/logs/{server_id}?token=<JWT>` — поток journald-логов.
- `WS /ws/agent/logs?api_key=...` — агент пушит логи в бэкенд.

### Лимиты CSV-экспорта

| `granularity` | Источник | Макс. диапазон |
|---|---|---|
| `raw` | `metrics` / `docker_metrics` | 24 часа |
| `fivemin` | `metric_aggregates` (period=fivemin) | 7 дней |
| `hourly` | `metric_aggregates` (period=hourly) | 30 дней |
| `daily` | `metric_aggregates` (period=daily) | 365 дней |

При превышении — `400 Bad Request`.

## Telegram-уведомления

1. Создай бота через [`@BotFather`](https://t.me/BotFather) (`/newbot` → имя → username с суффиксом `bot`). Получишь токен формата `7234567890:AAH...`.
2. Добавь токен в `.env`: `TELEGRAM_BOT_TOKEN=7234567890:AAH...`
3. Перезапусти стек (`make down && make up`) — без токена фича выключена молча.
4. Узнай свой `chat_id`. Самый быстрый способ — написать боту [`@userinfobot`](https://t.me/userinfobot), он ответит твоим ID. **Перед этим напиши своему боту любое сообщение** (например, `/start`), иначе он не сможет тебе писать.
5. Привяжи `chat_id` к юзеру:
   ```bash
   curl -X PATCH http://localhost:8000/auth/me/telegram \
     -H "Authorization: Bearer <JWT>" \
     -H "Content-Type: application/json" \
     -d '{"chat_id":"123456789"}'
   ```
6. Создай алерт-правило с низким порогом и подожди следующую метрику от агента — бот напишет в чат.

Отвязать chat_id: `PATCH /auth/me/telegram` с телом `{"chat_id": null}`.

## Установка агента на наблюдаемый сервер

```bash
# 1. Создаём пользователя и каталог
sudo useradd -r -s /usr/sbin/nologin pulsewatch
sudo mkdir -p /opt/pulsewatch /etc/pulsewatch
sudo chown -R pulsewatch:pulsewatch /opt/pulsewatch

# 2. Копируем код агента (или клонируем репу)
sudo -u pulsewatch git clone https://your-repo.git /opt/pulsewatch
cd /opt/pulsewatch
sudo -u pulsewatch uv sync --frozen --no-dev

# 3. Конфиг агента
sudo tee /etc/pulsewatch/agent.env > /dev/null <<EOF
AGENT_API_URL=https://pulsewatch.example.com
AGENT_API_KEY=1.<секрет_из_servers_register>
AGENT_SEND_INTERVAL_SECONDS=10
EOF
sudo chmod 600 /etc/pulsewatch/agent.env
sudo chown pulsewatch:pulsewatch /etc/pulsewatch/agent.env

# 4. systemd-юнит
sudo cp agent/pulsewatch-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pulsewatch-agent
sudo systemctl status pulsewatch-agent
```

Если агенту нужен Docker — добавь юзера `pulsewatch` в группу `docker`.
Для journald-логов — в группу `systemd-journal`.

## Разработка

```bash
# Зависимости (один раз)
uv sync

# pre-commit хуки (один раз — ставит .git/hooks/pre-commit)
uv run pre-commit install

# Тесты (требуют запущенного Postgres+Redis из docker-compose)
make test
# или
uv run pytest -v

# Линтер + форматтер
uv run ruff check --fix .
uv run ruff format .

# Тайпчек
uv run mypy .

# Миграции
uv run alembic revision --autogenerate -m "описание"
uv run alembic upgrade head

# Запуск агента локально
make agent
```

### Структура

```
app/
  api/        # FastAPI роутеры
  core/       # security, rate_limit, connection manager
  models/     # SQLAlchemy модели
  schemas/    # Pydantic-схемы (вход/выход)
  services/   # бизнес-логика (threshold, aggregation, alert_resolver, telegram)
  tasks/      # Celery задачи (агрегация, heartbeat, notification, resolve)
  utils/      # стриминг CSV
agent/
  collectors/ # system (psutil), docker (SDK), logs (journald)
  agent.py, sender.py, logs_streamer.py
alembic/      # миграции
tests/
docs/         # планы этапов
```

## Известные ограничения / TODO

- Привязка Telegram сейчас ручная (юзер сам узнаёт `chat_id` через `@userinfobot`). Удобнее было бы через `/start <код>` — этот flow требует отдельного процесса polling/webhook.
- Auto-resolve работает только для системных алертов. Docker-резолв не реализован — у `AlertEvent` нет колонки `container_name`, чтобы понять метрики какого контейнера перепроверять.
- Frontend для дашборда отсутствует — WebSocket-потоки можно посмотреть только через клиент или devtools.
- Email-уведомления не реализованы (только Telegram).

## Лицензия

Учебный проект, лицензии нет.
