from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import get_conn
from app.services.auth import generate_api_key, hash_api_key, make_token_preview, validate_admin_key

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(validate_admin_key)])

TOKEN_LENGTH = int(os.getenv("TOKEN_LENGTH", "64"))
DEFAULT_DAILY_LIMIT = int(os.getenv("DEFAULT_DAILY_LIMIT", "1000"))
DEFAULT_MINUTE_LIMIT = int(os.getenv("DEFAULT_MINUTE_LIMIT", "60"))


def _row_to_token(row: tuple[Any, ...], include_hash: bool = False) -> dict:
    base = {
        "id": row[0],
        "nombre": row[1],
        "token_preview": row[3],
        "is_active": row[4],
        "activo": row[4],
        "descripcion": row[5],
        "created_at": row[6],
        "fecha_creacion": row[6],
        "last_used_at": row[7],
        "ultimo_uso": row[7],
        "daily_limit": row[8],
        "limite_diario": row[8],
        "minute_limit": row[9],
        "limite_por_minuto": row[9],
        "total_requests": row[10],
        "consultas_realizadas": row[10],
        "last_ip": row[11],
        "disabled_at": row[12],
        "deleted_at": row[13],
    }
    if include_hash:
        base["token_hash"] = row[2]
    return base


def _token_stats(conn, token_id: int) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE fecha >= date_trunc('day', now())) AS requests_today,
                COUNT(*) FILTER (WHERE fecha >= date_trunc('minute', now())) AS requests_this_minute
            FROM api_logs
            WHERE api_key_id = %s
            """,
            (token_id,),
        )
        row = cur.fetchone()
    return {"requests_today": row[0], "requests_this_minute": row[1]}


def _get_token_row(conn, token_id: int) -> tuple[Any, ...] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, nombre, api_key_hash, token_preview, activo, descripcion, fecha_creacion,
                   ultimo_uso, limite_diario, limite_por_minuto, total_requests, ultima_ip,
                   disabled_at, deleted_at
            FROM api_keys
            WHERE id = %s
            """,
            (token_id,),
        )
        return cur.fetchone()


@router.post("/tokens")
@router.post("/api-keys")
def create_token(payload: dict):
    nombre = (payload.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=422, detail="nombre es obligatorio")

    raw_token = generate_api_key(TOKEN_LENGTH)
    token_hash = hash_api_key(raw_token)
    token_preview = make_token_preview(raw_token)
    descripcion = payload.get("descripcion")
    daily_limit = payload.get("daily_limit", payload.get("limite_diario", DEFAULT_DAILY_LIMIT))
    minute_limit = payload.get("minute_limit", payload.get("limite_por_minuto", DEFAULT_MINUTE_LIMIT))

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO api_keys (
                    nombre, api_key_hash, token_preview, activo, descripcion, fecha_creacion,
                    limite_diario, limite_por_minuto, total_requests, consultas_realizadas
                ) VALUES (%s, %s, %s, TRUE, %s, %s, %s, %s, 0, 0)
                RETURNING id
                """,
                (
                    nombre,
                    token_hash,
                    token_preview,
                    descripcion,
                    datetime.now(timezone.utc),
                    daily_limit,
                    minute_limit,
                ),
            )
            token_id = cur.fetchone()[0]

    return {
        "id": token_id,
        "api_key": raw_token,
        "token_preview": token_preview,
        "daily_limit": daily_limit,
        "minute_limit": minute_limit,
    }


@router.get("/tokens")
@router.get("/api-keys")
def list_tokens():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, nombre, api_key_hash, token_preview, activo, descripcion, fecha_creacion,
                       ultimo_uso, limite_diario, limite_por_minuto, total_requests, ultima_ip,
                       disabled_at, deleted_at
                FROM api_keys
                WHERE deleted_at IS NULL
                ORDER BY id DESC
                """
            )
            rows = cur.fetchall()
    return [_row_to_token(row) for row in rows]


@router.get("/tokens/{token_id}")
@router.get("/api-keys/{api_key_id}")
def get_token(token_id: int = None, api_key_id: int = None):
    token_id = token_id if token_id is not None else api_key_id
    with get_conn() as conn:
        row = _get_token_row(conn, token_id)
        if not row or row[13] is not None:
            raise HTTPException(status_code=404, detail="Token no encontrado")
        payload = _row_to_token(row)
        payload.update(_token_stats(conn, token_id))
    return payload


def _set_active(token_id: int, active: bool):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE api_keys
                SET activo = %s,
                    disabled_at = CASE WHEN %s THEN NULL ELSE COALESCE(disabled_at, %s) END
                WHERE id = %s AND deleted_at IS NULL
                """,
                (active, active, datetime.now(timezone.utc), token_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Token no encontrado")
    return {"id": token_id, "is_active": active}


@router.patch("/tokens/{token_id}/disable")
@router.patch("/api-keys/{api_key_id}/deactivate")
def disable_token(token_id: int = None, api_key_id: int = None):
    return _set_active(token_id if token_id is not None else api_key_id, False)


@router.patch("/tokens/{token_id}/enable")
@router.patch("/api-keys/{api_key_id}/activate")
def enable_token(token_id: int = None, api_key_id: int = None):
    return _set_active(token_id if token_id is not None else api_key_id, True)


@router.delete("/tokens/{token_id}")
@router.delete("/api-keys/{api_key_id}")
def delete_token(token_id: int = None, api_key_id: int = None):
    token_id = token_id if token_id is not None else api_key_id
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM api_keys WHERE id = %s", (token_id,))
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail="Token no encontrado")
            cur.execute("DELETE FROM api_keys WHERE id = %s", (token_id,))
    return {"deleted": True, "id": token_id}


@router.post("/tokens/{token_id}/regenerate")
@router.post("/api-keys/{api_key_id}/regenerate")
def regenerate_token(token_id: int = None, api_key_id: int = None):
    token_id = token_id if token_id is not None else api_key_id
    raw_token = generate_api_key(TOKEN_LENGTH)
    token_hash = hash_api_key(raw_token)
    token_preview = make_token_preview(raw_token)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE api_keys
                SET api_key_hash = %s,
                    token_preview = %s,
                    deleted_at = NULL,
                    activo = TRUE,
                    disabled_at = NULL
                WHERE id = %s
                """,
                (token_hash, token_preview, token_id),
            )
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail="Token no encontrado")
    return {"id": token_id, "api_key": raw_token, "token_preview": token_preview}


@router.get("/tokens/{token_id}/stats")
@router.get("/api-keys/{api_key_id}/stats")
def token_stats(token_id: int = None, api_key_id: int = None):
    token_id = token_id if token_id is not None else api_key_id
    with get_conn() as conn:
        row = _get_token_row(conn, token_id)
        if not row or row[13] is not None:
            raise HTTPException(status_code=404, detail="Token no encontrado")
        token = _row_to_token(row)
        token.update(_token_stats(conn, token_id))
    return {"token": token}


@router.get("/tokens/{token_id}/logs")
@router.get("/api-keys/{api_key_id}/logs")
def token_logs(token_id: int = None, api_key_id: int = None, limit: int = 100):
    token_id = token_id if token_id is not None else api_key_id
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
                (token_id, min(limit, 500)),
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
