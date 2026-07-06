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

CREATE TABLE IF NOT EXISTS api_keys (
    id BIGSERIAL PRIMARY KEY,
    nombre VARCHAR(150) NOT NULL UNIQUE,
    api_key_hash CHAR(64) NOT NULL UNIQUE,
    token_preview TEXT,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    descripcion TEXT,
    fecha_creacion TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ultimo_uso TIMESTAMPTZ,
    limite_diario INTEGER NOT NULL DEFAULT 1000,
    limite_por_minuto INTEGER NOT NULL DEFAULT 60,
    total_requests BIGINT NOT NULL DEFAULT 0,
    consultas_realizadas BIGINT NOT NULL DEFAULT 0,
    ultima_ip INET,
    disabled_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_api_keys_activo ON api_keys (activo);
CREATE INDEX IF NOT EXISTS idx_api_keys_nombre_trgm ON api_keys USING gin (nombre gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_api_keys_deleted_at ON api_keys (deleted_at);

CREATE TABLE IF NOT EXISTS api_logs (
    id BIGSERIAL PRIMARY KEY,
    api_key_id BIGINT REFERENCES api_keys(id) ON DELETE SET NULL,
    ruc_consultado CHAR(11),
    endpoint TEXT NOT NULL,
    metodo VARCHAR(10) NOT NULL,
    ip INET,
    user_agent TEXT,
    codigo_http INTEGER NOT NULL,
    tiempo_respuesta_ms INTEGER NOT NULL,
    origen TEXT,
    fecha TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_api_logs_api_key_id ON api_logs (api_key_id);
CREATE INDEX IF NOT EXISTS idx_api_logs_ruc_consultado ON api_logs (ruc_consultado);
CREATE INDEX IF NOT EXISTS idx_api_logs_fecha ON api_logs (fecha DESC);
CREATE INDEX IF NOT EXISTS idx_api_logs_codigo_http ON api_logs (codigo_http);

ALTER TABLE api_keys
    ADD COLUMN IF NOT EXISTS token_preview TEXT,
    ADD COLUMN IF NOT EXISTS total_requests BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS import_history (
    id BIGSERIAL PRIMARY KEY,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size BIGINT NOT NULL,
    file_mtime TIMESTAMPTZ NOT NULL,
    signature_hash CHAR(64) NOT NULL,
    import_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    import_finished_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed', 'skipped')),
    rows_imported BIGINT NOT NULL DEFAULT 0,
    rows_skipped BIGINT NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_import_history_signature ON import_history (file_size, file_mtime, signature_hash, status);
CREATE INDEX IF NOT EXISTS idx_import_history_created_at ON import_history (created_at DESC);
