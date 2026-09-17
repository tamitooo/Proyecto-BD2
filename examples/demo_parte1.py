"""
Demo end-to-end de la **Parte 1: Base de Datos Relacional (Tablas y SQL)**.

Recorre en vivo toda la cadena implementada por el equipo:

    1. Almacenamiento fisico   -> Heap File y Archivo Secuencial Paginado
    2. Indexacion              -> B+ agrupado, B+ no agrupado, Hash Extendible
    3. Algoritmos externos     -> External Sort (ORDER BY)
                                  External Hashing (GROUP BY y JOIN)
    4. Procesamiento SQL       -> parser + planner + ejecutor
    5. Plan de ejecucion       -> se imprime el plan elegido por consulta

Uso:
    python examples/demo_parte1.py
    python examples/demo_parte1.py --dir demo_parte1_data
"""

import argparse
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from query.executor import (  # noqa: E402
    Catalog,
    QueryExecutor,
    TableDefinition,
    clustered_index,
    hash_index,
    unclustered_index,
)
from storage.heap_file import HeapFile  # noqa: E402
from storage.record import Schema  # noqa: E402
from storage.sequential_file import SequentialFile  # noqa: E402


ALUMNOS = Schema(
    [
        ("id", "INT"),
        ("nombre", "VARCHAR(20)"),
        ("nota", "FLOAT"),
        ("carrera", "VARCHAR(10)"),
    ],
    primary_key="id",
)

MATRICULAS = Schema(
    [
        ("matricula", "INT"),
        ("id_alumno", "INT"),
        ("curso", "VARCHAR(10)"),
    ],
    primary_key="matricula",
)

ALUMNOS_DATA = [
    {"id": 1, "nombre": "Ana", "nota": 18.5, "carrera": "CS"},
    {"id": 2, "nombre": "Luis", "nota": 12.0, "carrera": "CS"},
    {"id": 3, "nombre": "Marta", "nota": 15.5, "carrera": "DS"},
    {"id": 4, "nombre": "Ivan", "nota": 9.5, "carrera": "DS"},
    {"id": 5, "nombre": "Rosa", "nota": 19.0, "carrera": "CS"},
    {"id": 6, "nombre": "Hugo", "nota": 14.0, "carrera": "IA"},
]

MATRICULAS_DATA = [
    {"matricula": 100, "id_alumno": 1, "curso": "CS101"},
    {"matricula": 101, "id_alumno": 1, "curso": "CS102"},
    {"matricula": 102, "id_alumno": 2, "curso": "CS101"},
    {"matricula": 103, "id_alumno": 3, "curso": "DS201"},
    {"matricula": 104, "id_alumno": 6, "curso": "IA301"},
    {"matricula": 105, "id_alumno": 99, "curso": "XX999"},
]


def titulo(texto):
    print()
    print("=" * 78)
    print(texto)
    print("=" * 78)


def sub(texto):
    print()
    print(f"--- {texto} " + "-" * max(0, 74 - len(texto)))


def filas(rows, limite=12):
    if not rows:
        print("      (sin resultados)")
        return

    columnas = list(rows[0].keys())
    print("      " + " | ".join(columnas))
    print("      " + "-" * 60)

    for row in rows[:limite]:
        print(
            "      "
            + " | ".join(str(row.get(columna, "")) for columna in columnas)
        )

    if len(rows) > limite:
        print(f"      ... ({len(rows)} filas en total)")


def construir_catalogo(base_dir):
    catalog = Catalog()

    tablas = {}

    for kind, sufijo in (("heap", "h"), ("sequential", "s")):
        path = os.path.join(base_dir, f"alumnos_{sufijo}.dat")

        storage = (
            HeapFile(path, ALUMNOS)
            if kind == "heap"
            else SequentialFile(path, ALUMNOS)
        )

        table = TableDefinition(
            name="alumnos" if kind == "heap" else "alumnos_secuencial",
            schema=ALUMNOS,
            storage=storage,
            storage_kind=kind,
        )
        table.add_index(hash_index("id", bucket_capacity=32))
        table.add_index(unclustered_index("nota", order=16))
        table.add_index(clustered_index("carrera", order=16))

        for record in ALUMNOS_DATA:
            table.insert(record)

        if kind == "sequential":
            table.rebuild_indexes()

        catalog.register(table)
        tablas[kind] = table

    matriculas = TableDefinition(
        name="matriculas",
        schema=MATRICULAS,
        storage=HeapFile(os.path.join(base_dir, "matriculas.dat"), MATRICULAS),
        storage_kind="heap",
    )
    matriculas.add_index(hash_index("matricula", bucket_capacity=32))

    for record in MATRICULAS_DATA:
        matriculas.insert(record)

    catalog.register(matriculas)

    return catalog, tablas


