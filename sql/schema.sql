CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS padron_ruc (
    ruc CHAR(11) PRIMARY KEY,
    razon_social TEXT NOT NULL,
    estado TEXT NOT NULL,
    condicion TEXT NOT NULL,
    ubigeo TEXT NOT NULL,
    direccion TEXT,
    provincia TEXT,
    departamento TEXT,
    distrito TEXT
);

CREATE INDEX IF NOT EXISTS idx_padron_estado ON padron_ruc (estado);
CREATE INDEX IF NOT EXISTS idx_padron_condicion ON padron_ruc (condicion);
CREATE INDEX IF NOT EXISTS idx_padron_ubigeo ON padron_ruc (ubigeo);
CREATE INDEX IF NOT EXISTS idx_padron_razon_social_trgm ON padron_ruc USING gin (razon_social gin_trgm_ops);
