import os
import time
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import healthcheck
from app.routes.admin import router as admin_router
from app.routes.ruc import router as ruc_router
from app.services.auth import init_settings
from app.services.cache import ping as redis_ping
from app.services.logging import register_log
from app.web import router as web_router

init_settings(os.getenv("HASH_SECRET", "change-me"))

app = FastAPI(
    title="SUNAT RUC API",
    version="1.0.0",
    description="API de alto volumen para consultar el padrón reducido de RUC de SUNAT.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://docs.codered.host",
        "https://codered.host",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ruc_router)
app.include_router(admin_router)
app.include_router(web_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.middleware("http")
async def log_requests(request: Request, call_next: Callable):
    if request.method == "OPTIONS":
        return await call_next(request)

    start = time.perf_counter()
    response = None
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        api_key_id = getattr(request.state, "api_key_id", None)
        ruc_consultado = request.path_params.get("ruc") if hasattr(request, "path_params") else None
        register_log(
            api_key_id=api_key_id,
            ruc_consultado=ruc_consultado,
            endpoint=str(request.url.path),
            metodo=request.method,
            ip=getattr(request.state, "client_ip", request.client.host if request.client else None),
            user_agent=getattr(request.state, "user_agent", request.headers.get("user-agent")),
            codigo_http=status_code,
            tiempo_respuesta_ms=elapsed_ms,
            origen=request.headers.get("origin"),
        )


@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    return Response(status_code=204)


@app.get("/health")
def health():
    db_ok = "ok" if healthcheck() else "fail"
    redis_ok = "ok" if redis_ping() else None
    status = "ok" if db_ok == "ok" else "degraded"
    return {"status": status, "database": db_ok, "redis": redis_ok}


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description
        + "\n\nTodos los endpoints públicos requieren el header `X-API-Key`. Los endpoints administrativos requieren `X-Admin-Key`.",
        routes=app.routes,
    )
    openapi_schema.setdefault("components", {}).setdefault("securitySchemes", {})
    openapi_schema["components"]["securitySchemes"]["ApiKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
    }
    openapi_schema["components"]["securitySchemes"]["AdminKeyAuth"] = {
        "type": "apiKey",
        "in": "header",
        "name": "X-Admin-Key",
    }
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
