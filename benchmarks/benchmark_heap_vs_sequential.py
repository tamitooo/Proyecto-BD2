"""
Benchmark reproducible: **Heap File vs Archivo Secuencial Paginado**.

Cubre la comparación experimental pedida en la Parte 1 del proyecto
(sección 2.1.6 "Gestión de Archivos"):

- tiempo de inserción (1 000 / 10 000 / 100 000 registros)
- tiempo de búsqueda por clave primaria (aciertos y fallos)
- espacio en disco utilizado y espacio desperdiciado
- tiempo de reorganización (solo aplica al Archivo Secuencial)

Metodología
-----------
1. **Inserción real**: se insertan los registros uno a uno usando la API
   pública (`HeapFile.insert` / `SequentialFile.insert`). Es la medición
   fiel, pero su costo crece con el tamaño; por eso está limitada por
   `--mutation-limit` (por defecto 10 000). Para tamaños mayores se
   reporta `supported=False` en lugar de inventar un número.
2. **Carga masiva (bulk load)**: se genera el archivo en disco con el
   mismo layout binario que produce la inserción uno a uno, escribiendo
   página por página. Se usa para habilitar las métricas de búsqueda y de
   espacio en 100 000 registros. La equivalencia byte a byte con la ruta
   real de inserción está cubierta por
   `tests/test_benchmark_heap_vs_sequential.py`.
3. **Búsqueda**: se eligen claves existentes y claves inexistentes al
   azar (semilla fija). El Heap File no tiene índice: su búsqueda por
   clave primaria es un *full scan* con corte temprano. El Archivo
   Secuencial usa búsqueda binaria en `.main` y barrido lineal en `.aux`.
4. **Calibración de E/S**: se mide el costo base de un `read` y de un
   `write` de 43 bytes. Sirve para interpretar los resultados en
   cualquier host (si el host tiene escrituras lentas, los tiempos de
   inserción se inflan proporcionalmente y la comparación *relativa*
   sigue siendo válida).

Los resultados se exportan a CSV y JSON para alimentar las gráficas
(`benchmarks/generate_charts.py`) sin depender de librerías externas.
"""

import argparse
import csv
import json
import math
import os
import pickle
import platform
import random
import shutil
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Permite ejecutarlo tanto como modulo (`python -m benchmarks...`) como
# script directo (`python benchmarks/...`).
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage.heap_file import PAGE_SIZE, HeapFile
from storage.record import Schema
from storage.sequential_file import SequentialFile


# ----------------------------------------------------------------------
# Configuración
# ----------------------------------------------------------------------


DEFAULT_SCHEMA = Schema(
    [
        ("id", "INT"),
        ("nombre", "VARCHAR(30)"),
        ("nota", "FLOAT"),
    ],
    primary_key="id",
)


@dataclass
class StorageBenchmarkResult:
    dataset_size: int
    storage_type: str
    metric: str
    supported: bool
    operations: int
    total_ms: Optional[float] = None
    avg_us: Optional[float] = None
    median_us: Optional[float] = None
    p95_us: Optional[float] = None
    result_items: Optional[int] = None
    size_bytes: Optional[int] = None
    notes: str = ""


@dataclass
class StorageBenchmarkConfig:
    sizes: List[int]
    seed: int = 42
    search_queries: int = 200
    mutation_limit: int = 10_000
    delete_fraction: float = 0.30
    work_dir: str = ""


# ----------------------------------------------------------------------
# Utilidades de medición
# ----------------------------------------------------------------------


def _percentile(values: Sequence[int], percentile: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    index = max(
        0,
        min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1),
    )
    return ordered[index] / 1_000.0


def _timing_summary(
    durations_ns: Sequence[int],
    result_items: Optional[int] = None,
) -> Dict[str, Any]:
    total_ns = sum(durations_ns)

    return {
        "total_ms": total_ns / 1_000_000.0,
        "avg_us": (
            statistics.fmean(durations_ns) / 1_000.0
            if durations_ns
            else 0.0
        ),
        "median_us": (
            statistics.median(durations_ns) / 1_000.0
            if durations_ns
            else 0.0
        ),
        "p95_us": _percentile(durations_ns, 0.95),
        "result_items": result_items,
    }


