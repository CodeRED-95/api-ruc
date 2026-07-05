import csv
import io
import os
import sys
from pathlib import Path

import psycopg
from psycopg import sql
from tqdm import tqdm


DATABASE_URL = os.getenv("DATABASE_URL")
TABLE_NAME = os.getenv("PADRON_TABLE", "padron_ruc")
DELIMITER = os.getenv("PADRON_DELIMITER", "|")


def detect_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as f:
        return sum(1 for _ in f)


def clean_value(value: str | None) -> str:
    if value is None:
        return ""
    return value.strip().strip('"').strip("'")


def normalize_row(row: list[str]) -> list[str] | None:
    if len(row) < 5:
        return None
    row = [clean_value(v) for v in row]
    ruc = row[0]
    if len(ruc) != 11 or not ruc.isdigit():
        return None
    razon_social = row[1]
    if not razon_social:
        return None
    padded = row[:9] + [""] * max(0, 9 - len(row))
    return padded[:9]


def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/importar_padron.py /ruta/al/padron.txt")
        sys.exit(1)
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL no está configurada")

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    total_rows = detect_rows(input_path)
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {TABLE_NAME}")

        with input_path.open("r", encoding="utf-8", errors="ignore", newline="") as source:
            reader = csv.reader(source, delimiter=DELIMITER)
            buffer = io.StringIO()
            writer = csv.writer(buffer, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
            copied = 0
            with conn.cursor() as cur:
                with tqdm(total=total_rows, desc="Importando", unit="filas") as pbar:
                    for row in reader:
                        normalized = normalize_row(row)
                        pbar.update(1)
                        if not normalized:
                            continue
                        writer.writerow(normalized)
                        copied += 1
                        if copied % 50000 == 0:
                            buffer.seek(0)
                            with cur.copy(
                                sql.SQL(
                                    """
                                    COPY {} (ruc, razon_social, estado, condicion, ubigeo, direccion, provincia, departamento, distrito)
                                    FROM STDIN WITH (FORMAT csv, DELIMITER E'\t', QUOTE '"')
                                    """
                                ).format(sql.Identifier(TABLE_NAME))
                            ) as copy:
                                copy.write(buffer.read())
                            buffer = io.StringIO()
                            writer = csv.writer(buffer, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
                    if buffer.tell() > 0:
                        buffer.seek(0)
                        with cur.copy(
                            sql.SQL(
                                """
                                COPY {} (ruc, razon_social, estado, condicion, ubigeo, direccion, provincia, departamento, distrito)
                                FROM STDIN WITH (FORMAT csv, DELIMITER E'\t', QUOTE '"')
                                """
                            ).format(sql.Identifier(TABLE_NAME))
                        ) as copy:
                            copy.write(buffer.read())


if __name__ == "__main__":
    main()

