import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from redis.asyncio import Redis
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.alertmanager import router as alertmanager_router
from app.api.alerts import router as alerts_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.docker_metrics import router as docker_metrics_router
from app.api.metrics import router as metrics_router
from app.api.servers import router as servers_router
from app.api.websocket import router as websocket_router
from app.api.ws_metrics import router as ws_metrics_router
from app.config import settings
from app.core.observability_refresh import refresh_gauges_loop
from app.core.rate_limit import limiter
from app.redis_client import get_redis, set_redis_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=0,
        decode_responses=True,
    )
    await client.ping()  # type: ignore[misc]  # redis-py stub: Awaitable[bool]|bool, async-вариант возвращает Awaitable
    app.state.redis = client
    set_redis_client(client)
    # Periodic gauge refresh: считает users/servers/open-alerts каждые 30с и
    # пишет в Prometheus. Если БД временно недоступна — тики пропускаются,
    # цикл не падает.
    gauge_task = asyncio.create_task(refresh_gauges_loop())
    try:
        yield
    finally:
        gauge_task.cancel()
        with suppress(asyncio.CancelledError):
            await gauge_task
        await client.aclose()
        set_redis_client(None)


app = FastAPI(title="PulseWatch", lifespan=lifespan)

# REST-роутеры монтируются ДВАЖДЫ: под /v1/... и под legacy-префиксом.
# Старые клиенты (CI, агент, существующий фронт) работают без миграции,
# новые клиенты могут переходить на /v1/. В следующей мажорной версии
# legacy будет помечен deprecated и удалён.
REST_ROUTERS = [
    (auth_router, "/auth", "auth"),
    (servers_router, "/servers", "servers"),
    (alerts_router, "/alerts", "alerts"),
    (metrics_router, "/metrics", "metrics"),
    (docker_metrics_router, "/docker-metrics", "docker-metrics"),
    (alertmanager_router, "/alertmanager", "alertmanager"),
    (audit_router, "/audit", "audit"),
]

for router, prefix, tag in REST_ROUTERS:
    app.include_router(router, prefix=f"/v1{prefix}", tags=[tag])
    # Legacy: те же роуты без /v1, но помечены deprecated — Swagger покажет
    # перечёркнутый бейдж, клиенты получат предупреждение в auto-генерируемых SDK
    app.include_router(router, prefix=prefix, tags=[f"{tag} (legacy)"], deprecated=True)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]  # slowapi stub typing
# WebSocket-роутеры не версионируем — пути с фиксированным /ws/ префиксом
app.include_router(websocket_router, tags=["websocket"])
app.include_router(ws_metrics_router, tags=["ws-metrics"])

# Prometheus-инструментация: middleware считает запросы/латентность,
# дамп отдаётся на /metrics/prometheus (нельзя /metrics — занят ingest-роутером)
Instrumentator().instrument(app).expose(
    app, endpoint="/metrics/prometheus", include_in_schema=False
)


@app.get("/health")
async def health():
    try:
        await get_redis().ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {"status": "ok", "redis": redis_ok}


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def root():
    return FileResponse("static/index.html")


@app.get("/reset-password", include_in_schema=False)
async def reset_password_page():
    """Страница для сценария «забыл пароль» — JS читает ?token=... из URL."""
    return FileResponse("static/reset-password.html")
