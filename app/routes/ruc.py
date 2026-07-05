import os
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.database import get_conn
from app.services.auth import validate_api_key
from app.schemas import PaginatedRucResponse, RucResponse
from app.services.cache import get_json, set_json

router = APIRouter(dependencies=[Depends(validate_api_key)])

DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_PAGE_SIZE", "50"))
MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", "200"))


def validate_ruc(ruc: str) -> str:
    if not re.fullmatch(r"\d{11}", ruc):
        raise HTTPException(status_code=422, detail="El RUC debe tener 11 dígitos numéricos")
    return ruc


def row_to_dict(row) -> dict:
    return {
        "ruc": row[0],
        "razon_social": row[1],
        "estado": row[2],
        "condicion": row[3],
        "ubigeo": row[4],
        "direccion": row[5],
        "provincia": row[6],
        "departamento": row[7],
        "distrito": row[8],
    }


@router.get("/ruc/{ruc}", response_model=RucResponse, responses={401: {"description": "Unauthorized"}, 404: {"description": "Not Found"}, 429: {"description": "Too Many Requests"}, 500: {"description": "Server Error"}})
def get_by_ruc(ruc: str, request: Request):
    ruc = validate_ruc(ruc)
    cache_key = f"ruc:{ruc}"
    cached = get_json(cache_key)
    if cached is not None:
        return cached

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ruc, razon_social, estado, condicion, ubigeo, direccion, provincia, departamento, distrito
                FROM padron_ruc
                WHERE ruc = %s
                """,
                (ruc,),
            )
            row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="RUC no encontrado")
    data = row_to_dict(row)
    set_json(cache_key, data)
    return data


@router.get("/buscar", response_model=PaginatedRucResponse, responses={401: {"description": "Unauthorized"}, 429: {"description": "Too Many Requests"}})
def search_by_name(request: Request, nombre: str = Query(..., min_length=2), page: int = 1, page_size: int = DEFAULT_PAGE_SIZE):
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    offset = (page - 1) * page_size
    like = f"%{nombre.strip()}%"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM padron_ruc WHERE razon_social ILIKE %s", (like,))
            total = cur.fetchone()[0]
            cur.execute(
                """
                SELECT ruc, razon_social, estado, condicion, ubigeo, direccion, provincia, departamento, distrito
                FROM padron_ruc
                WHERE razon_social ILIKE %s
                ORDER BY razon_social, ruc
                LIMIT %s OFFSET %s
                """,
                (like, page_size, offset),
            )
            items = [row_to_dict(row) for row in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


def list_by_field(field: str, value: str, page: int, page_size: int):
    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    offset = (page - 1) * page_size
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM padron_ruc WHERE {field} = %s", (value,))
            total = cur.fetchone()[0]
            cur.execute(
                f"""
                SELECT ruc, razon_social, estado, condicion, ubigeo, direccion, provincia, departamento, distrito
                FROM padron_ruc
                WHERE {field} = %s
                ORDER BY razon_social, ruc
                LIMIT %s OFFSET %s
                """,
                (value, page_size, offset),
            )
            items = [row_to_dict(row) for row in cur.fetchall()]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/estado/{estado}", response_model=PaginatedRucResponse)
def get_by_estado(request: Request, estado: str, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE):
    return list_by_field("estado", estado.strip(), page, page_size)


@router.get("/condicion/{condicion}", response_model=PaginatedRucResponse)
def get_by_condicion(request: Request, condicion: str, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE):
    return list_by_field("condicion", condicion.strip(), page, page_size)


@router.get("/ubigeo/{ubigeo}", response_model=PaginatedRucResponse)
def get_by_ubigeo(request: Request, ubigeo: str, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE):
    return list_by_field("ubigeo", ubigeo.strip(), page, page_size)
