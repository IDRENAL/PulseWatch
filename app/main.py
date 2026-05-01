from fastapi import FastAPI
from app.api.auth import router as auth_router
from app.api.servers import router as servers_router


app = FastAPI(title="PulseWatch")
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(servers_router, prefix="/servers", tags=["servers"])

@app.get("/health")
async def health():
    return {"status": "ok"}


