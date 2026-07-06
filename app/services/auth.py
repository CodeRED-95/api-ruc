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


def make_token_preview(token: str, prefix: int = 8, suffix: int = 8) -> str:
    if len(token) <= prefix + suffix:
        return token
    return f"{token[:prefix]}...{token[-suffix:]}"


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
        SELECT id, nombre, api_key_hash, token_preview, activo, descripcion, fecha_creacion,
               ultimo_uso, limite_diario, limite_por_minuto, total_requests, consultas_realizadas,
               ultima_ip, disabled_at, deleted_at
        FROM api_keys
        WHERE api_key_hash = %s
          AND deleted_at IS NULL
        """,
        (key_hash,),
    )
    return cur.fetchone()


def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.strip().split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip() or None
    return None


def _extract_token_from_request(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> Optional[str]:
    candidates = [
        x_api_key,
        _extract_bearer_token(authorization),
        request.query_params.get("apikey"),
        request.query_params.get("token"),
    ]
    for candidate in candidates:
        if candidate:
            candidate = candidate.strip()
            if candidate:
                return candidate
    return None


def _get_request_counts(cur, api_key_id: int, now: datetime):
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    minute_start = now.replace(second=0, microsecond=0)
    cur.execute(
        """
        SELECT COUNT(*)
        FROM api_logs
        WHERE api_key_id = %s AND fecha >= %s
        """,
        (api_key_id, day_start),
    )
    requests_today = cur.fetchone()[0]
    cur.execute(
        """
        SELECT COUNT(*)
        FROM api_logs
        WHERE api_key_id = %s AND fecha >= %s
        """,
        (api_key_id, minute_start),
    )
    requests_this_minute = cur.fetchone()[0]
    return requests_today, requests_this_minute


def validate_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    token = _extract_token_from_request(request, x_api_key=x_api_key, authorization=authorization)
    if not token:
        raise HTTPException(status_code=401, detail="API Key requerida")

    key_hash = hash_api_key(normalize_token(token))
    now = datetime.now(timezone.utc)
    ip = get_client_ip(request)
    user_agent = request.headers.get("user-agent")

    with get_conn() as conn:
        with conn.cursor() as cur:
            row = _api_key_row_by_hash(cur, key_hash)
            if not row or not row[4] or row[13] is not None or row[14] is not None:
                raise HTTPException(status_code=401, detail="API Key inválida")

            api_key_id = row[0]
            limite_diario = row[8]
            limite_minuto = row[9]
            requests_today, requests_this_minute = _get_request_counts(cur, api_key_id, now)

            if limite_diario is not None and requests_today >= limite_diario:
                raise HTTPException(status_code=429, detail="Límite diario excedido")
            if limite_minuto is not None and requests_this_minute >= limite_minuto:
                raise HTTPException(status_code=429, detail="Límite por minuto excedido")

            cur.execute(
                """
                UPDATE api_keys
                SET ultimo_uso = %s,
                    ultima_ip = %s,
                    total_requests = COALESCE(total_requests, consultas_realizadas) + 1,
                    consultas_realizadas = COALESCE(total_requests, consultas_realizadas) + 1
                WHERE id = %s
                """,
                (now, ip, api_key_id),
            )

    request.state.api_key_id = api_key_id
    request.state.api_key_name = row[1]
    request.state.api_key_preview = row[3]
    request.state.api_key_hash = key_hash
    request.state.client_ip = ip
    request.state.user_agent = user_agent
    request.state.requests_today = requests_today + 1
    request.state.requests_this_minute = requests_this_minute + 1
    request.state.last_used_at = now
    return row


def validate_admin_key(x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key")):
    import os

    admin_key = os.getenv("API_ADMIN_KEY", "")
    if not x_admin_key or x_admin_key != admin_key:
        raise HTTPException(status_code=401, detail="Admin key inválida")
    return True