def main():
    parser = argparse.ArgumentParser(description="Demo de la Parte 1")
    parser.add_argument(
        "--dir",
        default="",
        help="Directorio de trabajo (por defecto uno temporal)",
    )
    args = parser.parse_args()

    temporal = None

    if args.dir:
        base_dir = os.path.abspath(args.dir)
        shutil.rmtree(base_dir, ignore_errors=True)
        os.makedirs(base_dir, exist_ok=True)
    else:
        temporal = tempfile.TemporaryDirectory()
        base_dir = temporal.name

    titulo("MiniGestor de Base de Datos Multimodal - Demo Parte 1 (Relacional)")
    print(f"Directorio de datos: {base_dir}")

    catalog, tablas = construir_catalogo(base_dir)
    executor = QueryExecutor(catalog, memory_limit_records=4, temp_dir=base_dir)

    # ------------------------------------------------------------------
    sub("1. Almacenamiento fisico y espacio en disco")
    for kind, table in tablas.items():
        print(f"  {table.name:<22} storage={kind:<11} "
              f"bytes={table.storage.espacio_utilizado_bytes():,}")

    # ------------------------------------------------------------------
    sub("2. SELECT con WHERE de igualdad -> indice Hash Extendible")
    resultado = executor.execute_sql("SELECT * FROM alumnos WHERE id = 3")
    print(resultado.explain())
    filas(resultado.rows)

    # ------------------------------------------------------------------
    sub("3. SELECT con rango -> B+ no agrupado")
    resultado = executor.execute_sql(
        "SELECT * FROM alumnos WHERE nota >= 15"
    )
    print(resultado.explain())
    filas(resultado.rows)

    # ------------------------------------------------------------------
    sub("4. ORDER BY -> External Sort (no hay indice que lo cubra)")
    resultado = executor.execute_sql(
        "SELECT nombre, nota FROM alumnos ORDER BY nota DESC"
    )
    print(resultado.explain())
    filas(resultado.rows)

    # ------------------------------------------------------------------
    sub("5. ORDER BY cubierto por el B+ agrupado (sin External Sort)")
    resultado = executor.execute_sql(
        "SELECT nombre, carrera FROM alumnos ORDER BY carrera"
    )
    print(resultado.explain())
    filas(resultado.rows)

    # ------------------------------------------------------------------
    sub("6. GROUP BY -> External Hashing")
    resultado = executor.execute_sql(
        "SELECT carrera, COUNT(*), SUM(nota) FROM alumnos GROUP BY carrera"
    )
    print(resultado.explain())
    filas(resultado.rows)

    # ------------------------------------------------------------------
    sub("7. JOIN -> Grace Hash Join")
    resultado = executor.execute_sql(
        "SELECT nombre, curso FROM alumnos "
        "JOIN matriculas ON alumnos.id = matriculas.id_alumno"
    )
    print(resultado.explain())
    filas(resultado.rows)
    print(f"      estadisticas del join: {resultado.stats.get('join')}")

    # ------------------------------------------------------------------
    sub("8. Las mismas consultas sobre Archivo Secuencial Paginado")
    for sql in (
        "SELECT * FROM alumnos_secuencial WHERE id = 3",
        "SELECT * FROM alumnos_secuencial WHERE nota >= 15",
        "SELECT carrera, COUNT(*) FROM alumnos_secuencial GROUP BY carrera",
    ):
        resultado = executor.execute_sql(sql)
        print(f"  SQL: {sql}")
        print(f"       acceso={resultado.stats['access_path']} "
              f"filas={len(resultado.rows)}")

    # ------------------------------------------------------------------
    sub("9. INSERT y DELETE desde SQL")
    insertado = executor.execute_sql(
        "INSERT INTO alumnos VALUES (7, 'Zoe', 17.0, 'IA')"
    )
    print(f"  INSERT -> {insertado.affected} fila")

    borrado = executor.execute_sql("DELETE FROM alumnos WHERE id = 2")
    print(f"  DELETE -> {borrado.affected} fila(s) afectada(s)")

    print("  Consulta posterior:")
    filas(executor.execute_sql("SELECT * FROM alumnos").rows)

    titulo("Demo finalizada")
    print("Esta demo ejercita: storage + indices + algoritmos externos +")
    print("parser SQL + planner + ejecutor (Parte 1 completa).")
    print()
    print("Resultados experimentales y graficas:")
    print("  benchmark_results/storage_benchmark.json   (Heap vs Secuencial)")
    print("  benchmark_results/index_benchmark.json     (B+ vs Hash)")
    print("  benchmark_results/plots/                   (graficas PNG)")

    if temporal is not None:
        temporal.cleanup()


if __name__ == "__main__":
    main()
