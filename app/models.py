from dataclasses import dataclass


@dataclass
class RucRecord:
    ruc: str
    razon_social: str
    estado: str
    condicion: str
    ubigeo: str
    direccion: str | None = None
    provincia: str | None = None
    departamento: str | None = None
    distrito: str | None = None


@dataclass
class ApiTokenRecord:
    id: int
    nombre: str
    token_preview: str | None
    is_active: bool
    descripcion: str | None
    created_at: str | None = None
    last_used_at: str | None = None
    daily_limit: int | None = None
    minute_limit: int | None = None
    total_requests: int = 0
    last_ip: str | None = None
    disabled_at: str | None = None
    deleted_at: str | None = None
