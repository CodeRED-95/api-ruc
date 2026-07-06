from __future__ import annotations

import csv
import hashlib
import io
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Iterable, Optional

import psycopg
from psycopg import sql
from tqdm import tqdm


DATABASE_URL = os.getenv("DATABASE_URL")
PADRON_TABLE = os.getenv("PADRON_TABLE", "padron_ruc")
PADRON_DELIMITER = os.getenv("PADRON_DELIMITER", "|")
IMPORT_BATCH_SIZE = int(os.getenv("IMPORT_BATCH_SIZE", "250000"))
IMPORT_ENCODING = os.getenv("IMPORT_ENCODING", "latin-1")
IMPORT_LOG_ERRORS = os.getenv("IMPORT_LOG_ERRORS", "true").lower() == "true"
IMPORT_ERRORS_FILE = os.getenv("IMPORT_ERRORS_FILE", "logs/importacion_padron.log")
IMPORT_SKIP_ERRORS = os.getenv("IMPORT_SKIP_ERRORS", "true").lower() == "true"
IMPORT_SIGNATURE_HEAD_BYTES = int(os.getenv("IMPORT_SIGNATURE_HEAD_BYTES", "1048576"))
IMPORT_SIGNATURE_TAIL_BYTES = int(os.getenv("IMPORT_SIGNATURE_TAIL_BYTES", "1048576"))
IMPORT_FORCE = os.getenv("IMPORT_FORCE", "false").lower() == "true"

STAGING_TABLE = f"{PADRON_TABLE}_staging"
EXPECTED_OUTPUT_COLUMNS = 9


@dataclass
class Stats:
    total_lines: int = 0
    imported: int = 0
    skipped: int = 0
    errors: int = 0
    start_time: float = 0.0

    @property
    def elapsed_seconds(self) -> float:
        return max(time.perf_counter() - self.start_time, 0.0)

    @property
    def minutes(self) -> float:
        return self.elapsed_seconds / 60.0

    @property
    def speed(self) -> float:
        return self.imported / self.elapsed_seconds if self.elapsed_seconds > 0 else 0.0


@dataclass
class FileMeta:
    file_name: str
    file_path: str
    file_size: int
    file_mtime: datetime
    signature_hash: str


def configure_csv_limits() -> None:
    limit = getattr(sys, "maxsize", 2**31 - 1)
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10
            if limit <= 0:
                raise


def ensure_dirs() -> None:
    Path("logs").mkdir(parents=True, exist_ok=True)
    Path("data").mkdir(parents=True, exist_ok=True)


def open_error_log():
    if not IMPORT_LOG_ERRORS:
        return None
    ensure_dirs()
    return open(IMPORT_ERRORS_FILE, "a", encoding="utf-8", errors="replace")


def write_log(handle, line_no: int, reason: str, raw_line: str | None = None) -> None:
    if handle is None:
        return
    handle.write(f"Linea {line_no}\n")
    handle.write(f"Motivo: {reason}\n")
    if raw_line:
        handle.write(f"Contenido: {raw_line.rstrip()}\n")
    handle.write("\n--------------------------------\n\n")
    handle.flush()


def write_info(handle, message: str) -> None:
    if handle is None:
        return
    handle.write(f"{message}\n")
    handle.flush()


def validate_input_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {path}")
    if path.stat().st_size == 0:
        raise ValueError("El archivo está vacío")


def build_quick_signature(path: Path) -> FileMeta:
    stat_result = path.stat()
    file_size = stat_result.st_size
    file_mtime = datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc)
    head_bytes = max(0, IMPORT_SIGNATURE_HEAD_BYTES)
    tail_bytes = max(0, IMPORT_SIGNATURE_TAIL_BYTES)

    with path.open("rb") as f:
        head = f.read(head_bytes)
        tail = b""
        if tail_bytes > 0 and file_size > tail_bytes:
            try:
                f.seek(max(file_size - tail_bytes, 0))
                tail = f.read(tail_bytes)
            except OSError:
                tail = b""
        elif tail_bytes > 0:
            remaining = f.read()
            tail = remaining[-tail_bytes:] if remaining else b""

    signature_parts = [
        str(path.resolve()),
        path.name,
        str(file_size),
        file_mtime,
        head.hex(),
        tail.hex(),
    ]
    signature_source = "|".join(signature_parts).encode("utf-8", errors="ignore")
    signature_hash = hashlib.sha256(signature_source).hexdigest()
    return FileMeta(
        file_name=path.name,
        file_path=str(path.resolve()),
        file_size=file_size,
        file_mtime=file_mtime,
        signature_hash=signature_hash,
    )


