import json
import os
from typing import Any, Optional

import redis


REDIS_URL = os.getenv("REDIS_URL")
REDIS_ENABLED = os.getenv("REDIS_ENABLED", "true").lower() == "true"
CACHE_TTL_SECONDS = int(os.getenv("CACHE_TTL_SECONDS", "3600"))

client: Optional[redis.Redis] = None

if REDIS_ENABLED and REDIS_URL:
    client = redis.from_url(REDIS_URL, decode_responses=True)


def get_json(key: str) -> Any | None:
    if client is None:
        return None
    value = client.get(key)
    if value is None:
        return None
    return json.loads(value)


def set_json(key: str, value: Any, ttl: int = CACHE_TTL_SECONDS) -> None:
    if client is None:
        return
    client.setex(key, ttl, json.dumps(value, ensure_ascii=False))


def ping() -> bool:
    if client is None:
        return False
    return bool(client.ping())

