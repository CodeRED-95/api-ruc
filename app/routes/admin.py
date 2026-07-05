import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import get_conn
from app.services.auth import generate_api_key, hash_api_key, validate_admin_key

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(validate_admin_key)])

TOKEN_LENGTH = int(os.getenv("TOKEN_LENGTH", "64"))
DEFAULT_DAILY_LIMIT = int(os.getenv("DEFAULT_DAILY_LIMIT", "1000"))
DEFAULT_MINUTE_LIMIT = int(os.getenv("DEFAULT_MINUTE_LIMIT", "60"))


def _row_to_api_key(row):
    return {
        "id": row[0],
        "nombre": row[1],
        "activo": row[3],
        "descripcion": row[4],
        "fecha_creacion": row[5],
        "ultimo_uso": row[6],
        "limite_diario": row[7],
        "limite_por_minuto": row[8],
        "consultas_realizadas": row[9],
        "ultima_ip": row[10],
    }


@router.post("/api-keys")
def create_api_key(payload: dict):
    nombre = payload.get("nombre")
    if not nombre:
        raise HTTPException(status_code=422, detail="nombre es obligatorio")
    raw_key = generate_api_key(TOKEN_LENGTH)
    key_hash = hash_api_key(raw_key)
    descripcion = payload.get("descripcion")
    limite_diario = payload.get("limite_diario", DEFAULT_DAILY_LIMIT)
    limite_minuto = payload.get("limite_por_minuto", DEFAULT_MINUTE_LIMIT)
    activo = payload.get("activo", True)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO api_keys (
                    nombre, api_key_hash, activo, descripcion, fecha_creacion,
                    limite_diario, limite_por_minuto, consultas_realizadas
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
                RETURNING id
                """,
                (nombre, key_hash, activo, descripcion, datetime.now(timezone.utc), limite_diario, limite_minuto),
            )
            api_key_id = cur.fetchone()[0]
    return {"id": api_key_id, "api_key": raw_key}


@router.get("/api-keys")
def list_api_keys():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, nombre, api_key_hash, activo, descripcion, fecha_creacion,
                       ultimo_uso, limite_diario, limite_por_minuto, consultas_realizadas, ultima_ip
                FROM api_keys
                ORDER BY id DESC
                """
            )
            rows = cur.fetchall()
    return [_row_to_api_key(row) for row in rows]


@router.get("/api-keys/search")
def search_api_keys(nombre: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, nombre, api_key_hash, activo, descripcion, fecha_creacion,
                       ultimo_uso, limite_diario, limite_por_minuto, consultas_realizadas, ultima_ip
                FROM api_keys
                WHERE nombre ILIKE %s
                ORDER BY id DESC
                """,
                (f"%{nombre}%",),
            )
            rows = cur.fetchall()
    return [_row_to_api_key(row) for row in rows]


def _set_active(api_key_id: int, activo: bool):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE api_keys SET activo = %s WHERE id = %s", (activo, api_key_id))
    return {"id": api_key_id, "activo": activo}


@router.patch("/api-keys/{api_key_id}/activate")
def activate_api_key(api_key_id: int):
    return _set_active(api_key_id, True)


@router.patch("/api-keys/{api_key_id}/deactivate")
def deactivate_api_key(api_key_id: int):
    return _set_active(api_key_id, False)


@router.delete("/api-keys/{api_key_id}")
def delete_api_key(api_key_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM api_keys WHERE id = %s", (api_key_id,))
    return {"deleted": True, "id": api_key_id}


@router.post("/api-keys/{api_key_id}/regenerate")
def regenerate_api_key(api_key_id: int):
    raw_key = generate_api_key(TOKEN_LENGTH)
    key_hash = hash_api_key(raw_key)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE api_keys
                SET api_key_hash = %s
                WHERE id = %s
                """,
                (key_hash, api_key_id),
            )
    return {"id": api_key_id, "api_key": raw_key}


@router.get("/api-keys/{api_key_id}/stats")
def api_key_stats(api_key_id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, nombre, api_key_hash, activo, descripcion, fecha_creacion,
                       ultimo_uso, limite_diario, limite_por_minuto, consultas_realizadas, ultima_ip
                FROM api_keys
                WHERE id = %s
                """,
                (api_key_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="API key no encontrada")
            cur.execute("SELECT COUNT(*) FROM api_logs WHERE api_key_id = %s", (api_key_id,))
            total_logs = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM api_logs WHERE api_key_id = %s AND codigo_http = 200", (api_key_id,))
            total_ok = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM api_logs WHERE api_key_id = %s AND codigo_http >= 400", (api_key_id,))
            total_error = cur.fetchone()[0]
    return {"api_key": _row_to_api_key(row), "logs": {"total": total_logs, "ok": total_ok, "error": total_error}}


@router.get("/api-keys/{api_key_id}/logs")
def api_key_logs(api_key_id: int, limit: int = 100):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, api_key_id, ruc_consultado, endpoint, metodo, ip, user_agent,
                       codigo_http, tiempo_respuesta_ms, origen, fecha
                FROM api_logs
                WHERE api_key_id = %s
                ORDER BY fecha DESC
                LIMIT %s
                """,
                (api_key_id, min(limit, 500)),
            )
            rows = cur.fetchall()
    return [
        {
            "id": row[0],
            "api_key_id": row[1],
            "ruc_consultado": row[2],
            "endpoint": row[3],
            "metodo": row[4],
            "ip": row[5],
            "user_agent": row[6],
            "codigo_http": row[7],
            "tiempo_respuesta_ms": row[8],
            "origen": row[9],
            "fecha": row[10],
        }
        for row in rows
    ]