def detect_delimiter(sample: str, configured: str) -> str:
    if configured in sample:
        return configured
    for candidate in ("|", ";", ",", "\t"):
        if candidate in sample:
            return candidate
    return configured


def clean_value(value: Optional[str]) -> str:
    if value is None:
        return ""
    value = value.strip().strip('"').strip("'")
    return "" if value in {"-", "NULL", "null"} else value


def normalize_record(row: list[str]) -> list[str] | None:
    if len(row) < 5:
        return None

    ruc = clean_value(row[0])
    razon_social = clean_value(row[1])
    estado = clean_value(row[2])
    condicion = clean_value(row[3])
    ubigeo = clean_value(row[4])

    if len(ruc) != 11 or not ruc.isdigit():
        return None
    if not razon_social:
        return None

    # El archivo SUNAT trae más columnas que las necesarias.
    # Tomamos las necesarias por posición real observada:
    # 1 ruc, 2 razon_social, 3 estado, 4 condicion, 5 ubigeo
    # Dirección suele estar distribuida en columnas de texto libre;
    # para priorizar velocidad se usa la columna 8 si existe y, si no,
    # se construye una dirección mínima con los datos de ubicación.
    direccion = clean_value(row[7]) if len(row) > 7 else ""
    provincia = clean_value(row[8]) if len(row) > 8 else ""
    departamento = clean_value(row[9]) if len(row) > 9 else ""
    distrito = clean_value(row[10]) if len(row) > 10 else ""

    if not direccion:
        partes = [p for p in (provincia, departamento, distrito) if p]
        direccion = " - ".join(partes) if partes else ""

    return [ruc, razon_social, estado, condicion, ubigeo, direccion, provincia, departamento, distrito]


def read_rows(path: Path, encoding: str, delimiter: str, stats: Stats, error_log) -> Iterable[list[str]]:
    with path.open("r", encoding=encoding, errors="strict", newline="") as f:
        sample = f.readline()
        if not sample:
            raise ValueError("El archivo está vacío")
        detected_delimiter = detect_delimiter(sample, delimiter)
        f.seek(0)

        for line_no, raw_line in enumerate(f, start=1):
            stats.total_lines += 1
            if not raw_line.strip():
                stats.skipped += 1
                write_log(error_log, line_no, "Línea vacía", raw_line)
                continue
            try:
                parsed = next(csv.reader([raw_line], delimiter=detected_delimiter))
            except csv.Error as exc:
                stats.errors += 1
                write_log(error_log, line_no, f"Error CSV: {exc}", raw_line)
                if IMPORT_SKIP_ERRORS:
                    continue
                raise

            normalized = normalize_record(parsed)
            if normalized is None:
                stats.skipped += 1
                reason = "RUC inválido" if parsed and (len(parsed[0].strip()) != 11 or not parsed[0].strip().isdigit()) else "Registro incompleto"
                write_log(error_log, line_no, reason, raw_line)
                continue
            yield normalized


def create_staging_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(STAGING_TABLE)))
        cur.execute(
            sql.SQL(
                """
                CREATE UNLOGGED TABLE {} (
                    ruc CHAR(11),
                    razon_social TEXT,
                    estado TEXT,
                    condicion TEXT,
                    ubigeo TEXT,
                    direccion TEXT,
                    provincia TEXT,
                    departamento TEXT,
                    distrito TEXT
                )
                """
            ).format(sql.Identifier(STAGING_TABLE))
        )


