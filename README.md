# PulseWatch

![CI](https://github.com/IDRENAL/PulseWatch/actions/workflows/ci.yml/badge.svg)

Self-hosted система мониторинга серверов: агенты собирают метрики (CPU/RAM/диск + Docker-контейнеры + journald-логи), отправляют на бэкенд, который сохраняет в Postgres, агрегирует, проверяет алерт-правила, шлёт уведомления в Telegram и email, отдаёт реал-тайм поток через WebSocket в браузерный дашборд, а HTTP-метрики бэкенда отдаёт в Prometheus-формате для Grafana.

Учебный проект, реализующий 7-этапный план разработки + хвостовые фичи поверх (telegram-бот с командами админки, email-канал, auto-resolve, per-channel mute, Prometheus/Grafana, refresh-токены с reuse-detection, TOTP 2FA, password reset, audit log, persisted logs, Slack-receiver, frontend-дашборд с тёмной/светлой темой, RU/EN i18n, мобильной вёрсткой, /v1 API-версионированием).

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

- **Агент** — Python-процесс на наблюдаемом сервере. `psutil` для системных метрик, Docker SDK для контейнеров, journalctl для логов. Шлёт раз в 10 секунд через `httpx`, в каждой системной метрике передаёт свою версию (`agent.__version__`) — бэкенд апдейтит `servers.agent_version` при изменении.
- **Backend (FastAPI)** — приём метрик, JWT-аутентификация юзеров, API-ключи для агентов, REST + WebSocket эндпоинты.
- **Postgres** — хранит юзеров (с настройками уведомлений: Telegram chat_id + флаг email_alerts_enabled), серверы, raw-метрики (24ч), агрегаты (`metric_aggregates`, `docker_aggregates`), алерт-правила и события.
- **Redis** — Pub/Sub для real-time дашборда, кэш дашборда (10s TTL), хранилище rate-лимитов (db=3), per-channel mute (`mute:<server_id>:<channel>`), pending-delete подтверждения, одноразовые коды привязки бота, Celery broker (db=1) и backend (db=2).
- **Celery + Beat** — 5-минутная/почасовая/посуточная агрегация, heartbeat-проверка (помечает сервер неактивным, если метрик нет >5 мин), auto-resolve алертов (system + docker), отправка уведомлений в Telegram и email.
- **Telegram bot** — отдельный long-polling процесс. Обрабатывает `/start <код>` для привязки чата к юзеру (одноразовые коды живут в Redis с TTL 10 мин) и команды админки: `/status`, `/servers`, `/rules`, `/toggle`, `/mute`, `/delete`.
- **Prometheus + Grafana** *(опционально)* — Prometheus скрапит `/metrics/prometheus` на бэкенде каждые 15с (счётчики запросов, латентность, статусы). Grafana с pre-provisioned Prometheus-датасорсом и готовым дашбордом «PulseWatch — Backend HTTP».
- **Frontend** — статика (vanilla JS + Chart.js через CDN) в `static/`, FastAPI отдаёт `/` → `index.html`. Login, список серверов, реал-тайм график (CPU/RAM/Disk через WebSocket) — без билда и npm.

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

# 2. Поднять стек (Postgres + Redis + backend + Celery worker + Celery beat + Telegram bot + Prometheus + Alertmanager + Grafana)
make up

# Альтернатива — `make demo` создаст юзера/сервер/правила и погонит фейковый агент
# (см. секцию ниже про быстрый онбординг)

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

> Контейнеры `worker` + `beat` (Celery) и `bot` (Telegram long-polling) поднимаются автоматически вместе с `app`. Локально без Docker запускай их вручную в отдельных терминалах: `uv run celery -A app.tasks.celery_app worker -l info`, `uv run celery -A app.tasks.celery_app beat -l info`, `uv run python -m app.telegram_bot`.

## Переменные окружения

| Имя | Описание |
|---|---|
| `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME` | Postgres-подключение |
| `REDIS_HOST`, `REDIS_PORT` | Redis-подключение |
| `SECRET_KEY` | Ключ для подписи JWT. Не дефолтный, не пустой |
| `ALGORITHM` | Алгоритм JWT (по умолчанию `HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | TTL access-токена (по умолчанию 30 мин) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | TTL refresh-токена (по умолчанию 7 дней) |
| `PASSWORD_RESET_TOKEN_TTL_SECONDS` | TTL одноразового токена сброса пароля (по умолчанию 3600 = 1 час) |
| `FRONTEND_BASE_URL` | Базовый URL фронта для генерации reset-password-ссылки в email (по умолчанию `http://localhost:8000`) |
| `LOG_RETENTION_DAYS` | Хранение persisted-логов в днях; Celery beat удаляет старше (по умолчанию 14) |
| `TELEGRAM_BOT_TOKEN` | Токен бота от `@BotFather`. Опционально — если пусто, уведомления отключены |
| `TELEGRAM_BOT_USERNAME` | Username бота (без `@`). Нужен только для deep-link в `/auth/me/telegram/code` |
| `ADMIN_TELEGRAM_CHAT_ID` | chat_id админа для Alertmanager-уведомлений (BackendDown / HighLatency / HighErrorRate). Пусто — webhook только логирует |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_ADDRESS`, `SMTP_USE_TLS` | SMTP для email-уведомлений. Пусто → канал выключен |
| `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD` | Логин/пароль админа Grafana. По умолчанию `admin`/`admin` (поменяй) |
| `AGENT_API_URL` | URL бэкенда для агента |
| `AGENT_API_KEY` | API-ключ от `/servers/register`, формат `<server_id>.<secret>` |
| `AGENT_SEND_INTERVAL_SECONDS` | Период отправки метрик (по умолчанию 10с) |

## API

Все защищённые эндпоинты требуют `Authorization: Bearer <JWT>`. Эндпоинты приёма метрик от агента — `X-API-Key: <server_id>.<secret>`.

**Версионирование.** Все REST-роуты доступны под двумя префиксами: `/v1/...` (рекомендуется для новых клиентов) и без префикса (legacy, помечен `deprecated=true` в OpenAPI). Например `POST /v1/auth/login` ≡ `POST /auth/login`. WebSocket-эндпоинты (`/ws/...`) не версионируются.

### Auth
- `POST /auth/register` — регистрация юзера. Лимит **3/min на IP**.
- `POST /auth/login` — логин (form-encoded). Возвращает пару `{access_token, refresh_token, token_type}`. Если у юзера включён TOTP — без поля `totp_code` отвечает 401 с `detail="TOTP_REQUIRED"`; повторный POST с `totp_code=123456` валидирует код через `pyotp.TOTP(secret).verify(code, valid_window=1)`. Лимит **5/min на IP**.
- `POST /auth/refresh` — обменивает refresh на новую пару с **ротацией**: старый refresh инвалидируется и помечается как «used» в Redis (TTL=TTL_токена). Если предъявляют уже использованный jti — это **reuse detection**: отзываем все сессии юзера (SCAN `refresh:<id>:*` + DEL), шлём владельцу предупреждение в Telegram (если привязан chat_id) и возвращаем 401. Тело JSON: `{"refresh_token": "..."}`. Лимит **5/min на IP**.
- `POST /auth/logout` — отзывает refresh-токен (идемпотентно, всегда 204). Тело JSON: `{"refresh_token": "..."}`.
- `POST /auth/forgot-password` — принимает `{"email":"..."}`, всегда возвращает 200 (не раскрываем существующие email). Если юзер найден, в Redis кладётся одноразовый токен `pwd_reset:<token>` (TTL = `PASSWORD_RESET_TOKEN_TTL_SECONDS`), на `users.email` шлётся письмо со ссылкой `<FRONTEND_BASE_URL>/reset-password?token=<token>`. Лимит **3/min на IP**.
- `POST /auth/reset-password` — обменивает токен на новый пароль (`{"token":"...", "new_password":"..."}`). Атомарно: `GET+DEL` через Redis pipeline. После успеха отзываем ВСЕ refresh-токены юзера (старые сессии должны заново логиниться). Лимит **5/min на IP**.
- `GET /auth/me` — текущий юзер (поля включают `totp_enabled: bool`, `subscription_tier: str`).
- `GET /auth/me/quota` — потребление и лимиты текущего тарифа: `{tier, servers_used, servers_max, rules_used, rules_max}`. `*_max = -1` означает безлимит.
- `POST /auth/me/totp/setup` — генерит свежий `pyotp.random_base32()` secret, ставит `totp_enabled=false`. Возвращает `{secret, otpauth_url}` (URL для QR: `otpauth://totp/PulseWatch:<email>?secret=...&issuer=PulseWatch`). Повторный вызов сбрасывает старый secret.
- `POST /auth/me/totp/enable` — подтверждает код от приложения (`{"code":"123456"}`), выставляет `totp_enabled=true`. С этого момента логин требует второй фактор.
- `POST /auth/me/totp/disable` — требует пароль (`{"password":"..."}`) чтобы украденный access-токен не мог снять 2FA. Очищает `totp_secret` и `totp_enabled`.
- `POST /auth/me/telegram/code` — генерит одноразовый код привязки + deep-link `https://t.me/<bot>?start=<code>` (TTL 10 мин). Юзер шлёт `/start <code>` боту → бот ставит chat_id.
- `PATCH /auth/me/telegram` — ручная привязка/отвязка chat_id (для скриптов). Тело: `{"chat_id": "12345"}` или `{"chat_id": null}`.
- `PATCH /auth/me/email-alerts` — включить/выключить email-уведомления. Тело: `{"enabled": true \| false}`.

### Серверы
- `POST /servers/register` — создать сервер, получить API-ключ.
- `GET /servers/me` — список своих серверов.
- `GET /servers/dashboard` — сводка с последними метриками (10s Redis-кэш).
- `POST /servers/{id}/rotate-key` — ротация API-ключа: генерит новый секрет, старый ключ моментально умирает. Полезно если ключ скомпрометирован — переустанови агента с новым ключом. Audit: запись `server_rotate_key`.
- `GET /servers/{id}/logs/export?start=&end=` — CSV-экспорт persisted-логов из таблицы `logs`. Default window 7 дней, max 30.

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
- `GET /alerts/events/export?start=&end=&server_id=&rule_id=&only_open=` — CSV-стрим событий. Default window 7 дней, max 90.
- При срабатывании: задача в Celery шлёт сообщение в Telegram (если у юзера привязан chat_id и токен бота настроен), плюс публикация в Redis Pub/Sub.
- Auto-resolve: раз в минуту Celery-beat проверяет открытые события — если последняя метрика больше не пробивает порог, в `resolved_at` ставится текущее время. Работает и для system, и для docker (по `(server_id, container_name)`).

### Audit log
- `GET /audit/me?limit=N` (default 50, max 500) — последние записи `audit_log` для текущего юзера, новые сверху. Поля: `action`, `resource_type`, `resource_id`, `ip_address`, `meta` (JSONB), `created_at`.

Записи пишет `app/services/audit.py:record_audit` (best-effort — если запись падает, основной запрос не падает). Покрытые действия:

| action | Где пишется |
|---|---|
| `register` | `POST /auth/register` |
| `login` / `login_failed` | `POST /auth/login` (последний с `meta.reason` = `wrong_password` / `invalid_totp`) |
| `password_reset` | `POST /auth/reset-password` |
| `rule_create` / `rule_update` / `rule_delete` | `POST/PATCH/DELETE /alerts/rules` |
| `server_rotate_key` | `POST /servers/{id}/rotate-key` |
| `totp_setup` / `totp_enable` / `totp_disable` | `/auth/me/totp/*` |

### WebSocket
- `WS /ws/metrics/{server_id}?token=<JWT>` — real-time поток метрик владельцу сервера.
- `WS /ws/logs/{server_id}?token=<JWT>` — поток journald-логов (real-time broadcast, без задержки).
- `WS /ws/agent/logs?api_key=...` — агент пушит логи в бэкенд. **Сохраняются в `logs` таблицу батчами** (до 50 строк или 1 секунды); broadcast идёт сразу. Retention: Celery beat задача `prune-old-logs` раз в сутки удаляет логи старше `LOG_RETENTION_DAYS` (default 14).

### Лимиты CSV-экспорта

| `granularity` | Источник | Макс. диапазон |
|---|---|---|
| `raw` | `metrics` / `docker_metrics` | 24 часа |
| `fivemin` | `metric_aggregates` (period=fivemin) | 7 дней |
| `hourly` | `metric_aggregates` (period=hourly) | 30 дней |
| `daily` | `metric_aggregates` (period=daily) | 365 дней |

При превышении — `400 Bad Request`.

## Уведомления

При срабатывании алерт-правила событие шлётся в **два канала параллельно**: Telegram (если у юзера привязан `telegram_chat_id` и токен бота настроен) и email (если SMTP сконфигурирован и у юзера `email_alerts_enabled=true`). Каналы можно глушить **независимо**: Redis-ключи `mute:<server_id>:telegram` и `mute:<server_id>:email` живут с TTL и ставятся через бот-команду `/mute`. По умолчанию `/mute <id> <minutes>` (без указания канала) глушит оба.

### Telegram

1. Создай бота через [`@BotFather`](https://t.me/BotFather) (`/newbot` → имя → username с суффиксом `bot`). Получишь токен формата `7234567890:AAH...`.
2. Добавь в `.env`:
   ```
   TELEGRAM_BOT_TOKEN=7234567890:AAH...
   TELEGRAM_BOT_USERNAME=мой_бот   # без @, для генерации deep-link
   ```
3. Перезапусти стек (`make down && make up`) — поднимется отдельный сервис `bot` с long-polling. Без токена бот в логах напишет «не задан» и завершится — это нормально.

### Способ 1 — привязка через `/start <код>` (рекомендуемый)

Юзер заходит в свой PulseWatch-аккаунт, генерит одноразовый код, отправляет его боту:

```bash
# 1. Получить код (TTL 10 мин)
curl -X POST http://localhost:8000/auth/me/telegram/code \
  -H "Authorization: Bearer <JWT>"
# → {"code": "a1b2c3d4", "deep_link": "https://t.me/мой_бот?start=a1b2c3d4", "expires_in_seconds": 600}

# 2. Открыть deep_link → Telegram → нажать «START» (бот автоматически пошлёт /start a1b2c3d4)
#    Бот ответит «✅ Аккаунт привязан».
```

### Способ 2 — ручная привязка по `chat_id`

Полезно для скриптов/админки. Юзер сам узнаёт свой chat_id (например, через [`@userinfobot`](https://t.me/userinfobot)) и шлёт PATCH:

```bash
curl -X PATCH http://localhost:8000/auth/me/telegram \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{"chat_id":"123456789"}'
```

Отвязка (любой способ): `PATCH /auth/me/telegram` с телом `{"chat_id": null}`.

После привязки создай алерт-правило с низким порогом и подожди следующую метрику от агента — бот напишет в чат.

### Команды бота

После того как чат привязан:

| Команда | Что делает |
|---|---|
| `/status` | Сводка: список серверов с последней метрикой (CPU/RAM/disk), счётчик открытых алертов, индикатор mute по каналам, paused/active/down |
| `/servers` | Подробный список серверов: имя, `last_seen_at`, состояние (active/paused/down) |
| `/mute <server_id> <minutes> [telegram\|email\|all]` | Глушит уведомления для сервера на N минут (1–1440). Канал опционален, default `all` (оба) |
| `/rules` | Список твоих алерт-правил с состоянием on/off, оператором и порогом |
| `/toggle <rule_id>` | Включает/выключает правило (флипает `is_active`) |
| `/createrule` | **Диалоговое** создание правила (system или docker). Шаги: сервер → тип (system/docker) → имя → метрика → (для docker) имя контейнера или `*` → оператор → порог → каналы → подтверждение. Состояние живёт 10 мин в Redis (`rule_draft:<chat_id>`). |
| `/cancel` | Отменить активный диалог `/createrule` |
| `/delete <server_id>` | **Двухступенчатое** удаление сервера со всеми его метриками/агрегатами/правилами/событиями. Бот просит подтверждение `/delete <id> confirm` в течение 60с |
| `/events [server_id]` | Последние 10 алерт-событий (или по конкретному серверу) с пометкой open/resolved |
| `/pause <server_id>` | Поставить сервер на паузу: `POST /metrics` молча игнорируются, heartbeat не помечает как inactive. Состояние видно в `/servers`, `/status` и в UI |
| `/resume <server_id>` | Снять паузу |

Mute проверяется в `send_telegram_alert` и `send_email_alert` перед отправкой (каждый смотрит свой канал) — пока активна заглушка, сообщения молча скипаются. Алерт-события всё равно создаются и видны в `GET /alerts/events`.

**Heartbeat-уведомления.** Если сервер замолчал >5 минут — Celery-beat отправляет владельцу `⚠️ <server> не отвечает` (telegram + email). Когда метрики возобновляются — `✅ <server> снова в строю`. Heartbeat пропускает `paused`-серверы (юзер сам их отключил), уважает per-channel mute (если юзер заглушил канал — heartbeat молчит по этому каналу) и `email_alerts_enabled`.

**Per-канальный opt-out на уровне правила.** В `AlertRule.notification_channels` — массив `["telegram"]` / `["email"]` / `["telegram","email"]` (default) / `[]`. Пустой массив = создаём AlertEvent + публикуем в Redis Pub/Sub, но не шлём никаких уведомлений. Управляется через REST (`POST /alerts/rules`, `PATCH /alerts/rules/{id}`) или через бот `/createrule` (на последнем шаге выбираешь `telegram` / `email` / `both` / `none`).

### Email

1. Заведи SMTP-аккаунт (например, в почтовом провайдере включи app password).
2. Заполни в `.env`:
   ```
   SMTP_HOST=smtp.example.com
   SMTP_PORT=587
   SMTP_USER=alerts@example.com
   SMTP_PASSWORD=...
   SMTP_FROM_ADDRESS=alerts@example.com
   SMTP_USE_TLS=true
   ```
3. Перезапусти Celery `worker` (`docker compose restart worker`).

Уведомления шлются на `users.email` (тот же, по которому юзер логинится). Опт-аут:

```bash
curl -X PATCH http://localhost:8000/auth/me/email-alerts \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{"enabled": false}'
```

Если `SMTP_HOST` не задан — канал молча выключен, никаких ошибок.

## Тарифы и квоты

Каждому юзеру при регистрации присваивается `subscription_tier="free"`. Тариф ограничивает максимальное количество серверов и алерт-правил. При превышении `POST /servers/register` или `POST /alerts/rules` возвращает **402 Payment Required**.

| Тариф | Серверы | Правила |
|---|---|---|
| `free` *(default)* | 3 | 10 |
| `pro` | 20 | 100 |
| `enterprise` | ∞ | ∞ |

Смена тарифа сейчас только через прямой `UPDATE users SET subscription_tier='pro' WHERE id=...` (платёжная интеграция вне scope). Текущее потребление и лимиты юзер видит через `GET /auth/me/quota` — можно показывать в UI «осталось N из M серверов».

Лимиты редактируются в `app/core/quotas.py:TIER_LIMITS` (тариф = строка, новые планы добавляются без миграции).

## Observability (Prometheus + Grafana)

Бэкенд отдаёт HTTP-метрики в Prometheus-формате на `/metrics/prometheus` (счётчики запросов, латентность, статус-коды — собираются через middleware `prometheus-fastapi-instrumentator`). В compose уже есть два готовых сервиса:

- **`prometheus`** на `http://localhost:9090` — скрапит `app:8000/metrics/prometheus` раз в 15с. Конфиг в `prometheus.yml`, alerting-правила в `prometheus_rules.yml`.
- **`alertmanager`** на `http://localhost:9093` — принимает алерты от Prometheus, агрегирует, шлёт на webhook `POST /alertmanager/webhook`. Бэкенд логирует payload и, если задан `ADMIN_TELEGRAM_CHAT_ID`, дублирует алерт в Telegram админу. Конфиг в `alertmanager.yml`.
- **`grafana`** на `http://localhost:3000` — с pre-provisioned Prometheus-датасорсом **и готовым дашбордом** «PulseWatch — Backend HTTP» (4 панели: rps, latency p50/p95/p99, 5xx error rate, статус-коды). Дефолтные креды `admin`/`admin` (поменяй через `GRAFANA_ADMIN_USER`/`GRAFANA_ADMIN_PASSWORD` в `.env`).

После `make up`:
1. Открой Grafana → авторизуйся.
2. **Dashboards** — увидишь готовый «PulseWatch — Backend HTTP».
3. Свои дашборды клади в `grafana/provisioning/dashboards/` (JSON), они подхватятся автоматически.

Первый запрос на `/metrics/prometheus` идёт через 15с после старта Prometheus, так что сразу после `up` метрик может ещё не быть — подожди минуту.

**Slack-канал для critical-алертов.** В `alertmanager.yml` есть второй receiver `slack-critical` с маршрутизацией по `severity = critical` (и `continue: true` чтобы дублировать в webhook). Чтобы включить:

1. Получи Slack Incoming Webhook URL (`https://hooks.slack.com/services/...`).
2. Замени значение `slack_api_url` в `alertmanager.yml`.
3. При желании поменяй `channel: '#alerts'` на нужный.
4. `docker compose restart alertmanager`.

Если оставить плейсхолдер `REPLACE_ME` — Slack-доставка просто будет молча фейлиться, webhook к app продолжит работать.

**Бизнес-метрики PulseWatch** (помимо HTTP-метрик от instrumentator):

| Метрика | Тип | Лейблы |
|---|---|---|
| `pulsewatch_metrics_ingested_total` | Counter | `kind=system\|docker` |
| `pulsewatch_logs_persisted_total` | Counter | — |
| `pulsewatch_alert_events_created_total` | Counter | — |
| `pulsewatch_notifications_sent_total` | Counter | `channel=telegram\|email`, `status=success\|failed\|skipped` |
| `pulsewatch_users_total` | Gauge | — |
| `pulsewatch_servers_total` | Gauge | `status=active\|inactive\|paused` |
| `pulsewatch_open_alerts_total` | Gauge | — |

Counters инкрементятся в момент события. Gauges раз в 30с обновляются фоновой таской из lifespan FastAPI (`app/core/observability_refresh.py`).

**Готовые Prometheus-алерты** (`prometheus_rules.yml`):

| Алерт | Условие | for | Severity |
|---|---|---|---|
| `BackendDown` | `up{job="pulsewatch"} == 0` | 1m | critical |
| `HighRequestLatency` | p95 latency > 500ms | 5m | warning |
| `HighErrorRate` | 5xx > 1% запросов в секунду | 5m | critical |

Срабатывания идут в Alertmanager → webhook → лог. Если хочешь шлёт куда-то ещё (Slack/Telegram/email), правь `alertmanager.yml`.

## Frontend dashboard

Браузерный дашборд лежит в `static/` — без билда и без npm. Chart.js и qrcode-generator (для TOTP QR) подключены через CDN (`cdn.jsdelivr.net`).

FastAPI монтирует `/static` и отдаёт `index.html` на корневой URL (`GET /`). Открой `http://localhost:8000/`, войди — увидишь верхнюю навигацию с шестью табами:

| Таб | Что |
|---|---|
| Серверы | Карточки твоих серверов с last_seen, agent_version, paused/active. Клик → панель с real-time графиком CPU/RAM/Disk (60 точек, WebSocket) |
| Правила | Таблица `AlertRule` с кнопками toggle (PATCH is_active) и delete (DELETE) + кнопка «Создать правило» → инлайн-форма (сервер/имя/тип/метрика/оператор/порог/cooldown/каналы) → POST /alerts/rules |
| События | Таблица `AlertEvent` с фильтром по серверу и кнопкой refresh, цвет статуса open/resolved |
| Агрегаты | Выбор сервера + период (5min/час/день) → линейный график средних CPU/Memory/Disk |
| Логи | Выбор сервера + кнопка Подключить → WebSocket `/ws/logs/{id}` стримит journald-строки в `<pre>` |
| История | Таблица последних 200 записей `audit_log` с клиентской фильтрацией по action. Авто-обновление после мутаций (создание правила, TOTP, rotate-key) |

В шапке: селекторы **языка** (RU/EN) и **темы** (тёмная/светлая) с сохранением выбора в `localStorage`. Клик по email юзера открывает модалку профиля — управление TOTP 2FA (включить/выключить + QR-код).

Что реализовано в `static/app.js`:

- **Токены в `localStorage`** под ключом `pulsewatch.tokens` (access + refresh).
- **`apiFetch`** — обёртка над `fetch`, навешивает `Authorization: Bearer <access>`, на 401 атомарно ходит на `/auth/refresh`, обновляет пару, повторяет запрос. Если refresh тоже мёртв — выкидывает на login-форму. После успешной мутации на audited-эндпоинте (правила, TOTP, rotate-key, reset) сбрасывает кеш вкладки «История».
- **WebSocket** на `/ws/metrics/{id}?token=<access>` и `/ws/logs/{id}?token=<access>` — новые сообщения приходят без перезагрузки. На close с кодом 1008 (auth refused) пробуем refresh и переподключаемся один раз.
- **i18n** — словарь `I18N = {ru, en}` в `app.js`; `data-i18n` атрибуты статичных элементов + `t(key)` для динамических строк (карточки серверов, таблицы правил/событий, ошибки). Выбор языка persist в `pulsewatch.lang`.
- **Темы** — CSS-переменные в `:root` (dark по умолчанию) и `[data-theme="light"]`. Inline-скрипт в `<head>` применяет тему ДО отрисовки (избегает «вспышки»). Чарты Chart.js перекрашиваются на смене темы через `getComputedStyle`.
- **TOTP UI** — модалка профиля + QR через qrcode-generator; на login-форме поле «Код 2FA» появляется при ответе сервера `detail=TOTP_REQUIRED` и сабмит повторяется с кодом.
- **Reset-password** — отдельная страница `/reset-password?token=...` (`static/reset-password.html` + `reset-password.js`). Ссылка «Забыли пароль?» на login-форме делает prompt email и POST `/auth/forgot-password`.
- **Mobile-friendly** — `@media (max-width: 700px)` и `380px` адаптируют header, табы, filter-bar (колонкой), таблицы (горизонтальный скролл через `.table-wrap`), модалку (full-width), формы.

Тестов на фронтенд два уровня: unit-тесты бэкенда (pytest, 225+) и smoke-тесты UI через Playwright (см. ниже).

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

# Unit-тесты (требуют запущенного Postgres+Redis из docker-compose)
make test
# или
uv run pytest -v

# E2E-тесты Playwright (один раз поставить браузер)
uv run playwright install chromium
make up        # стек должен быть запущен
make test-e2e  # pytest e2e/ --base-url http://localhost:8000

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

# Сгенерировать Python SDK из живого /openapi.json (бэкенд на :8000)
make sdk
# затем `python examples/use_sdk.py` чтобы попробовать
```

### CI

`.github/workflows/ci.yml` запускается на push в master и PRs. Два job'а:
- **lint** — `ruff check`, `ruff format --check`, `mypy`
- **test** — `alembic upgrade head` + `pytest`, с Postgres 16 и Redis 7 в качестве service-контейнеров GitHub Actions

`SECRET_KEY` в CI генерится из `github.sha` (не для прода). Dependabot настроен в `.github/dependabot.yml` — ежемесячные апдейты github-actions и pip.

### Структура

```
app/
  api/        # FastAPI роутеры
  core/       # security (JWT access+refresh), rate_limit, connection manager
  models/     # SQLAlchemy модели
  schemas/    # Pydantic-схемы (вход/выход)
  services/   # бизнес-логика (threshold, aggregation, alert_resolver, telegram, email_alert)
  tasks/      # Celery задачи (агрегация, heartbeat, notification, resolve)
  utils/      # стриминг CSV
  telegram_bot.py  # long-polling процесс для бота
agent/
  collectors/ # system (psutil), docker (SDK), logs (journald)
  agent.py, sender.py, logs_streamer.py, __init__.py (__version__)
static/       # frontend: index.html, app.js, style.css, reset-password.{html,js}
sdk/          # README для генерации Python SDK через `make sdk` (артефакт в .gitignore)
examples/     # use_sdk.py — демо использования сгенерированного клиента
.github/      # CI workflow (ci.yml) + dependabot.yml
grafana/      # provisioning datasources/dashboards
alembic/      # миграции
tests/
docs/         # планы этапов
```

## Backup и restore Postgres

```bash
# Создать дамп (gzip, в backups/pulsewatch_YYYYMMDD_HHMMSS.sql.gz):
make backup

# Восстановить из дампа:
make restore FILE=backups/pulsewatch_20260511_180000.sql.gz
```

Каталог `backups/` в `.gitignore`. Для регулярных бэкапов добавь в crontab:

```cron
# Ежедневный бэкап в 03:00; pruning старше 30 дней
0 3 * * * cd /path/to/PulseWatch && make backup && find backups -name '*.sql.gz' -mtime +30 -delete
```

`pg_dump` запускается внутри контейнера db; пользователь и имя БД берутся из `$DB_USER`/`$DB_NAME` (или `.env`). Восстановление работает и для `.sql`, и для `.sql.gz`.

## Quick demo

```bash
make demo
```

Поднимет `db redis app worker beat`, дождётся пока приложение взлетит, запустит `scripts/demo.py`, который:

1. Регистрирует юзера `demo@pulsewatch.local` / `demopass123` (или reuse если есть).
2. Создаёт свежий сервер `demo-srv-<rand>` и **печатает api_key один раз**.
3. Заводит два правила: `cpu_percent > 60` и `memory_percent > 60` с cooldown 60с.
4. Гонит фейковый агент: каждые 5с шлёт случайные метрики в диапазоне 20–90%, половина итераций пробивает порог.

UI на `http://localhost:8000/` — увидишь как метрики обновляются в real-time, события появляются в `/alerts/events`. Старые demo-серверы чистятся через бот `/delete`.

## Известные ограничения / TODO

- TOTP secret хранится в Postgres «голым» (`users.totp_secret VARCHAR(64)`). Для продакшна — шифровать KMS-ключом / Vault.
- Audit log без UI-страницы по другим юзерам — только `/audit/me` (свои действия). Админский endpoint типа `/audit/all` не реализован.
- Email шаблоны простые — без branding'а, без preheader, без unsubscribe-ссылки.
- Backup автоматизирован только через cron-снаружи; PITR (point-in-time-recovery) через WAL-архивирование не настроен.

## Лицензия

Учебный проект, лицензии нет.
