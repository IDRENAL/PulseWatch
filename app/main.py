from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.alerts import router as alerts_router
from app.api.auth import router as auth_router
from app.api.docker_metrics import router as docker_metrics_router
from app.api.metrics import router as metrics_router
from app.api.servers import router as servers_router
from app.api.websocket import router as websocket_router
from app.api.ws_metrics import router as ws_metrics_router
from app.config import settings
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
    try:
        yield
    finally:
        await client.aclose()
        set_redis_client(None)


app = FastAPI(title="PulseWatch", lifespan=lifespan)
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(servers_router, prefix="/servers", tags=["servers"])
app.include_router(alerts_router, prefix="/alerts", tags=["alerts"])
app.include_router(metrics_router, prefix="/metrics", tags=["metrics"])
app.include_router(docker_metrics_router, prefix="/docker-metrics", tags=["docker-metrics"])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]  # slowapi stub typing
app.include_router(websocket_router, tags=["websocket"])
app.include_router(ws_metrics_router, tags=["ws-metrics"])


@app.get("/health")
async def health():
    try:
        await get_redis().ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    return {"status": "ok", "redis": redis_ok}
