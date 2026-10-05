"""Genera las tablas numéricas del informe **directamente desde los CSV**.

Motivo: en la revisión se encontró que las tablas del informe y las del README
venían de una corrida distinta a la de los CSV/JSON (p. ej. "0.098 ms" en el
informe frente a "0.122 ms" en el CSV). Desde ahora ningún número se escribe a
mano: este script lee

    benchmark_results/storage_benchmark.csv   (Parte 1 · Heap vs Secuencial)
    benchmark_results/index_benchmark.csv     (Parte 1 · B+ / B+ / Hash)
    benchmark_results/spatial_benchmark.csv   (Parte 2 · Secuencial / R-Tree / GiST)

y reemplaza los bloques marcados con

    <!-- BEGIN:AUTO:<nombre> -->  ...  <!-- END:AUTO:<nombre> -->

en ``README.md``, ``docs/parte2_espacial.md`` y ``docs/informe_incremental.md``.
Además escribe ``docs/resultados_experimentales.md`` completo.

Uso (después de correr los benchmarks):

    python -m benchmarks.generate_report_tables
    python -m benchmarks.generate_report_tables --check   # falla si algo está desactualizado
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmark_results"

DOCS_WITH_BLOCKS = [
    ROOT / "README.md",
    ROOT / "docs" / "parte2_espacial.md",
    ROOT / "docs" / "informe_incremental.md",
]
FULL_REPORT = ROOT / "docs" / "resultados_experimentales.md"


# ----------------------------------------------------------------------
# Lectura y formato
# ----------------------------------------------------------------------

def _read(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _env(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("environment") or {}


def _f(value: Optional[str]) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _n(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _ms(value: Optional[float], digits: int = 3) -> str:
    return "—" if value is None else f"{value:,.{digits}f} ms".replace(",", " ")


def _us(value: Optional[float]) -> str:
    if value is None:
        return "—"
    if value >= 1000:
        return f"{value / 1000:,.2f} ms".replace(",", " ")
    return f"{value:,.2f} µs".replace(",", " ")


def _bytes(value: Optional[float]) -> str:
    if value is None:
        return "—"
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.2f} MiB"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value:.0f} B"


def _x(base: Optional[float], other: Optional[float]) -> str:
    if not base or not other:
        return "—"
    return f"{base / other:,.1f}×".replace(",", " ")


def _winner(rtree: Optional[float], gist: Optional[float]) -> str:
    """Quién gana entre R-Tree y GiST y por cuánto (siempre >= 1×)."""
    if not rtree or not gist:
        return "—"
    if rtree <= gist:
        return f"R-Tree {gist / rtree:,.1f}×".replace(",", " ")
    return f"GiST {rtree / gist:,.1f}×".replace(",", " ")


def _table(header: List[str], rows: List[List[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Parte 2 · espacial
# ----------------------------------------------------------------------

class Spatial:
    def __init__(self, rows: List[Dict[str, str]]):
        self.rows = rows
        self.sizes = sorted({int(r["dataset_size"]) for r in rows})

    def get(self, n: int, tech: str, query: str, param: str, field: str = "avg_ms"):
        for r in self.rows:
            if (
                int(r["dataset_size"]) == n
                and r["technique"] == tech
                and r["query"] == query
                and r["parameter"] == param
                and r.get("supported") == "True"
            ):
                return _f(r.get(field))
        return None

    def first(self, n: int, tech: str, field: str):
        for r in self.rows:
            if int(r["dataset_size"]) == n and r["technique"] == tech and r.get(field):
                return _f(r[field])
        return None

    def query_table(self, query: str, param: str) -> str:
        rows = []
        for n in self.sizes:
            seq = self.get(n, "secuencial", query, param)
            rt = self.get(n, "rtree", query, param)
            gi = self.get(n, "postgres_gist", query, param)
            rows.append([
                _n(n), _ms(seq), _ms(rt), _ms(gi), _x(seq, rt), _x(seq, gi), _winner(rt, gi),
            ])
        return _table(
            ["N", "Secuencial", "R-Tree propio", "GiST/PostGIS",
             "R-Tree vs secuencial", "GiST vs secuencial", "Más rápido (R-Tree vs GiST)"],
            rows,
        )

    def full_at(self, n: int) -> str:
        rows = []
        for query, params, label in (
            ("range", ["1 km", "5 km", "10 km"], "Rango"),
            ("knn", ["k=10", "k=50", "k=100"], "k-NN"),
        ):
            for p in params:
                seq = self.get(n, "secuencial", query, p)
                rt = self.get(n, "rtree", query, p)
                gi = self.get(n, "postgres_gist", query, p)
                rows.append([
                    f"{label} {p}", _ms(seq), f"{_ms(rt)} ({_x(seq, rt)})",
                    f"{_ms(gi)} ({_x(seq, gi)})",
                ])
        poly = self.get(n, "rtree", "polygon", "4 vértices")
        rows.append(["Polígono (4 vértices)", "—", _ms(poly), "—"])
        return _table(["Consulta", "Secuencial", "R-Tree propio", "GiST/PostGIS"], rows)

    def build_space_table(self) -> str:
        rows = []
        for n in self.sizes:
            rows.append([
                _n(n),
                _ms(self.first(n, "rtree", "build_ms"), 1),
                _ms(self.first(n, "postgres_gist", "build_ms"), 1),
                _bytes(self.first(n, "rtree", "size_bytes")),
                _bytes(self.first(n, "postgres_gist", "size_bytes")),
                _bytes(self.first(n, "rtree", "memory_bytes")),
                _bytes(self.first(n, "postgres_gist", "table_bytes")),
            ])
        return _table(
            ["N", "Construcción R-Tree", "Construcción GiST",
             "Índice R-Tree (serializado)", "Índice GiST (pg_relation_size)",
             "R-Tree en memoria Python", "Tabla PostgreSQL (contexto)"],
            rows,
        )

    def facts(self) -> List[str]:
        """Frases numéricas calculadas (no escritas a mano)."""
        if not self.sizes:
            return []
        small, big = self.sizes[0], self.sizes[-1]
        mid = self.sizes[1] if len(self.sizes) > 2 else small
        out = []
        rt, gi = self.get(small, "rtree", "range", "1 km"), self.get(small, "postgres_gist", "range", "1 km")
        if rt and gi:
            quien = "más rápido" if rt < gi else "más lento"
            out.append(
                f"Rango 1 km con {_n(small)} puntos: R-Tree {_ms(rt)} vs GiST {_ms(gi)} → "
                f"el R-Tree es {max(rt, gi) / min(rt, gi):.1f}× {quien} que PostGIS."
            )
        filas_mid = self.get(mid, "secuencial", "range", "1 km", "result_items")
        filas_big = self.get(big, "secuencial", "range", "1 km", "result_items")
        for tech, nombre in (("rtree", "R-Tree"), ("postgres_gist", "GiST")):
            a, b = self.get(mid, tech, "range", "1 km"), self.get(big, tech, "range", "1 km")
            if a and b:
                extra = ""
                if filas_mid and filas_big:
                    extra = (
                        f"; los resultados por consulta también crecen "
                        f"{filas_big / filas_mid:.1f}× ({filas_mid / 100:.0f} → {filas_big / 100:.0f})"
                    )
                out.append(
                    f"Escalabilidad del {nombre} (rango 1 km, de {_n(mid)} a {_n(big)} puntos): "
                    f"{_ms(a)} → {_ms(b)} ({b / a:.1f}× más tiempo para 10× datos{extra})."
                )
        a, b = self.get(mid, "rtree", "knn", "k=10"), self.get(big, "rtree", "knn", "k=10")
        if a and b:
            out.append(
                f"Con resultado de tamaño fijo (k-NN k=10) el R-Tree crece de forma sublineal: "
                f"{_ms(a)} → {_ms(b)} ({b / a:.1f}× para 10× datos)."
            )
        s1, s2 = self.get(mid, "secuencial", "range", "1 km"), self.get(big, "secuencial", "range", "1 km")
        if s1 and s2:
            out.append(
                f"Secuencial (rango 1 km) de {_n(mid)} a {_n(big)}: {_ms(s1)} → {_ms(s2)} "
                f"({s2 / s1:.1f}×, lineal en N)."
            )
        k10, k100 = self.get(big, "rtree", "knn", "k=10"), self.get(big, "rtree", "knn", "k=100")
        if k10 and k100:
            out.append(
                f"k-NN del R-Tree con {_n(big)} puntos: k=10 {_ms(k10)} y k=100 {_ms(k100)} "
                f"(apenas cambia con k: O(k log n))."
            )
        g, r = self.get(big, "postgres_gist", "knn", "k=10"), self.get(big, "rtree", "knn", "k=10")
        if g and r:
            out.append(
                f"k-NN k=10 con {_n(big)} puntos: GiST {_ms(g)} vs R-Tree {_ms(r)} → GiST "
                f"{r / g:.0f}× más rápido (C + operador <-> integrado en el optimizador)."
            )
        r10, g10 = self.get(big, "rtree", "range", "10 km"), self.get(big, "postgres_gist", "range", "10 km")
        if r10 and g10:
            out.append(
                f"Rango 10 km con {_n(big)} puntos: R-Tree {_ms(r10)} vs GiST {_ms(g10)} "
                "(con resultados grandes domina el costo de devolver filas, no la búsqueda)."
            )
        sr, sg = self.first(big, "rtree", "size_bytes"), self.first(big, "postgres_gist", "size_bytes")
        if sr and sg:
            out.append(
                f"Espacio con {_n(big)} puntos: R-Tree serializado {_bytes(sr)} "
                f"({sr / big:.1f} B/punto) vs GiST {_bytes(sg)} ({sg / big:.1f} B/punto)."
            )
        return out


# ----------------------------------------------------------------------
# Parte 1 · almacenamiento e índices
# ----------------------------------------------------------------------

class Storage:
    def __init__(self, rows):
        self.rows = rows
        self.sizes = sorted({int(r["dataset_size"]) for r in rows})

    def get(self, n, kind, metric, field="avg_us"):
        for r in self.rows:
            if int(r["dataset_size"]) == n and r["storage_type"] == kind and r["metric"] == metric:
                if r.get("supported") != "True":
                    return None
                return _f(r.get(field))
        return None

    def table(self) -> str:
        rows = []
        for n in self.sizes:
            for kind, label in (("heap_file", "Heap File"), ("archivo_secuencial", "Secuencial")):
                rows.append([
                    _n(n), label,
                    _us(self.get(n, kind, "insert")),
                    _ms(self.get(n, kind, "bulk_load", "total_ms"), 1),
                    _us(self.get(n, kind, "search_hit")),
                    _bytes(self.get(n, kind, "disk_space", "size_bytes")),
                    _us(self.get(n, kind, "delete")),
                    _ms(self.get(n, kind, "reorganize", "total_ms"), 1)
                    if kind == "archivo_secuencial" else "no aplica",
                ])
        return _table(
            ["N", "Técnica", "Inserción (1 a 1, prom.)", "Carga masiva", "Búsqueda por PK",
             "Espacio en disco", "Borrado (prom.)", "Reorganización"],
            rows,
        )

    def insert_limit(self) -> Optional[int]:
        medidos = [n for n in self.sizes if self.get(n, "heap_file", "insert") is not None]
        return max(medidos) if medidos else None


class Indexes:
    LABELS = (
        ("bplus_clustered", "B+ agrupado"),
        ("bplus_unclustered", "B+ no agrupado"),
        ("extendible_hash", "Hash extendible"),
    )

    def __init__(self, rows):
        self.rows = rows
        self.sizes = sorted({int(r["dataset_size"]) for r in rows})

    def get(self, n, kind, metric, field="avg_us"):
        for r in self.rows:
            if int(r["dataset_size"]) == n and r["index_type"] == kind and r["metric"] == metric:
                if r.get("supported") != "True":
                    return None
                return _f(r.get(field))
        return None

    def table(self, n: int) -> str:
        lineal = self.get(n, "linear_scan", "linear_scan")
        metrics: List[Tuple[str, Callable[[str], str]]] = [
            ("Construcción", lambda k: _us(self.get(n, k, "build"))),
            ("Igualdad exacta (hit)", lambda k: _us(self.get(n, k, "exact_hit"))),
            ("Mejora vs búsqueda lineal", lambda k: _x(lineal, self.get(n, k, "exact_hit"))),
            ("Igualdad + traer la fila", lambda k: _us(self.get(n, k, "exact_hit_materialized"))),
            ("Rango + traer la fila", lambda k: _us(self.get(n, k, "range_search_materialized"))
             if self.get(n, k, "range_search_materialized") is not None else "no aplica"),
            ("Recorrido ordenado", lambda k: _us(self.get(n, k, "ordered_scan"))
             if self.get(n, k, "ordered_scan") is not None else "no aplica"),
            ("Inserción (prom.)", lambda k: _us(self.get(n, k, "insert"))),
            ("Borrado (prom.)", lambda k: _us(self.get(n, k, "delete"))),
            ("Espacio adicional", lambda k: _bytes(self.get(n, k, "serialized_size", "size_bytes"))),
        ]
        rows = [[name] + [fn(kind) for kind, _ in self.LABELS] for name, fn in metrics]
        rows.append(["Búsqueda lineal (sin índice)", _us(lineal), "", ""])
        return _table(["Métrica"] + [label for _, label in self.LABELS], rows)

    def scaling(self) -> str:
        rows = []
        for n in self.sizes:
            rows.append([_n(n)] + [_us(self.get(n, k, "exact_hit")) for k, _ in self.LABELS]
                        + [_us(self.get(n, "linear_scan", "linear_scan"))])
        return _table(["N"] + [f"{label} (igualdad)" for _, label in self.LABELS] + ["Lineal"], rows)


# ----------------------------------------------------------------------
# Bloques
# ----------------------------------------------------------------------

def _env_line(path: Path) -> str:
    env = _env(path)
    if not env:
        return ""
    parts = [str(env.get("platform", "")), f"Python {env.get('python', '?')}"]
    if env.get("postgres_server"):
        parts.append(str(env["postgres_server"]))
    return "Entorno de la corrida: " + " · ".join(p for p in parts if p) + "."


def build_blocks() -> Dict[str, str]:
    spatial = Spatial(_read(RESULTS / "spatial_benchmark.csv"))
    storage = Storage(_read(RESULTS / "storage_benchmark.csv"))
    indexes = Indexes(_read(RESULTS / "index_benchmark.csv"))
    fuente = "_Generado por `python -m benchmarks.generate_report_tables` desde `benchmark_results/*.csv`. No editar a mano._"
    blocks: Dict[str, str] = {}

    if spatial.rows:
        big = spatial.sizes[-1]
        hechos = "\n".join(f"- {h}" for h in spatial.facts())
        blocks["parte2_tablas"] = "\n\n".join([
            fuente,
            _env_line(RESULTS / "spatial_benchmark.json"),
            "**Rango (radio 1 km), promedio de 100 consultas**\n\n" + spatial.query_table("range", "1 km"),
            "**Rango (radio 5 km)**\n\n" + spatial.query_table("range", "5 km"),
            "**Rango (radio 10 km)**\n\n" + spatial.query_table("range", "10 km"),
            "**k-NN (k = 10)**\n\n" + spatial.query_table("knn", "k=10"),
            "**k-NN (k = 50)**\n\n" + spatial.query_table("knn", "k=50"),
            "**k-NN (k = 100)**\n\n" + spatial.query_table("knn", "k=100"),
            f"**Todas las consultas con {_n(big)} puntos**\n\n" + spatial.full_at(big),
            "**Tiempo de construcción y espacio del índice**\n\n" + spatial.build_space_table(),
            "**Lectura numérica (calculada del CSV)**\n\n" + hechos,
        ])
        blocks["readme_parte2"] = "\n\n".join([
            fuente,
            spatial.full_at(big),
            "**Construcción y espacio:**\n\n" + spatial.build_space_table(),
            "\n".join(f"- {h}" for h in spatial.facts()[:3]),
        ])

    if storage.rows:
        limite = storage.insert_limit()
        nota = (
            f"Inserción y borrado uno a uno medidos hasta **{_n(limite)}** registros."
            if limite else ""
        )
        blocks["parte1_storage"] = "\n\n".join(
            [fuente, _env_line(RESULTS / "storage_benchmark.json"), nota, storage.table()]
        )
    if indexes.rows:
        n = indexes.sizes[-1]
        blocks["parte1_indices"] = "\n\n".join([
            fuente,
            f"**Comparación con {_n(n)} claves** (tiempos promedio por operación)\n\n" + indexes.table(n),
            "**Escalabilidad de la igualdad exacta**\n\n" + indexes.scaling(),
        ])
    return blocks


_BLOCK_RE = re.compile(
    r"(<!-- BEGIN:AUTO:(?P<name>[a-z0-9_]+) -->)(?P<body>.*?)(<!-- END:AUTO:(?P=name) -->)",
    re.DOTALL,
)


def apply(path: Path, blocks: Dict[str, str]) -> Tuple[str, str]:
    original = path.read_text(encoding="utf-8")

    def repl(match):
        name = match.group("name")
        if name not in blocks:
            return match.group(0)
        return f"{match.group(1)}\n{blocks[name]}\n{match.group(4)}"

    return original, _BLOCK_RE.sub(repl, original)


def full_report(blocks: Dict[str, str]) -> str:
    parts = [
        "# Resultados experimentales (generado)",
        "",
        "Archivo generado automáticamente desde los CSV de `benchmark_results/`. "
        "Las mismas tablas aparecen en el informe y en el README.",
        "",
    ]
    for title, key in (
        ("Parte 1 · Heap File vs Archivo Secuencial Paginado", "parte1_storage"),
        ("Parte 1 · B+ agrupado vs B+ no agrupado vs Hash Extendible", "parte1_indices"),
        ("Parte 2 · Secuencial vs R-Tree vs GiST (PostGIS)", "parte2_tablas"),
    ):
        if key in blocks:
            parts += [f"## {title}", "", blocks[key], ""]
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="no escribe; falla si hay diferencias")
    args = parser.parse_args()

    blocks = build_blocks()
    desactualizados = []
    for path in DOCS_WITH_BLOCKS:
        if not path.exists():
            continue
        original, nuevo = apply(path, blocks)
        if original != nuevo:
            desactualizados.append(path)
            if not args.check:
                path.write_text(nuevo, encoding="utf-8")
                print(f"[ok] {path.relative_to(ROOT)}")
    reporte = full_report(blocks)
    if not FULL_REPORT.exists() or FULL_REPORT.read_text(encoding="utf-8") != reporte:
        desactualizados.append(FULL_REPORT)
        if not args.check:
            FULL_REPORT.write_text(reporte, encoding="utf-8")
            print(f"[ok] {FULL_REPORT.relative_to(ROOT)}")

    if args.check and desactualizados:
        for path in desactualizados:
            print(f"[desactualizado] {path.relative_to(ROOT)}")
        return 1
    if args.check:
        print("Todas las tablas coinciden con los CSV.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
