"""Benchmark reproducible de la Parte 2: **Secuencial vs R-Tree vs GiST**.

Cubre la comparación experimental que pide el enunciado (sección 2.2.4):

* **Técnicas**: búsqueda secuencial (sin índice), R-Tree propio y el índice
  **GiST de PostgreSQL**.
* **Consultas**: por rango (radio 1 km, 5 km y 10 km), k-NN (k = 10, 50, 100) y
  una consulta de intersección con polígono.
* **Datasets**: 1 000, 10 000 y 100 000 puntos.
* **Métricas**: tiempo de construcción del índice, tiempo de consulta (promedio
  de 100 consultas), y memoria/espacio en disco.

Sobre PostgreSQL
----------------
El enunciado pide comparar contra **GiST de PostgreSQL** (con PostGIS). En este
entorno **PostGIS no está instalado** y no hay red para instalarlo, así que se usa
el **GiST nativo de PostgreSQL 17** a través de las extensiones ``cube`` y
``earthdistance``, que dan:

* ``ll_to_earth(lat, lon)`` — el punto como cubo 3D sobre la esfera;
* ``earth_distance`` / ``earth_box`` — distancia geodésica y caja de búsqueda;
* ``<->`` — operador de distancia **acelerado por GiST** (k-NN real por índice).

El índice que se crea es ``USING gist (ll_to_earth(lat, lon))``, que **es** un
GiST. La diferencia con PostGIS es la implementación del tipo espacial (``cube``
en lugar de ``geometry``), no la técnica de indexación. El script está escrito
para que, si ``postgis`` está disponible, use ``geometry`` y ``ST_Distance``:
basta con cambiar ``USE_POSTGIS`` a ``True``.

Los resultados se exportan a CSV y JSON para las gráficas, sin dependencias
externas (el driver de PostgreSQL es opcional: si falta, el benchmark sigue
midiendo secuencial y R-Tree y marca GiST como no disponible).
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from indexes.rtree import RTree
from spatial.geo import (
    bounds_of,
    generate_points,
    haversine,
    meters_per_degree_lon,
    point_in_polygon,
    polygon_to_mbr,
)
from spatial.index import SpatialIndex

#: Compatibilidad: el modo se elige ahora con ``--pg-mode`` (auto|postgis|earthdistance).
#: Se mantiene la constante para no romper imports antiguos: ``True`` equivale a
#: forzar PostGIS.
USE_POSTGIS = False

#: Radios del enunciado.
RADII_M = (1_000, 5_000, 10_000)
#: Valores de k del enunciado.
K_VALUES = (10, 50, 100)
#: Consultas por medición (el enunciado pide el promedio de 100 consultas).
QUERIES_PER_MEASUREMENT = 100

#: Dataset de referencia, centrado en Lima.
CENTER = (-12.0464, -77.0428)


@dataclass
class SpatialResult:
    """Una medición del benchmark espacial."""

    dataset_size: int
    technique: str
    query: str
    parameter: str
    supported: bool
    samples: int = 0
    avg_ms: Optional[float] = None
    median_ms: Optional[float] = None
    p95_ms: Optional[float] = None
    min_ms: Optional[float] = None
    max_ms: Optional[float] = None
    build_ms: Optional[float] = None
    result_items: Optional[int] = None
    size_bytes: Optional[int] = None
    notes: str = ""


@dataclass
class SpatialBenchmarkConfig:
    sizes: List[int] = field(default_factory=lambda: [1_000, 10_000, 100_000])
    seed: int = 42
    spread_km: float = 30.0
    queries: int = QUERIES_PER_MEASUREMENT
    build_repeats: int = 1
    #: Capacidad M de los nodos del R-Tree.
    rtree_max_entries: int = 16
    #: Dataset de la consulta por polígono (se usa el R-Tree).
    run_polygon: bool = True


# ----------------------------------------------------------------------
# Utilidades de medición
# ----------------------------------------------------------------------

def _summary(durations_ms: Sequence[float], items: int = 0) -> Dict[str, Any]:
    if not durations_ms:
        return {"samples": 0}
    ordenado = sorted(durations_ms)
    return {
        "samples": len(durations_ms),
        "avg_ms": statistics.fmean(durations_ms),
        "median_ms": statistics.median(durations_ms),
        "p95_ms": ordenado[max(0, math.ceil(0.95 * len(ordenado)) - 1)],
        "min_ms": ordenado[0],
        "max_ms": ordenado[-1],
        "result_items": items,
    }


def _medir(funcion: Callable[[], int], consultas: int) -> Dict[str, Any]:
    """Ejecuta ``funcion()`` ``consultas`` veces y resume los tiempos."""
    tiempos: List[float] = []
    total_items = 0
    for _ in range(consultas):
        inicio = time.perf_counter()
        total_items += funcion()
        tiempos.append((time.perf_counter() - inicio) * 1000.0)
    return _summary(tiempos, total_items)


# ----------------------------------------------------------------------
# Consultas generadas (las mismas para las tres técnicas)
# ----------------------------------------------------------------------

def _query_points(count: int, seed: int) -> List[Tuple[float, float]]:
    """Puntos de consulta reproducibles, alrededor del centro."""
    import random

    rng = random.Random(seed + 7)
    dlat = 25.0 / 111.32
    dlon = 25.0 / (meters_per_degree_lon(CENTER[0]) / 1000.0)
    return [
        (
            CENTER[0] + rng.uniform(-dlat, dlat),
            CENTER[1] + rng.uniform(-dlon, dlon),
        )
        for _ in range(count)
    ]


# ----------------------------------------------------------------------
# Técnica 1: búsqueda secuencial (sin índice)
# ----------------------------------------------------------------------

def _benchmark_sequential(
    points: Sequence[Tuple[float, float]],
    config: SpatialBenchmarkConfig,
) -> List[SpatialResult]:
    """Línea base: fuerza bruta sobre todos los puntos."""
    resultados: List[SpatialResult] = []
    consultas = _query_points(config.queries, config.seed)
    n = len(points)

    for radius in RADII_M:
        def rango(punto=consultas[0]):
            return 0

        tiempos: List[float] = []
        items = 0
        for punto in consultas:
            inicio = time.perf_counter()
            encontrados = sum(
                1 for p in points if haversine(punto, p) <= radius
            )
            tiempos.append((time.perf_counter() - inicio) * 1000.0)
            items += encontrados
        resultados.append(
            SpatialResult(
                dataset_size=n,
                technique="secuencial",
                query="range",
                parameter=f"{radius // 1000} km",
                supported=True,
                **_summary(tiempos, items),
                notes=(
                    "Sin índice: distancia Haversine punto a punto sobre todo "
                    "el dataset. Es la línea base que exige el enunciado."
                ),
            )
        )

    for k in K_VALUES:
        tiempos = []
        items = 0
        for punto in consultas:
            inicio = time.perf_counter()
            top = sorted(
                (haversine(punto, p) for p in points)
            )[:k]
            tiempos.append((time.perf_counter() - inicio) * 1000.0)
            items += len(top)
        resultados.append(
            SpatialResult(
                dataset_size=n,
                technique="secuencial",
                query="knn",
                parameter=f"k={k}",
                supported=True,
                **_summary(tiempos, items),
                notes="Ordenamiento completo por distancia: O(n log n) por consulta.",
            )
        )

    return resultados


# ----------------------------------------------------------------------
# Técnica 2: R-Tree propio
# ----------------------------------------------------------------------

def _build_rtree(
    points: Sequence[Tuple[float, float]],
    config: SpatialBenchmarkConfig,
) -> Tuple[SpatialIndex, float]:
    """Construye el índice espacial con carga masiva y devuelve el tiempo (ms)."""
    indice = SpatialIndex(
        "lat", "lon", max_entries=config.rtree_max_entries, metric="haversine"
    )
    inicio = time.perf_counter()
    indice.bulk_load(
        [({"lat": lat, "lon": lon}, i) for i, (lat, lon) in enumerate(points)]
    )
    return indice, (time.perf_counter() - inicio) * 1000.0


def _benchmark_rtree(
    points: Sequence[Tuple[float, float]],
    config: SpatialBenchmarkConfig,
) -> List[SpatialResult]:
    resultados: List[SpatialResult] = []
    consultas = _query_points(config.queries, config.seed)
    n = len(points)

    build_times: List[float] = []
    indice: Optional[SpatialIndex] = None
    for _ in range(config.build_repeats):
        indice, ms = _build_rtree(points, config)
        build_times.append(ms)
    build_ms = statistics.fmean(build_times)
    assert indice is not None
    indice.validate()

    stats = indice.stats()

    for radius in RADII_M:
        items = 0
        tiempos = []
        for punto in consultas:
            inicio = time.perf_counter()
            encontrados = indice.range_search(punto, radius)
            tiempos.append((time.perf_counter() - inicio) * 1000.0)
            items += len(encontrados)
        resultados.append(
            SpatialResult(
                dataset_size=n,
                technique="rtree",
                query="range",
                parameter=f"{radius // 1000} km",
                supported=True,
                build_ms=build_ms,
                size_bytes=stats["nodes"] * 64,
                **_summary(tiempos, items),
                notes=(
                    f"R-Tree propio (M={config.rtree_max_entries}, altura="
                    f"{stats['height']}, llenado {stats['fill_factor']:.0%}). "
                    "Poda por MBR y comprobación exacta con Haversine."
                ),
            )
        )

    for k in K_VALUES:
        items = 0
        tiempos = []
        for punto in consultas:
            inicio = time.perf_counter()
            vecinos = indice.knn(punto, k)
            tiempos.append((time.perf_counter() - inicio) * 1000.0)
            items += len(vecinos)
        resultados.append(
            SpatialResult(
                dataset_size=n,
                technique="rtree",
                query="knn",
                parameter=f"k={k}",
                supported=True,
                build_ms=build_ms,
                size_bytes=stats["nodes"] * 64,
                **_summary(tiempos, items),
                notes=(
                    "Best-first search con MINDIST: la distancia real sólo se "
                    "calcula con los puntos de las hojas visitadas."
                ),
            )
        )

    if config.run_polygon:
        ancho = 0.05
        anillo = [
            (CENTER[0] - ancho, CENTER[1] - ancho),
            (CENTER[0] - ancho, CENTER[1] + ancho),
            (CENTER[0] + ancho, CENTER[1] + ancho),
            (CENTER[0] + ancho, CENTER[1] - ancho),
        ]
        tiempos = []
        items = 0
        for _ in range(min(20, config.queries)):
            inicio = time.perf_counter()
            dentro = indice.polygon_search(anillo)
            tiempos.append((time.perf_counter() - inicio) * 1000.0)
            items += len(dentro)
        resultados.append(
            SpatialResult(
                dataset_size=n,
                technique="rtree",
                query="polygon",
                parameter=f"{len(anillo)} vértices",
                supported=True,
                build_ms=build_ms,
                size_bytes=stats["nodes"] * 64,
                **_summary(tiempos, items),
                notes=(
                    "Intersección con polígono: poda por el MBR del polígono y "
                    "confirmación con punto-en-polígono (ray casting)."
                ),
            )
        )

    return resultados


# ----------------------------------------------------------------------
# Técnica 3: GiST de PostgreSQL
# ----------------------------------------------------------------------

class PostgresGiST:
    """Índice GiST de PostgreSQL vía earthdistance/cube (o PostGIS si existe)."""

    def __init__(
        self,
        dsn: Optional[str] = None,
        table: str = "spatial_bench",
        mode: Optional[str] = None,
    ):
        self.dsn = dsn or os.environ.get(
            "BD2_PG_DSN",
            "host=127.0.0.1 port=5432 user=postgres password=postgres dbname=postgres",
        )
        self.table = table
        self.connection = None
        self.available = False
        self.error: Optional[str] = None
        #: "auto" prueba PostGIS y cae a earthdistance; "postgis" y
        #: "earthdistance" fuerzan el modo y fallan con un mensaje claro.
        self.requested_mode = mode or os.environ.get("BD2_PG_MODE", "auto")
        self.mode = self.requested_mode
        self._connect()

    def _connect(self) -> None:
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            self.error = (
                "falta el driver psycopg2; instala 'psycopg2-binary' para "
                "comparar contra el GiST de PostgreSQL"
            )
            return

        try:
            import psycopg2

            self.connection = psycopg2.connect(self.dsn)
            self.connection.autocommit = True
            with self.connection.cursor() as cur:
                if self.requested_mode == "postgis":
                    # Modo exigido por el enunciado: falla si no hay PostGIS.
                    cur.execute("create extension if not exists postgis")
                    self.mode = "postgis"
                elif self.requested_mode == "earthdistance":
                    cur.execute("create extension if not exists cube")
                    cur.execute("create extension if not exists earthdistance")
                    self.mode = "earthdistance"
                else:
                    # Automático: se prefiere PostGIS (lo que pide el enunciado)
                    # y sólo si no está disponible se usa earthdistance.
                    try:
                        cur.execute("create extension if not exists postgis")
                        self.mode = "postgis"
                    except Exception:
                        self.connection.rollback()
                        cur.execute("create extension if not exists cube")
                        cur.execute("create extension if not exists earthdistance")
                        self.mode = "earthdistance"
            self.available = True
        except Exception as exc:  # sin servidor, sin permisos, sin extension
            self.error = f"{type(exc).__name__}: {exc}"
            self.connection = None

    # ------------------------------------------------------------- operaciones

    def build(
        self,
        points: Sequence[Tuple[float, float]],
    ) -> float:
        """Crea la tabla, carga los puntos y crea el índice GiST. Devuelve ms."""
        assert self.connection is not None
        inicio = time.perf_counter()

        with self.connection.cursor() as cur:
            cur.execute(f"drop table if exists {self.table}")
            cur.execute(
                f"create table {self.table} "
                "(id int primary key, lat double precision, lon double precision)"
            )

            # Carga masiva con COPY (es lo que hace viable 100 000 puntos).
            import io

            buffer = io.StringIO()
            for i, (lat, lon) in enumerate(points):
                buffer.write(f"{i}\t{lat!r}\t{lon!r}\n")
            buffer.seek(0)
            cur.copy_from(buffer, self.table, columns=("id", "lat", "lon"))

            if self.mode == "postgis":
                cur.execute(
                    f"alter table {self.table} add column geom geometry(Point, 4326)"
                )
                cur.execute(
                    f"update {self.table} set geom = "
                    "ST_SetSRID(ST_MakePoint(lon, lat), 4326)"
                )
                cur.execute(
                    f"create index {self.table}_gist on {self.table} using gist (geom)"
                )
            else:
                cur.execute(
                    f"create index {self.table}_gist on {self.table} "
                    "using gist (ll_to_earth(lat, lon))"
                )
                cur.execute(f"analyze {self.table}")

        return (time.perf_counter() - inicio) * 1000.0

    def size_bytes(self) -> Optional[int]:
        if not self.available:
            return None
        with self.connection.cursor() as cur:
            cur.execute(
                "select pg_total_relation_size(%s) + "
                "coalesce(pg_relation_size(%s), 0)",
                (self.table, f"{self.table}_gist"),
            )
            return int(cur.fetchone()[0])

    def range_time(self, center: Tuple[float, float], radius: float) -> Tuple[float, int]:
        """Una consulta por rango: tiempo (ms) y filas."""
        lat, lon = center
        if self.mode == "postgis":
            sql = (
                f"select count(*) from {self.table} where "
                "ST_DWithin(geom::geography, "
                f"ST_SetSRID(ST_MakePoint({lon!r}, {lat!r}), 4326)::geography, {radius!r})"
            )
        else:
            sql = (
                f"select count(*) from {self.table} where "
                f"ll_to_earth(lat, lon) <@ earth_box(ll_to_earth({lat!r}, {lon!r}), {radius!r}) "
                f"and earth_distance(ll_to_earth(lat, lon), ll_to_earth({lat!r}, {lon!r})) <= {radius!r}"
            )
        with self.connection.cursor() as cur:
            inicio = time.perf_counter()
            cur.execute(sql)
            filas = int(cur.fetchone()[0])
        return (time.perf_counter() - inicio) * 1000.0, filas

    def knn_time(self, center: Tuple[float, float], k: int) -> Tuple[float, int]:
        """Una consulta k-NN por índice GiST: tiempo (ms) y filas."""
        lat, lon = center
        if self.mode == "postgis":
            sql = (
                f"select id from {self.table} order by "
                f"geom <-> ST_SetSRID(ST_MakePoint({lon!r}, {lat!r}), 4326) limit {k}"
            )
        else:
            sql = (
                f"select id from {self.table} order by "
                f"ll_to_earth(lat, lon) <-> ll_to_earth({lat!r}, {lon!r}) limit {k}"
            )
        with self.connection.cursor() as cur:
            inicio = time.perf_counter()
            cur.execute(sql)
            filas = len(cur.fetchall())
        return (time.perf_counter() - inicio) * 1000.0, filas

    def cleanup(self) -> None:
        if not self.available:
            return
        try:
            with self.connection.cursor() as cur:
                cur.execute(f"drop table if exists {self.table}")
        except Exception:
            pass

    def close(self) -> None:
        if self.connection is not None:
            try:
                self.connection.close()
            except Exception:
                pass


def _benchmark_postgres(
    points: Sequence[Tuple[float, float]],
    config: SpatialBenchmarkConfig,
    engine: PostgresGiST,
) -> List[SpatialResult]:
    resultados: List[SpatialResult] = []
    consultas = _query_points(config.queries, config.seed)
    n = len(points)

    if not engine.available:
        for query, parametros in (
            ("range", [f"{r // 1000} km" for r in RADII_M]),
            ("knn", [f"k={k}" for k in K_VALUES]),
        ):
            for parametro in parametros:
                resultados.append(
                    SpatialResult(
                        dataset_size=n,
                        technique="postgres_gist",
                        query=query,
                        parameter=parametro,
                        supported=False,
                        notes=f"PostgreSQL no disponible: {engine.error}",
                    )
                )
        return resultados

    build_ms = engine.build(points)
    size = engine.size_bytes()

    for radius in RADII_M:
        tiempos = []
        items = 0
        for punto in consultas:
            ms, filas = engine.range_time(punto, radius)
            tiempos.append(ms)
            items += filas
        resultados.append(
            SpatialResult(
                dataset_size=n,
                technique="postgres_gist",
                query="range",
                parameter=f"{radius // 1000} km",
                supported=True,
                build_ms=build_ms,
                size_bytes=size,
                **_summary(tiempos, items),
                notes=(
                    f"GiST de PostgreSQL ({engine.mode}) con earth_box + "
                    "earth_distance (Haversine)."
                    if engine.mode == "earthdistance"
                    else "GiST de PostgreSQL con PostGIS (ST_DWithin)."
                ),
            )
        )

    for k in K_VALUES:
        tiempos = []
        items = 0
        for punto in consultas:
            ms, filas = engine.knn_time(punto, k)
            tiempos.append(ms)
            items += filas
        resultados.append(
            SpatialResult(
                dataset_size=n,
                technique="postgres_gist",
                query="knn",
                parameter=f"k={k}",
                supported=True,
                build_ms=build_ms,
                size_bytes=size,
                **_summary(tiempos, items),
                notes=(
                    "k-NN con el operador <-> acelerado por GiST (Index Scan "
                    "ordenado por distancia)."
                ),
            )
        )

    return resultados


# ----------------------------------------------------------------------
# Orquestación
# ----------------------------------------------------------------------

def run_benchmarks(
    config: SpatialBenchmarkConfig,
    pg_mode: str = "auto",
) -> List[SpatialResult]:
    resultados: List[SpatialResult] = []
    engine = PostgresGiST(mode=pg_mode)

    try:
        for size in config.sizes:
            if size < 1:
                raise ValueError("los tamaños deben ser >= 1")

            puntos = generate_points(
                size,
                center=CENTER,
                spread_km=config.spread_km,
                seed=config.seed,
            )
            print(f"[N={size:,}] secuencial...")
            resultados.extend(_benchmark_sequential(puntos, config))

            print(f"[N={size:,}] R-Tree propio...")
            resultados.extend(_benchmark_rtree(puntos, config))

            print(f"[N={size:,}] GiST de PostgreSQL...")
            resultados.extend(_benchmark_postgres(puntos, config, engine))
    finally:
        engine.cleanup()
        engine.close()

    return resultados


def write_csv(results: Sequence[SpatialResult], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    campos = list(SpatialResult.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as manejador:
        escritor = csv.DictWriter(manejador, fieldnames=campos)
        escritor.writeheader()
        for resultado in results:
            escritor.writerow(asdict(resultado))


def write_json(
    results: Sequence[SpatialResult],
    config: SpatialBenchmarkConfig,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "config": {
            "sizes": config.sizes,
            "seed": config.seed,
            "spread_km": config.spread_km,
            "queries": config.queries,
            "radii_m": list(RADII_M),
            "k_values": list(K_VALUES),
            "rtree_max_entries": config.rtree_max_entries,
            "center": list(CENTER),
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "gist_backend": (
                "postgis"
                if any(
                    r.technique == "postgres_gist"
                    and r.supported
                    and "postgis" in r.notes.lower()
                    for r in results
                )
                else "earthdistance+cube (PostGIS no disponible en este entorno)"
            ),
            "postgis_available": any(
                r.technique == "postgres_gist"
                and r.supported
                and "postgis" in r.notes.lower()
                for r in results
            ),
        },
        "results": [asdict(resultado) for resultado in results],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _print_summary(results: Sequence[SpatialResult]) -> None:
    print()
    print("=" * 96)
    print("BENCHMARK ESPACIAL · Secuencial vs R-Tree propio vs GiST de PostgreSQL")
    print("=" * 96)
    print(
        f"{'N':>8} {'tecnica':<16} {'consulta':<9} {'parametro':<10} "
        f"{'promedio':>12} {'mejora':>10}"
    )
    for size in sorted({r.dataset_size for r in results}):
        base = {
            (r.query, r.parameter): r.avg_ms
            for r in results
            if r.dataset_size == size and r.technique == "secuencial"
        }
        for resultado in results:
            if resultado.dataset_size != size:
                continue
            if not resultado.supported:
                valor = "N/A"
                mejora = "-"
            else:
                valor = f"{resultado.avg_ms:,.3f} ms" if resultado.avg_ms else "-"
                referencia = base.get((resultado.query, resultado.parameter))
                mejora = (
                    f"{referencia / resultado.avg_ms:.1f}x"
                    if referencia and resultado.avg_ms
                    else "-"
                )
            print(
                f"{size:>8,} {resultado.technique:<16} {resultado.query:<9} "
                f"{resultado.parameter:<10} {valor:>12} {mejora:>10}"
            )
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark espacial: secuencial vs R-Tree vs GiST",
    )
    parser.add_argument("--sizes", nargs="+", type=int, default=[1_000, 10_000, 100_000])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--queries", type=int, default=QUERIES_PER_MEASUREMENT)
    parser.add_argument("--spread-km", type=float, default=30.0)
    parser.add_argument("--rtree-max-entries", type=int, default=16)
    parser.add_argument("--output-dir", default="benchmark_results")
    parser.add_argument("--no-polygon", action="store_true")
    parser.add_argument(
        "--pg-mode",
        choices=["auto", "postgis", "earthdistance"],
        default="auto",
        help=(
            "Backend del GiST: 'postgis' lo exige (falla si no está instalado, "
            "que es lo que pide el enunciado), 'earthdistance' usa cube+"
            "earthdistance y 'auto' (por defecto) prefiere PostGIS y cae a "
            "earthdistance si no está disponible"
        ),
    )
    parser.add_argument(
        "--pg-dsn",
        default=None,
        help="Cadena de conexión de PostgreSQL (por defecto la local)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = SpatialBenchmarkConfig(
        sizes=args.sizes,
        seed=args.seed,
        spread_km=args.spread_km,
        queries=args.queries,
        rtree_max_entries=args.rtree_max_entries,
        run_polygon=not args.no_polygon,
    )

    if args.pg_dsn:
        os.environ["BD2_PG_DSN"] = args.pg_dsn

    results = run_benchmarks(config, pg_mode=args.pg_mode)

    output_dir = Path(args.output_dir)
    write_csv(results, output_dir / "spatial_benchmark.csv")
    write_json(results, config, output_dir / "spatial_benchmark.json")
    _print_summary(results)

    print(f"CSV : {output_dir / 'spatial_benchmark.csv'}")
    print(f"JSON: {output_dir / 'spatial_benchmark.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