def _register(
    results: List[StorageBenchmarkResult],
    size: int,
    storage_type: str,
    metric: str,
    durations_ns: Sequence[int],
    result_items: Optional[int] = None,
    size_bytes: Optional[int] = None,
    notes: str = "",
    operations: Optional[int] = None,
    supported: bool = True,
):
    summary = _timing_summary(durations_ns, result_items)

    results.append(
        StorageBenchmarkResult(
            dataset_size=size,
            storage_type=storage_type,
            metric=metric,
            supported=supported,
            operations=(
                operations
                if operations is not None
                else len(durations_ns)
            ),
            total_ms=summary["total_ms"],
            avg_us=summary["avg_us"],
            median_us=summary["median_us"],
            p95_us=summary["p95_us"],
            result_items=summary["result_items"],
            size_bytes=size_bytes,
            notes=notes,
        )
    )


def _register_unsupported(
    results: List[StorageBenchmarkResult],
    size: int,
    storage_type: str,
    metric: str,
    notes: str,
    operations: int = 0,
):
    results.append(
        StorageBenchmarkResult(
            dataset_size=size,
            storage_type=storage_type,
            metric=metric,
            supported=False,
            operations=operations,
            notes=notes,
        )
    )


def _measure_io_baseline(work_dir: str, record_size: int) -> Dict[str, float]:
    """Costo base de un read y de un write del tamaño de registro usado."""
    path = os.path.join(work_dir, "io_baseline.bin")
    payload = b"\x00" * record_size

    with open(path, "wb") as handle:
        handle.write(payload * 100)

    repeats = 200
    read_ns = []
    write_ns = []

    # Calentamiento: evita medir el costo de la primera apertura del archivo.
    for _ in range(20):
        with open(path, "rb") as handle:
            handle.seek(0)
            handle.read(record_size)
        with open(path, "r+b") as handle:
            handle.seek(0)
            handle.write(payload)

    for _ in range(repeats):
        start = time.perf_counter_ns()
        with open(path, "rb") as handle:
            handle.seek(0)
            handle.read(record_size)
        read_ns.append(time.perf_counter_ns() - start)

        start = time.perf_counter_ns()
        with open(path, "r+b") as handle:
            handle.seek(0)
            handle.write(payload)
        write_ns.append(time.perf_counter_ns() - start)

    os.remove(path)

    return {
        "read_open_close_us": statistics.median(read_ns) / 1_000.0,
        "write_open_close_us": statistics.median(write_ns) / 1_000.0,
        "read_mean_us": statistics.fmean(read_ns) / 1_000.0,
        "write_mean_us": statistics.fmean(write_ns) / 1_000.0,
        "record_size_bytes": float(record_size),
    }


# ----------------------------------------------------------------------
# Datos y constructores de archivos
# ----------------------------------------------------------------------


def _make_dataset(size: int, seed: int) -> List[dict]:
    """Mismo dataset (mismos ids y mismo orden de inserción) para ambas técnicas."""
    records = [
        {
            "id": i,
            "nombre": f"registro-{i:08d}",
            "nota": float(i % 1000) + 0.5,
        }
        for i in range(size)
    ]

    random.Random(seed + size).shuffle(records)
    return records


def _empty_record(schema: Schema) -> bytes:
    return schema.pack(
        {field.name: _default_value(field) for field in schema.fields},
        flag=schema.FLAG_EMPTY,
    )


def _default_value(field) -> Any:
    return 0 if field.kind in ("INT", "FLOAT") else ""


