from datetime import datetime, timezone
from typing import Optional

from app.database import get_conn


def register_log(
    api_key_id: Optional[int],
    ruc_consultado: Optional[str],
    endpoint: str,
    metodo: str,
    ip: Optional[str],
    user_agent: Optional[str],
    codigo_http: int,
    tiempo_respuesta_ms: int,
    origen: Optional[str] = None,
):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO api_logs (
                    api_key_id, ruc_consultado, endpoint, metodo, ip, user_agent,
                    codigo_http, tiempo_respuesta_ms, origen, fecha
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    api_key_id,
                    ruc_consultado,
                    endpoint,
                    metodo,
                    ip,
                    user_agent,
                    codigo_http,
                    tiempo_respuesta_ms,
                    origen,
                    datetime.now(timezone.utc),
                ),
            )

