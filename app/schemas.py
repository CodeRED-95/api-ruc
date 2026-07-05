from typing import List, Optional

from pydantic import BaseModel, Field


class RucBase(BaseModel):
    ruc: str = Field(min_length=11, max_length=11, pattern=r"^\d{11}$")
    razon_social: str
    estado: str
    condicion: str
    ubigeo: str
    direccion: Optional[str] = None
    provincia: Optional[str] = None
    departamento: Optional[str] = None
    distrito: Optional[str] = None


class RucResponse(RucBase):
    pass


class PaginatedRucResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[RucResponse]


class HealthResponse(BaseModel):
    status: str
    database: str
    redis: Optional[str] = None

