"""Carga de archivos CSV en tablas del motor (línea de comandos).

Ejemplos:
    python -m tools.import_csv --list
    python -m tools.import_csv --table alumnos --file alumnos_prueba_bd2.csv
    python -m tools.import_csv --table alumnos --file datos.csv --no-headers
    python -m tools.import_csv --sql "CREATE TABLE t (id INT PRIMARY KEY, x INT)" \
                               --table t --file datos.csv

Trabaja sobre el mismo catálogo que el API (`backend/data` + `catalog.json`),
por lo que la tabla debe existir antes de importar (créala con `--sql` o desde
el panel de consultas de la interfaz).

Nota: si el API está corriendo, sus índices viven en memoria; para que la
interfaz vea los datos importados usa mejor el endpoint
`POST /api/tables/{nombre}/import` (o reinicia el API tras usar este comando).
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.engine import DemoEngine, engine as motor_por_defecto  # noqa: E402


def _motor(data_dir: str | None):
    return DemoEngine(data_dir=data_dir) if data_dir else motor_por_defecto


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Carga un CSV en una tabla del minigestor",
    )
    parser.add_argument("--table", help="Tabla destino (debe existir)")
    parser.add_argument("--file", help="Ruta del archivo CSV")
    parser.add_argument(
        "--sql",
        help="Sentencia SQL a ejecutar antes de importar (por ejemplo CREATE TABLE)",
    )
    parser.add_argument(
        "--no-headers",
        action="store_true",
        help="El CSV no tiene fila de encabezado",
    )
    parser.add_argument("--delimiter", default=",", help="Separador (por defecto ',')")
    parser.add_argument("--encoding", default="utf-8", help="Codificación del archivo")
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directorio de datos (por defecto backend/data)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Lista las tablas registradas y termina",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    motor = _motor(args.data_dir)

    if args.list:
        print("Tablas registradas:")
        for info in motor.tables():
            print(
                f"  {info['name']:<16} {info['storage_kind']:<11} "
                f"filas={info['row_count']:<6} "
                f"columnas={[col for col, _ in info['schema']['columnas']]}"
            )
        return 0

    if not args.table or not args.file:
        print("Se requieren --table y --file (o usa --list)", file=sys.stderr)
        return 2

    if args.sql:
        resultado = motor.run(args.sql)
        print(f"SQL: {args.sql}")
        if not resultado.success:
            print(f"  ERROR: {resultado.error}", file=sys.stderr)
            return 1
        print(f"  ok ({resultado.statement})")

    reporte = motor.import_csv(
        args.table,
        args.file,
        has_header=not args.no_headers,
        delimiter=args.delimiter,
        encoding=args.encoding,
        allow_path=True,
    )

    print(f"\nImportación en '{reporte.table}'")
    print(f"  columnas mapeadas : {', '.join(reporte.columns)}")
    print(f"  filas leídas      : {reporte.rows_read}")
    print(f"  insertadas        : {reporte.inserted}")
    print(f"  rechazadas        : {reporte.failed}")
    for error in reporte.errors:
        print(f"    - {error}")

    return 0 if reporte.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
