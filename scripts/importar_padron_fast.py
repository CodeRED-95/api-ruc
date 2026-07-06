from __future__ import annotations

import csv
import io
import os
import sys
import time
from dataclasses import dataclass
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


def validate_input_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {path}")
    if path.stat().st_size == 0:
        raise ValueError("El archivo está vacío")


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

    input_file = Path(sys.argv[1])
    try:
        validate_input_file(input_file)
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    stats = Stats(start_time=time.perf_counter())
    error_log = open_error_log()

    try:
        try:
            with input_file.open("r", encoding=IMPORT_ENCODING, errors="strict", newline="") as probe:
                total_lines = sum(1 for _ in probe)
        except UnicodeDecodeError as exc:
            print(f"ERROR: codificación inválida. Revisa IMPORT_ENCODING={IMPORT_ENCODING}. Detalle: {exc}")
            return 1

        if total_lines == 0:
            print("ERROR: El archivo está vacío")
            return 1

        batch_size = max(1, int(IMPORT_BATCH_SIZE))
        batch: list[list[str]] = []

        with psycopg.connect(DATABASE_URL) as conn:
            conn.autocommit = False
            create_staging_table(conn)
            conn.commit()

            with tqdm(
                total=total_lines,
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

            inserted = insert_from_staging(conn)
            conn.commit()
            with conn.cursor() as cur:
                cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(PADRON_TABLE)))
                stats.imported = cur.fetchone()[0]

            create_indexes(conn)
            conn.commit()

            with conn.cursor() as cur:
                cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(STAGING_TABLE)))
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
        print(f"ERROR: {exc}")
        return 1
    finally:
        if error_log:
            error_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
