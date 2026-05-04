from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

import app.redis_client as redis_module
from app.api.auth import router as auth_router
from app.api.docker_metrics import router as docker_metrics_router
from app.api.metrics import router as metrics_router
from app.api.servers import router as servers_router
from app.api.websocket import router as websocket_router
from app.api.ws_metrics import router as ws_metrics_router
from app.config import settings
from app.redis_client import get_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=0,
        decode_responses=True,
    )
    await client.ping()
    app.state.redis = client
    redis_module.redis_client = client
    try:
        yield
    finally:
        await client.aclose()
        redis_module.redis_client = None


app = FastAPI(title="PulseWatch", lifespan=lifespan)
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(servers_router, prefix="/servers", tags=["servers"])
app.include_router(metrics_router, prefix="/metrics", tags=["metrics"])
app.include_router(
    docker_metrics_router, prefix="/docker-metrics", tags=["docker-metrics"]
)
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
