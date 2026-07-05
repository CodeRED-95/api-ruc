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

