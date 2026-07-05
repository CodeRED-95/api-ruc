import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request

from app.database import get_conn

HASH_SECRET = None


def init_settings(hash_secret: str) -> None:
    global HASH_SECRET
    HASH_SECRET = hash_secret.encode("utf-8")


def require_hash_secret() -> bytes:
    if HASH_SECRET is None:
        raise RuntimeError("HASH_SECRET no está configurado")
    return HASH_SECRET


def normalize_token(token: str) -> str:
    return token.strip()


def hash_api_key(api_key: str) -> str:
    secret = require_hash_secret()
    digest = hmac.new(secret, api_key.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


def generate_api_key(token_length: int) -> str:
    raw = secrets.token_urlsafe(token_length)
    if len(raw) < token_length:
        raw = raw + secrets.token_urlsafe(token_length)
    return raw[:token_length]


def get_client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def _api_key_row_by_hash(cur, key_hash: str):
    cur.execute(
        """
        SELECT id, nombre, api_key_hash, activo, descripcion, fecha_creacion, ultimo_uso,
               limite_diario, limite_por_minuto, consultas_realizadas, ultima_ip
        FROM api_keys
        WHERE api_key_hash = %s
        """,
        (key_hash,),
    )
    return cur.fetchone()


def validate_api_key(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API Key requerida")

    key_hash = hash_api_key(normalize_token(x_api_key))
    now = datetime.now(timezone.utc)
    minute_start = now.replace(second=0, microsecond=0)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    with get_conn() as conn:
        with conn.cursor() as cur:
            row = _api_key_row_by_hash(cur, key_hash)
            if not row or not row[3]:
                raise HTTPException(status_code=401, detail="API Key inválida o desactivada")

            api_key_id = row[0]
            limite_diario = row[7]
            limite_minuto = row[8]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM api_logs
                WHERE api_key_id = %s AND fecha >= %s
                """,
                (api_key_id, day_start),
            )
            daily_count = cur.fetchone()[0]

            cur.execute(
                """
                SELECT COUNT(*)
                FROM api_logs
                WHERE api_key_id = %s AND fecha >= %s
                """,
                (api_key_id, minute_start),
            )
            minute_count = cur.fetchone()[0]

            if limite_diario is not None and daily_count >= limite_diario:
                raise HTTPException(status_code=429, detail="Límite diario excedido")
            if limite_minuto is not None and minute_count >= limite_minuto:
                raise HTTPException(status_code=429, detail="Límite por minuto excedido")

            cur.execute(
                """
                UPDATE api_keys
                SET ultimo_uso = %s,
                    ultima_ip = %s,
                    consultas_realizadas = consultas_realizadas + 1
                WHERE id = %s
                """,
                (now, ip, api_key_id),
            )

    request.state.api_key_id = api_key_id
    request.state.api_key_name = row[1]
    request.state.api_key_hash = key_hash
    request.state.client_ip = ip
    request.state.user_agent = user_agent
    return row


def validate_admin_key(x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key")):
    import os

    admin_key = os.getenv("API_ADMIN_KEY", "")
    if not x_admin_key or x_admin_key != admin_key:
        raise HTTPException(status_code=401, detail="Admin key inválida")
    return True
