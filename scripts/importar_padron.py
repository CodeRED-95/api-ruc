from __future__ import annotations

import csv
import io
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import psycopg
from psycopg import sql
from tqdm import tqdm


DATABASE_URL = os.getenv("DATABASE_URL")
TABLE_NAME = os.getenv("PADRON_TABLE", "padron_ruc")
DELIMITER = os.getenv("PADRON_DELIMITER", "|")
IMPORT_BATCH_SIZE = int(os.getenv("IMPORT_BATCH_SIZE", "50000"))
IMPORT_SKIP_ERRORS = os.getenv("IMPORT_SKIP_ERRORS", "true").lower() == "true"
IMPORT_LOG_ERRORS = os.getenv("IMPORT_LOG_ERRORS", "true").lower() == "true"
IMPORT_ENCODING = os.getenv("IMPORT_ENCODING", "utf-8")
IMPORT_ERRORS_FILE = os.getenv("IMPORT_ERRORS_FILE", "logs/import_errors.log")

EXPECTED_COLUMNS = 9


@dataclass
class ImportStats:
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
    def records_per_second(self) -> float:
        elapsed = self.elapsed_seconds
        return self.imported / elapsed if elapsed > 0 else 0.0


def configure_csv_field_size_limit() -> None:
    """
    Set a large csv field limit in a cross-platform safe way.
    Uses a bounded loop to avoid OverflowError on Windows/macOS/Linux.
    """
    limit = getattr(sys, "maxsize", 2**31 - 1)
    while True:
        try:
            csv.field_size_limit(limit)
            return
        except OverflowError:
            limit //= 10
            if limit <= 0:
                raise