def bulk_build_heap(path: str, records: Sequence[dict], schema: Schema) -> None:
    """
    Construye un Heap File equivalente al de `insert` en orden de llegada:
    páginas de tamaño fijo llenas secuencialmente y `.free` con las páginas
    que aún tienen slots libres (a lo sumo la última).
    """
    slots_per_page = max(1, PAGE_SIZE // schema.record_size)
    empty = _empty_record(schema)

    buffer = bytearray()
    free_pages = set()

    for page_index, start in enumerate(range(0, len(records), slots_per_page)):
        chunk = records[start : start + slots_per_page]

        for record in chunk:
            buffer += schema.pack(record, flag=schema.FLAG_USED)

        free_slots = slots_per_page - len(chunk)
        if free_slots > 0:
            buffer += empty * free_slots
            free_pages.add(page_index)

    with open(path, "wb") as handle:
        handle.write(buffer)

    with open(path + ".free", "wb") as handle:
        pickle.dump(free_pages, handle)


def bulk_build_sequential(
    path: str,
    records: Sequence[dict],
    schema: Schema,
) -> None:
    """
    Construye un Archivo Secuencial Paginado equivalente al estado
    post-reorganización: `.main` ordenado por clave primaria y `.aux` vacío.
    """
    ordered = sorted(records, key=lambda record: record[schema.primary_key])

    buffer = bytearray()
    for record in ordered:
        buffer += schema.pack(record, flag=schema.FLAG_USED)

    with open(path + ".main", "wb") as handle:
        handle.write(buffer)

    open(path + ".aux", "wb").close()


def _heap_lookup(heap: HeapFile, key: int) -> Tuple[Optional[Any], Optional[dict]]:
    """Búsqueda por clave primaria en un Heap File: full scan con corte temprano."""
    for rid, values in heap.scan():
        if values["id"] == key:
            return rid, values
    return None, None


# ----------------------------------------------------------------------
# Métricas por técnica
# ----------------------------------------------------------------------


def _measure_heap(
    results: List[StorageBenchmarkResult],
    size: int,
    records: Sequence[dict],
    config: StorageBenchmarkConfig,
    schema: Schema,
    work_dir: str,
):
    path = os.path.join(work_dir, f"heap_{size}.dat")
    rng = random.Random(config.seed + size)

    # ------------------------- inserción real -------------------------
    if size <= config.mutation_limit:
        heap = HeapFile(path, schema)
        durations = []

        for record in records:
            start = time.perf_counter_ns()
            heap.insert(record)
            durations.append(time.perf_counter_ns() - start)

        _register(
            results,
            size,
            "heap_file",
            "insert",
            durations,
            size_bytes=os.path.getsize(path),
            notes="Insercion una a una con reutilizacion de espacio libre.",
        )
    else:
        heap = HeapFile(path, schema)
        durations = []
        _register(
            results,
            size,
            "heap_file",
            "insert",
            durations,
            supported=False,
            operations=size,
            notes=(
                "No medido: la insercion uno a uno a esta escala excede el "
                "presupuesto del benchmark en este host (ver --mutation-limit)."
            ),
        )

    # ------------------------- carga masiva -------------------------
    bulk_path = os.path.join(work_dir, f"heap_bulk_{size}.dat")
    start = time.perf_counter_ns()
    bulk_build_heap(bulk_path, records, schema)
    bulk_ns = time.perf_counter_ns() - start

    bulk_heap = HeapFile(bulk_path, schema)
    scanned = sum(1 for _ in bulk_heap.scan())
    assert scanned == len(records), (
        f"bulk heap inconsistente: {scanned} != {len(records)}"
    )

    _register(
        results,
        size,
        "heap_file",
        "bulk_load",
        [bulk_ns],
        result_items=scanned,
        size_bytes=os.path.getsize(bulk_path),
        notes="Construccion directa pagina a pagina (mismo layout binario).",
    )

    # ------------------------- búsquedas -------------------------
    query_count = min(config.search_queries, size)
    existing = rng.sample(range(size), query_count)
    missing = [size + 1_000_000 + i for i in range(query_count)]

    durations = []
    hits = 0
    for key in existing:
        start = time.perf_counter_ns()
        rid, values = _heap_lookup(bulk_heap, key)
        durations.append(time.perf_counter_ns() - start)
        if values is not None:
            hits += 1

    _register(
        results,
        size,
        "heap_file",
        "search_hit",
        durations,
        result_items=hits,
        notes="Full scan con corte temprano (no existe indice de clave primaria).",
    )

    durations = []
    for key in missing:
        start = time.perf_counter_ns()
        _heap_lookup(bulk_heap, key)
        durations.append(time.perf_counter_ns() - start)

    _register(
        results,
        size,
        "heap_file",
        "search_miss",
        durations,
        result_items=0,
        notes="Full scan completo: recorre todas las paginas.",
    )

    # ------------------------- espacio en disco -------------------------
    allocated = os.path.getsize(bulk_path)
    useful = len(records) * schema.record_size

    _register(
        results,
        size,
        "heap_file",
        "disk_space",
        [],
        operations=0,
        size_bytes=allocated,
        notes=f"Util={useful} bytes.",
    )

    _register(
        results,
        size,
        "heap_file",
        "wasted_space",
        [],
        operations=0,
        size_bytes=max(0, allocated - useful),
        notes=(
            "Slots libres de la ultima pagina (el archivo crece en paginas "
            f"de {PAGE_SIZE} bytes)."
        ),
    )

    # ------------------------- borrado + reutilización -------------------------
    if size <= config.mutation_limit:
        mutation = max(1, int(size * config.delete_fraction))
        delete_keys = rng.sample(range(size), mutation)

        durations = []
        deleted = 0
        freed_rids = []
        for key in delete_keys:
            rid, _values = _heap_lookup(heap, key)
            start = time.perf_counter_ns()
            if rid is not None and heap.delete(rid):
                deleted += 1
                freed_rids.append(rid)
            durations.append(time.perf_counter_ns() - start)

        _register(
            results,
            size,
            "heap_file",
            "delete",
            durations,
            result_items=deleted,
            notes="Eliminacion logica (tombstone) + alta de la pagina al free-list.",
        )

        # reinserción: ¿reutiliza el espacio liberado?
        reused = 0
        durations = []
        freed = set(freed_rids)
        for i in range(deleted):
            record = {
                "id": size + 1_000_000 + i,
                "nombre": f"reuso-{i:08d}",
                "nota": 1.0,
            }
            start = time.perf_counter_ns()
            rid = heap.insert(record)
            durations.append(time.perf_counter_ns() - start)
            if rid in freed:
                reused += 1

        _register(
            results,
            size,
            "heap_file",
            "reuse_insert",
            durations,
            result_items=reused,
            notes=(
                "Inserciones posteriores al borrado; "
                f"{reused}/{deleted} reutilizaron un slot liberado."
            ),
        )

        _register_unsupported(
            results,
            size,
            "heap_file",
            "reorganize",
            notes=(
                "No aplica: el Heap File no reorganiza, reutiliza espacio "
                "libre en linea mediante el free-list."
            ),
        )
    else:
        _register_unsupported(
            results,
            size,
            "heap_file",
            "delete",
            notes="No medido a esta escala (ver --mutation-limit).",
        )
        _register_unsupported(
            results,
            size,
            "heap_file",
            "reorganize",
            notes="No aplica: el Heap File no reorganiza.",
        )


def _measure_sequential(
    results: List[StorageBenchmarkResult],
    size: int,
    records: Sequence[dict],
    config: StorageBenchmarkConfig,
    schema: Schema,
    work_dir: str,
):
    path = os.path.join(work_dir, f"seq_{size}.dat")
    rng = random.Random(config.seed + size)

    # ------------------------- inserción real -------------------------
    if size <= config.mutation_limit:
        sequential = SequentialFile(path, schema)
        durations = []

        for record in records:
            start = time.perf_counter_ns()
            sequential.insert(record)
            durations.append(time.perf_counter_ns() - start)

        reorgs = sequential.n_reorganizaciones
        _register(
            results,
            size,
            "archivo_secuencial",
            "insert",
            durations,
            size_bytes=(
                os.path.getsize(sequential.main_path)
                + os.path.getsize(sequential.aux_path)
            ),
            notes=(
                "Insercion en .aux + reorganizacion automatica al superar el "
                f"30% (reorganizaciones durante la carga: {reorgs})."
            ),
        )
    else:
        sequential = SequentialFile(path, schema)
        _register(
            results,
            size,
            "archivo_secuencial",
            "insert",
            [],
            supported=False,
            operations=size,
            notes=(
                "No medido: la insercion uno a uno a esta escala excede el "
                "presupuesto del benchmark en este host (ver --mutation-limit)."
            ),
        )

    # ------------------------- carga masiva -------------------------
    bulk_path = os.path.join(work_dir, f"seq_bulk_{size}.dat")
    start = time.perf_counter_ns()
    bulk_build_sequential(bulk_path, records, schema)
    bulk_ns = time.perf_counter_ns() - start

    bulk_sequential = SequentialFile(bulk_path, schema)
    scanned = sum(1 for _ in bulk_sequential.scan())
    assert scanned == len(records), (
        f"bulk secuencial inconsistente: {scanned} != {len(records)}"
    )

    _register(
        results,
        size,
        "archivo_secuencial",
        "bulk_load",
        [bulk_ns],
        result_items=scanned,
        size_bytes=(
            os.path.getsize(bulk_sequential.main_path)
            + os.path.getsize(bulk_sequential.aux_path)
        ),
        notes=(
            "Equivale al estado post-reorganizacion: .main ordenado y .aux "
            "vacio."
        ),
    )

    # ------------------------- búsquedas -------------------------
    query_count = min(config.search_queries, size)
    existing = rng.sample(range(size), query_count)
    missing = [size + 1_000_000 + i for i in range(query_count)]

    durations = []
    hits = 0
    for key in existing:
        start = time.perf_counter_ns()
        rid, values = bulk_sequential.search(key)
        durations.append(time.perf_counter_ns() - start)
        if values is not None:
            hits += 1

    _register(
        results,
        size,
        "archivo_secuencial",
        "search_hit",
        durations,
        result_items=hits,
        notes="Busqueda binaria en .main + barrido lineal en .aux (aux vacio).",
    )

    durations = []
    for key in missing:
        start = time.perf_counter_ns()
        bulk_sequential.search(key)
        durations.append(time.perf_counter_ns() - start)

    _register(
        results,
        size,
        "archivo_secuencial",
        "search_miss",
        durations,
        result_items=0,
        notes=(
            "Busqueda binaria sin exito + barrido de .aux para descartar "
            "duplicados en overflow."
        ),
    )

    # ------------------------- espacio en disco -------------------------
    allocated = (
        os.path.getsize(bulk_sequential.main_path)
        + os.path.getsize(bulk_sequential.aux_path)
    )
    useful = len(records) * schema.record_size

    _register(
        results,
        size,
        "archivo_secuencial",
        "disk_space",
        [],
        operations=0,
        size_bytes=allocated,
        notes=(
            f"Util={useful} bytes; sin desperdicio tras reorganizar "
            f"({allocated - useful} bytes)."
        ),
    )

    # ------------------------- borrado + reorganización -------------------------
    if size <= config.mutation_limit:
        mutation = max(2, int(size * config.delete_fraction) + 1)
        delete_keys = rng.sample(range(size), mutation)

        durations = []
        deleted = 0
        for key in delete_keys:
            start = time.perf_counter_ns()
            if bulk_sequential.delete(key):
                deleted += 1
            durations.append(time.perf_counter_ns() - start)

        reorgs = bulk_sequential.n_reorganizaciones

        _register(
            results,
            size,
            "archivo_secuencial",
            "delete",
            durations,
            result_items=deleted,
            notes=(
                "Eliminacion lazy (tombstone en .main); reorganizaciones "
                f"automaticas disparadas durante el borrado: {reorgs}."
            ),
        )

        # Segunda tanda corta de borrados: deja tombstones (< 30%) para poder
        # cronometrar una reorganizacion sin que el umbral automatico se
        # dispare antes.
        extra = min(size - mutation, max(1, int(size * 0.05)))
        extra_keys = rng.sample(range(size), extra)
        for key in extra_keys:
            bulk_sequential.delete(key)

        wasted = sum(
            1
            for flag, _ in bulk_sequential._leer_todos(
                bulk_sequential.main_path
            )
            if flag == schema.FLAG_DELETED
        ) * schema.record_size

        _register(
            results,
            size,
            "archivo_secuencial",
            "wasted_space",
            [],
            operations=0,
            size_bytes=wasted,
            notes=(
                "Espacio en tombstones justo antes de reorganizar ("
                f"{wasted // schema.record_size} slots borrados)."
            ),
        )

        start = time.perf_counter_ns()
        bulk_sequential.reorganizar()
        reorg_ns = time.perf_counter_ns() - start

        after = (
            os.path.getsize(bulk_sequential.main_path)
            + os.path.getsize(bulk_sequential.aux_path)
        )

        _register(
            results,
            size,
            "archivo_secuencial",
            "reorganize",
            [reorg_ns],
            result_items=deleted + extra,
            size_bytes=after,
            notes=(
                "Reorganizacion cronometrada (compacta tombstones y vacia "
                ".aux)."
            ),
        )
    else:
        _register_unsupported(
            results,
            size,
            "archivo_secuencial",
            "delete",
            notes="No medido a esta escala (ver --mutation-limit).",
        )
        _register_unsupported(
            results,
            size,
            "archivo_secuencial",
            "reorganize",
            notes="No medido a esta escala (ver --mutation-limit).",
        )


# ----------------------------------------------------------------------
# Orquestación y salida
# ----------------------------------------------------------------------


def run_benchmarks(
    config: StorageBenchmarkConfig,
) -> Tuple[List[StorageBenchmarkResult], Dict[str, Any]]:
    schema = DEFAULT_SCHEMA
    work_dir = config.work_dir or os.path.join(
        os.getcwd(),
        ".benchmark_work",
    )
    shutil.rmtree(work_dir, ignore_errors=True)
    os.makedirs(work_dir, exist_ok=True)

    environment = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "record_size_bytes": schema.record_size,
        "page_size_bytes": PAGE_SIZE,
        "slots_per_page": max(1, PAGE_SIZE // schema.record_size),
    }

    environment.update(_measure_io_baseline(work_dir, schema.record_size))

    results: List[StorageBenchmarkResult] = []

    for size in config.sizes:
        if size < 1:
            raise ValueError("los tamanos de dataset deben ser >= 1")

        records = _make_dataset(size, config.seed)

        _measure_heap(results, size, records, config, schema, work_dir)
        _measure_sequential(results, size, records, config, schema, work_dir)

    shutil.rmtree(work_dir, ignore_errors=True)
    return results, environment


def write_csv(results: Sequence[StorageBenchmarkResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(StorageBenchmarkResult.__dataclass_fields__.keys())

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()

        for result in results:
            writer.writerow(asdict(result))


def write_json(
    results: Sequence[StorageBenchmarkResult],
    config: StorageBenchmarkConfig,
    environment: Dict[str, Any],
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "config": asdict(config),
        "environment": environment,
        "results": [asdict(result) for result in results],
    }

    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _print_summary(results: Sequence[StorageBenchmarkResult]) -> None:
    print()
    print("=== Benchmark Heap File vs Archivo Secuencial Paginado ===")
    print()

    for result in results:
        if not result.supported:
            value = "N/A"
        elif result.metric in {"disk_space", "wasted_space"}:
            value = f"{result.size_bytes:,} bytes"
        elif result.avg_us is not None:
            value = f"{result.avg_us:,.3f} us/op"
        else:
            value = "-"

        print(
            f"N={result.dataset_size:<8} "
            f"{result.storage_type:<20} "
            f"{result.metric:<14} "
            f"{value}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark Heap File vs Archivo Secuencial Paginado",
    )

    parser.add_argument(
        "--sizes",
        nargs="+",
        type=int,
        default=[1_000, 10_000, 100_000],
        help="Tamanos de dataset a evaluar",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
    )
    parser.add_argument(
        "--search-queries",
        type=int,
        default=200,
    )
    parser.add_argument(
        "--mutation-limit",
        type=int,
        default=10_000,
        help=(
            "Tamano maximo para el que se miden inserciones/borrados uno a "
            "uno (mas alla se reporta N/A y se usan metricas de carga masiva)"
        ),
    )
    parser.add_argument(
        "--delete-fraction",
        type=float,
        default=0.30,
        help="Fraccion de registros a borrar (umbral de reorganizacion = 0.30)",
    )
    parser.add_argument(
        "--work-dir",
        default="",
        help="Directorio temporal de trabajo (por defecto ./.benchmark_work)",
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark_results",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = StorageBenchmarkConfig(
        sizes=args.sizes,
        seed=args.seed,
        search_queries=args.search_queries,
        mutation_limit=args.mutation_limit,
        delete_fraction=args.delete_fraction,
        work_dir=args.work_dir,
    )

    start = time.perf_counter()
    results, environment = run_benchmarks(config)
    elapsed = time.perf_counter() - start

    output_dir = Path(args.output_dir)
    csv_path = output_dir / "storage_benchmark.csv"
    json_path = output_dir / "storage_benchmark.json"

    write_csv(results, csv_path)
    write_json(results, config, environment, json_path)
    _print_summary(results)

    print()
    print(
        "Calibracion de E/S (host): "
        f"read={environment['read_open_close_us']:.1f} us  "
        f"write={environment['write_open_close_us']:.1f} us"
    )
    print(f"Duracion total: {elapsed:,.1f} s")
    print(f"CSV : {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()
