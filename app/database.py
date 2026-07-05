import os
from contextlib import contextmanager

import psycopg
from psycopg_pool import ConnectionPool


DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está configurada")

POOL_MIN_SIZE = int(os.getenv("DB_POOL_MIN_SIZE", "5"))
POOL_MAX_SIZE = int(os.getenv("DB_POOL_MAX_SIZE", "20"))

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    min_size=POOL_MIN_SIZE,
    max_size=POOL_MAX_SIZE,
    kwargs={"autocommit": True},
)


@contextmanager
def get_conn():
    with pool.connection() as conn:
        yield conn


def healthcheck() -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone() is not None


def ensure_schema() -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
