import os

from fastapi import FastAPI

from app.database import healthcheck
from app.routes.ruc import router as ruc_router
from app.services.cache import ping as redis_ping

app = FastAPI(
    title="SUNAT RUC API",
    version="1.0.0",
    description="API de alto volumen para consultar el padrón reducido de RUC de SUNAT.",
)

app.include_router(ruc_router)


@app.get("/health")
def health():
    db_ok = "ok" if healthcheck() else "fail"
    redis_ok = "ok" if redis_ping() else None
    status = "ok" if db_ok == "ok" else "degraded"
    return {"status": status, "database": db_ok, "redis": redis_ok}

