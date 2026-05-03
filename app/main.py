from fastapi import FastAPI
from app.api.auth import router as auth_router
from app.api.servers import router as servers_router
from app.api.metrics import router as metrics_router
from app.api.docker_metrics import router as docker_metrics_router


app = FastAPI(title="PulseWatch")
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(servers_router, prefix="/servers", tags=["servers"])
app.include_router(metrics_router, prefix="/metrics", tags=["metrics"])
app.include_router(
    docker_metrics_router, prefix="/docker-metrics", tags=["docker-metrics"]
)

@app.get("/health")
async def health():
    return {"status": "ok"}