def ensure_parent_dirs() -> None:
    Path(IMPORT_ERRORS_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(parents=True, exist_ok=True)


def open_error_log():
    if not IMPORT_LOG_ERRORS:
        return None
    ensure_parent_dirs()
    return open(IMPORT_ERRORS_FILE, "a", encoding="utf-8", errors="replace")


def log_error(handle, line_number: int, reason: str, raw_line: str | None) -> None:
    if handle is None:
        return
    handle.write(f"Linea {line_number}\n")
    handle.write(f"Motivo: {reason}\n")
    if raw_line:
        handle.write("\n")
        handle.write(raw_line.rstrip("\n"))
        handle.write("\n")
    handle.write("\n--------------------------------\n\n")
    handle.flush()


def detect_row_count(path: Path, encoding: str) -> int:
    with path.open("r", encoding=encoding, errors="replace", newline="") as f:
        return sum(1 for _ in f)


def guess_delimiter(sample_line: str, configured_delimiter: str) -> str:
    if configured_delimiter in sample_line:
        return configured_delimiter
    for candidate in ("|", ";", ",", "\t"):
        if candidate in sample_line:
            return candidate
    return configured_delimiter


def clean_value(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().strip('"').strip("'")


def normalize_row(raw_row: list[str]) -> list[str] | None:
    if len(raw_row) < EXPECTED_COLUMNS:
        return None

    row = [clean_value(v) for v in raw_row[:EXPECTED_COLUMNS]]
    ruc = row[0]
    razon_social = row[1]

    if len(ruc) != 11 or not ruc.isdigit():
        return None
    if not razon_social:
        return None

    return row


def iter_valid_rows(
    path: Path,
    delimiter: str,
    encoding: str,
    stats: ImportStats,
    error_log,
) -> Iterator[list[str]]:
    with path.open("r", encoding=encoding, errors="strict", newline="") as source:
        first_line = source.readline()
        if not first_line:
            raise ValueError("El archivo está vacío")

        actual_delimiter = guess_delimiter(first_line, delimiter)
        source.seek(0)

        for line_number, raw_line in enumerate(source, start=1):
            stats.total_lines += 1
            if not raw_line.strip():
                stats.skipped += 1
                log_error(error_log, line_number, "Línea vacía", raw_line)
                continue

            try:
                parsed = next(csv.reader([raw_line], delimiter=actual_delimiter))
            except csv.Error as exc:
                stats.errors += 1
                if IMPORT_SKIP_ERRORS:
                    log_error(error_log, line_number, f"Error CSV: {exc}", raw_line)
                    continue
                raise

            if len(parsed) < EXPECTED_COLUMNS:
                stats.skipped += 1
                log_error(error_log, line_number, "Columnas inválidas o registro incompleto", raw_line)
                continue

            normalized = normalize_row(parsed)
            if normalized is None:
                stats.skipped += 1
                reason = "RUC inválido" if not (parsed and len(parsed[0].strip()) == 11 and parsed[0].strip().isdigit()) else "Registro incompleto o razón social vacía"
                log_error(error_log, line_number, reason, raw_line)
                continue

            yield normalized


def copy_batch(conn, batch: list[list[str]], table_name: str) -> None:
    if not batch:
        return
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    for row in batch:
        writer.writerow(row)
    buffer.seek(0)

    with conn.cursor() as cur:
        with cur.copy(
            sql.SQL(
                """
                COPY {} (ruc, razon_social, estado, condicion, ubigeo, direccion, provincia, departamento, distrito)
                FROM STDIN WITH (FORMAT csv, DELIMITER E'\t', QUOTE '"')
                """
            ).format(sql.Identifier(table_name))
        ) as copy:
            copy.write(buffer.read())


def truncate_target_table(conn, table_name: str) -> None:
    with conn.cursor() as cur:
        cur.execute(sql.SQL("TRUNCATE TABLE {}").format(sql.Identifier(table_name)))


def validate_input_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {path}")
    if not path.is_file():
        raise ValueError(f"Ruta inválida, se esperaba un archivo: {path}")
    if path.stat().st_size == 0:
        raise ValueError("El archivo está vacío")


def print_summary(stats: ImportStats, error_file: str) -> None:
    print("\nImportación finalizada correctamente\n")
    print(f"Tiempo: {stats.minutes:.2f} minutos")
    print(f"Filas importadas: {stats.imported}")
    print(f"Errores: {stats.errors}")
    print(f"Archivo de errores: {error_file}")
    print()


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: python scripts/importar_padron.py /ruta/al/padron.txt")
        sys.exit(1)
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no está configurada")

    configure_csv_field_size_limit()
    ensure_parent_dirs()

    input_path = Path(sys.argv[1])
    validate_input_file(input_path)

    stats = ImportStats(start_time=time.perf_counter())
    error_log = open_error_log()

    try:
        try:
            total_rows = detect_row_count(input_path, IMPORT_ENCODING)
        except UnicodeDecodeError as exc:
            raise ValueError(
                f"Codificación inválida para {input_path}. "
                f"Verifica IMPORT_ENCODING={IMPORT_ENCODING}. Detalle: {exc}"
            ) from exc

        if total_rows == 0:
            raise ValueError("El archivo está vacío")

        batch_size = max(int(IMPORT_BATCH_SIZE), 1)
        copy_buffer: list[list[str]] = []
        with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
            truncate_target_table(conn, TABLE_NAME)

            with tqdm(
                total=total_rows,
                desc="Importando",
                unit="filas",
                dynamic_ncols=True,
                smoothing=0.1,
            ) as pbar:
                for normalized_row in iter_valid_rows(
                    input_path,
                    DELIMITER,
                    IMPORT_ENCODING,
                    stats,
                    error_log,
                ):
                    copy_buffer.append(normalized_row)
                    stats.imported += 1
                    pbar.update(1)
                    pbar.set_postfix(
                        validos=stats.imported,
                        ignorados=stats.skipped + stats.errors,
                        velocidad=f"{stats.records_per_second:.1f}/s",
                        eta=f"{int(pbar.format_dict.get('remaining', 0))}s",
                    )

                    if len(copy_buffer) >= batch_size:
                        copy_batch(conn, copy_buffer, TABLE_NAME)
                        copy_buffer.clear()

                if copy_buffer:
                    copy_batch(conn, copy_buffer, TABLE_NAME)
                    copy_buffer.clear()

        if IMPORT_LOG_ERRORS and error_log is not None:
            error_log.flush()

        print_summary(stats, IMPORT_ERRORS_FILE if IMPORT_LOG_ERRORS else "deshabilitado")
        print(f"Total de líneas: {stats.total_lines}")
        print(f"Importadas: {stats.imported}")
        print(f"Ignoradas: {stats.skipped}")
        print(f"Errores: {stats.errors}")
        print(f"Tiempo total: {stats.minutes:.2f} minutos")
        print(f"Velocidad: {stats.records_per_second:.2f} registros/segundo")
    except Exception as exc:
        print(f"\nERROR: {exc}")
        print("La importación se detuvo por un problema no recuperable.")
        sys.exit(1)
    finally:
        if error_log is not None:
            error_log.close()


if __name__ == "__main__":
    main()