def ensure_import_history_table(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
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
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_import_history_signature
            ON import_history (file_size, file_mtime, signature_hash, status)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_import_history_created_at
            ON import_history (created_at DESC)
            """
        )


def load_batch_to_staging(conn, batch: list[list[str]]) -> None:
    if not batch:
        return
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerows(batch)
    buffer.seek(0)
    with conn.cursor() as cur:
        with cur.copy(
            sql.SQL(
                """
                COPY {} (ruc, razon_social, estado, condicion, ubigeo, direccion, provincia, departamento, distrito)
                FROM STDIN WITH (FORMAT csv, DELIMITER E'\t', QUOTE '"')
                """
            ).format(sql.Identifier(STAGING_TABLE))
        ) as copy:
            copy.write(buffer.read())


def insert_from_staging(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                INSERT INTO {}
                (ruc, razon_social, estado, condicion, ubigeo, direccion, provincia, departamento, distrito)
                SELECT DISTINCT ON (s.ruc)
                    s.ruc,
                    s.razon_social,
                    s.estado,
                    s.condicion,
                    s.ubigeo,
                    s.direccion,
                    s.provincia,
                    s.departamento,
                    s.distrito
                FROM {}
                s
                WHERE s.ruc IS NOT NULL
                  AND char_length(trim(s.ruc)) = 11
                  AND trim(s.ruc) ~ '^[0-9]+$'
                  AND coalesce(trim(s.razon_social), '') <> ''
                ORDER BY s.ruc
                ON CONFLICT (ruc) DO UPDATE SET
                    razon_social = EXCLUDED.razon_social,
                    estado = EXCLUDED.estado,
                    condicion = EXCLUDED.condicion,
                    ubigeo = EXCLUDED.ubigeo,
                    direccion = EXCLUDED.direccion,
                    provincia = EXCLUDED.provincia,
                    departamento = EXCLUDED.departamento,
                    distrito = EXCLUDED.distrito
                """
            ).format(sql.Identifier(PADRON_TABLE), sql.Identifier(STAGING_TABLE))
        )
        return cur.rowcount or 0


def create_indexes(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        cur.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS idx_padron_estado ON {} (estado)").format(
                sql.Identifier(PADRON_TABLE)
            )
        )
        cur.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS idx_padron_condicion ON {} (condicion)").format(
                sql.Identifier(PADRON_TABLE)
            )
        )
        cur.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS idx_padron_ubigeo ON {} (ubigeo)").format(
                sql.Identifier(PADRON_TABLE)
            )
        )
        cur.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS idx_padron_razon_social_trgm ON {} USING gin (razon_social gin_trgm_ops)").format(
                sql.Identifier(PADRON_TABLE)
            )
        )


def get_last_completed_import(conn, meta: FileMeta):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM import_history
            WHERE file_size = %s
              AND file_mtime = %s
              AND signature_hash = %s
              AND status = 'completed'
            ORDER BY id DESC
            LIMIT 1
            """,
            (meta.file_size, meta.file_mtime, meta.signature_hash),
        )
        return cur.fetchone()


def insert_import_history(conn, meta: FileMeta, status: str, rows_imported: int = 0, rows_skipped: int = 0, error_message: str | None = None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO import_history (
                file_name, file_path, file_size, file_mtime, signature_hash,
                import_started_at, status, rows_imported, rows_skipped, error_message
            ) VALUES (%s, %s, %s, %s, %s, NOW(), %s, %s, %s, %s)
            RETURNING id
            """,
            (
                meta.file_name,
                meta.file_path,
                meta.file_size,
                meta.file_mtime,
                meta.signature_hash,
                status,
                rows_imported,
                rows_skipped,
                error_message,
            ),
        )
        return cur.fetchone()[0]


