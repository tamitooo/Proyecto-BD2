"""
Demo end-to-end de la **Parte 1: Base de Datos Relacional (Tablas y SQL)**.

Usa el **ejecutor oficial** (``query/query_executor.py``), el mismo que atiende
el API REST y la interfaz, de modo que lo que se ve aquí es exactamente lo que
hace el motor en la demo web:

    1. Almacenamiento físico   -> Heap File y Archivo Secuencial Paginado
    2. Indexación              -> B+ agrupado, B+ no agrupado, Hash Extendible
    3. Algoritmos externos     -> External Sort (ORDER BY)
                                  External Hashing (GROUP BY y JOIN)
    4. Procesamiento SQL       -> parser + planner + ejecutor
    5. Plan de ejecución       -> se imprime el plan elegido por consulta
    6. Transacciones           -> BEGIN / ROLLBACK / END TRANSACTION

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

from operators.external_hashing import ExternalHashing  # noqa: E402
from operators.external_sort import ExternalSort  # noqa: E402
from query.catalog import Catalog  # noqa: E402
from query.query_executor import QueryExecutor  # noqa: E402

ALUMNOS = [
    (1, "Ana", 18.5, "CS"),
    (2, "Luis", 12.0, "CS"),
    (3, "Marta", 15.5, "DS"),
    (4, "Ivan", 9.5, "DS"),
    (5, "Rosa", 19.0, "CS"),
    (6, "Hugo", 14.0, "IA"),
]
MATRICULAS = [
    (100, 1, "CS101"),
    (101, 1, "CS102"),
    (102, 2, "CS101"),
    (103, 3, "DS201"),
    (104, 6, "IA301"),
    (105, 99, "XX999"),
]


def titulo(texto):
    print()
    print("=" * 78)
    print(texto)
    print("=" * 78)


def mostrar(executor, sql, *, filas=8):
    """Ejecuta una sentencia e imprime filas, plan y tiempo."""
    print(f"\nSQL> {sql}")
    resultado = executor.execute(sql)
    if not resultado.success:
        print(f"  ERROR: {resultado.error}")
        return resultado
    for fila in resultado.rows[:filas]:
        print("  ", dict(fila))
    if len(resultado.rows) > filas:
        print(f"   ... ({len(resultado.rows)} filas en total)")
    plan = resultado.execution_plan or {}
    if plan:
        pasos = " -> ".join(paso["operator"] for paso in plan.get("steps", []))
        print(f"  plan: {plan.get('access_path')}  [{pasos}]")
        usados = plan.get("used_indexes") or []
        if usados:
            print(f"  índices: {', '.join(usados)}")
    print(f"  tiempo: {resultado.execution_time_ms:.3f} ms · filas: {resultado.affected_rows}")
    return resultado


def preparar(executor, almacenamiento):
    using = "SEQUENTIAL" if almacenamiento == "sequential" else "HEAP"
    for sql in (
        "CREATE TABLE alumnos (id INT PRIMARY KEY, nombre VARCHAR(20), "
        f"nota FLOAT, carrera VARCHAR(10)) USING {using}",
        "CREATE TABLE matriculas (matricula INT PRIMARY KEY, id_alumno INT, "
        f"curso VARCHAR(10)) USING {using}",
    ):
        executor.execute(sql, raise_on_error=True)
    for fila in ALUMNOS:
        executor.execute(
            f"INSERT INTO alumnos VALUES ({fila[0]}, '{fila[1]}', {fila[2]}, '{fila[3]}')",
            raise_on_error=True,
        )
    for fila in MATRICULAS:
        executor.execute(
            f"INSERT INTO matriculas VALUES ({fila[0]}, {fila[1]}, '{fila[2]}')",
            raise_on_error=True,
        )


def demo(directorio, almacenamiento):
    titulo(f"PARTE 1 · almacenamiento: {almacenamiento.upper()}")
    catalog = Catalog(data_dir=directorio)
    executor = QueryExecutor(
        catalog,
        # Memoria de 2 registros a propósito: obliga a usar runs y particiones
        # en disco, para que el camino externo se vea en el plan.
        external_sort=ExternalSort(memory_limit_records=2, temp_dir=directorio),
        external_hashing=ExternalHashing(memory_limit_records=2, temp_dir=directorio),
    )
    preparar(executor, almacenamiento)

    tabla = catalog.get_table("alumnos")
    print("Archivos físicos:")
    for nombre in sorted(os.listdir(directorio)):
        if nombre.startswith(("alumnos", "matriculas")):
            ruta = os.path.join(directorio, nombre)
            print(f"   {nombre:<24} {os.path.getsize(ruta):>8} bytes")
    print(f"Registro de tamaño fijo: {tabla.schema.record_size} bytes")

    titulo("Índices: Hash (PK automático), B+ no agrupado y B+ agrupado")
    mostrar(executor, "CREATE INDEX idx_alumnos_nota ON alumnos (nota) USING BPLUS_UNCLUSTERED")
    mostrar(executor, "CREATE INDEX idx_alumnos_carrera ON alumnos (carrera) USING BPLUS_CLUSTERED")
    print("\n(Se espera un error: la clase indica que sólo puede existir UN índice")
    print(" agrupado por tabla, porque los datos tienen un único orden.)")
    mostrar(executor, "CREATE INDEX idx_otro ON alumnos (nombre) USING BPLUS_CLUSTERED")

    titulo("Consultas: el planner elige la ruta de acceso")
    mostrar(executor, "SELECT * FROM alumnos WHERE id = 4")
    mostrar(executor, "SELECT * FROM alumnos WHERE nota BETWEEN 12 AND 16")
    mostrar(executor, "SELECT * FROM alumnos ORDER BY carrera")
    mostrar(executor, "SELECT * FROM alumnos ORDER BY id DESC")
    mostrar(executor, "SELECT * FROM alumnos WHERE nombre = 'Ana'")

    titulo("Algoritmos externos: GROUP BY y JOIN con External Hashing")
    mostrar(executor, "SELECT carrera, COUNT(*) AS total FROM alumnos GROUP BY carrera")
    mostrar(
        executor,
        "SELECT alumnos.nombre, matriculas.curso FROM alumnos "
        "JOIN matriculas ON alumnos.id = matriculas.id_alumno",
    )
    estadisticas = executor.external_sort.last_stats
    print(
        f"\nÚltimo External Sort: {estadisticas.initial_runs} runs iniciales, "
        f"{estadisticas.merge_passes} pasadas de k-way merge, "
        f"{estadisticas.temporary_files} archivos temporales"
    )

    titulo("Transacciones: ROLLBACK deshace los cambios")
    mostrar(executor, "BEGIN TRANSACTION")
    mostrar(executor, "DELETE FROM alumnos WHERE carrera = 'CS'")
    mostrar(executor, "SELECT * FROM alumnos")
    mostrar(executor, "ROLLBACK")
    mostrar(executor, "SELECT * FROM alumnos WHERE carrera = 'CS'")

    titulo("EXPLAIN ANALYZE")
    mostrar(executor, "EXPLAIN ANALYZE SELECT * FROM alumnos WHERE nota >= 15 ORDER BY nota")


def main():
    parser = argparse.ArgumentParser(description="Demo end-to-end de la Parte 1")
    parser.add_argument("--dir", help="carpeta donde dejar los archivos de datos")
    args = parser.parse_args()

    for almacenamiento in ("heap", "sequential"):
        if args.dir:
            directorio = os.path.join(args.dir, almacenamiento)
            shutil.rmtree(directorio, ignore_errors=True)
            os.makedirs(directorio, exist_ok=True)
            demo(directorio, almacenamiento)
        else:
            with tempfile.TemporaryDirectory() as directorio:
                demo(directorio, almacenamiento)


if __name__ == "__main__":
    main()