def update_import_history(conn, history_id: int, status: str, stats: Stats, error_message: str | None = None):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE import_history
            SET import_finished_at = NOW(),
                status = %s,
                rows_imported = %s,
                rows_skipped = %s,
                error_message = %s
            WHERE id = %s
            """,
            (status, stats.imported, stats.skipped, error_message, history_id),
        )


def log_progress(stats: Stats, pbar) -> None:
    pbar.set_postfix(
        importadas=stats.imported,
        ignoradas=stats.skipped,
        errores=stats.errors,
        velocidad=f"{stats.speed:.1f}/s",
    )


def print_summary(stats: Stats, error_file: str) -> None:
    print("\nImportación finalizada correctamente\n")
    print(f"Tiempo: {stats.minutes:.2f} minutos")
    print(f"Filas importadas: {stats.imported}")
    print(f"Errores: {stats.errors}")
    print(f"Archivo de errores: {error_file}")
    print()


def main() -> int:
    if len(sys.argv) < 2:
        print("Uso: python scripts/importar_padron_fast.py /app/data/padron.txt")
        return 1
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL no está configurada")
        return 1

    configure_csv_limits()
    ensure_dirs()

    force = IMPORT_FORCE or "--force" in sys.argv[2:]
    input_file = Path(sys.argv[1])
    try:
        validate_input_file(input_file)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    stats = Stats(start_time=time.perf_counter())
    error_log = open_error_log()

    try:
        write_info(error_log, "Verificando firma rápida del archivo...")
        meta = build_quick_signature(input_file)
        write_info(
            error_log,
            f"Archivo detectado: {meta.file_name} | size={meta.file_size} | mtime={meta.file_mtime} | signature={meta.signature_hash}",
        )

        try:
            with input_file.open("r", encoding=IMPORT_ENCODING, errors="strict", newline="") as probe:
                probe.readline()
        except UnicodeDecodeError as exc:
            print(f"ERROR: codificación inválida. Revisa IMPORT_ENCODING={IMPORT_ENCODING}. Detalle: {exc}")
            return 1

        batch_size = max(1, int(IMPORT_BATCH_SIZE))
        batch: list[list[str]] = []

        with psycopg.connect(DATABASE_URL) as conn:
            conn.autocommit = False
            ensure_import_history_table(conn)
            conn.commit()

            last_completed = None if force else get_last_completed_import(conn, meta)
            if last_completed:
                message = "El archivo ya fue importado anteriormente.\nImportación omitida."
                print(message)
                write_info(error_log, "Archivo ya importado. Se omite la importación.")
                skipped_history_id = insert_import_history(conn, meta, "skipped")
                conn.commit()
                update_import_history(conn, skipped_history_id, "skipped", stats, "Archivo idéntico previamente importado")
                conn.commit()
                print_summary(stats, IMPORT_ERRORS_FILE if IMPORT_LOG_ERRORS else "deshabilitado")
                return 0

            write_info(error_log, "Nueva versión detectada. Iniciando importación...")
            history_id = insert_import_history(conn, meta, "running")
            conn.commit()

            if force:
                write_info(error_log, "IMPORT_FORCE activo. Se ejecutará la importación aunque el archivo parezca el mismo.")

            create_staging_table(conn)
            conn.commit()

            with tqdm(
                desc="Importando padrón",
                unit="líneas",
                dynamic_ncols=True,
                smoothing=0.1,
            ) as pbar:
                for row in read_rows(input_file, IMPORT_ENCODING, PADRON_DELIMITER, stats, error_log):
                    batch.append(row)
                    stats.imported += 1
                    pbar.update(1)
                    log_progress(stats, pbar)

                    if len(batch) >= batch_size:
                        load_batch_to_staging(conn, batch)
                        conn.commit()
                        batch.clear()

                if batch:
                    load_batch_to_staging(conn, batch)
                    conn.commit()
                    batch.clear()

            with conn.cursor() as cur:
                cur.execute(sql.SQL("TRUNCATE TABLE {}").format(sql.Identifier(PADRON_TABLE)))
            conn.commit()

            insert_from_staging(conn)
            conn.commit()
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(PADRON_TABLE)))
                stats.imported = cur.fetchone()[0]

            create_indexes(conn)
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(STAGING_TABLE)))
            conn.commit()

            update_import_history(conn, history_id, "completed", stats)
            conn.commit()

        if error_log:
            error_log.flush()

        print_summary(stats, IMPORT_ERRORS_FILE if IMPORT_LOG_ERRORS else "deshabilitado")
        print(f"Total de líneas: {stats.total_lines}")
        print(f"Importadas: {stats.imported}")
        print(f"Ignoradas: {stats.skipped}")
        print(f"Errores: {stats.errors}")
        print(f"Tiempo total: {stats.minutes:.2f} minutos")
        print(f"Velocidad: {stats.speed:.2f} registros/segundo")
        return 0
    except Exception as exc:
        try:
            if "history_id" in locals():
                with psycopg.connect(DATABASE_URL) as fail_conn:
                    fail_conn.autocommit = False
                    ensure_import_history_table(fail_conn)
                    update_import_history(fail_conn, history_id, "failed", stats, str(exc))
                    fail_conn.commit()
        except Exception:
            pass
        print(f"ERROR: {exc}")
        return 1
    finally:
        if error_log:
            error_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
