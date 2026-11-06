"""Baseline GIN de PostgreSQL (Parte 3). Uso: ``python -m benchmarks.benchmark_text_gin --pg-dsn "host=localhost user=postgres dbname=bd2_experimentos"``."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import tempfile
import time
from pathlib import Path

from benchmarks.common import write_rows

TABLA = "documentos"
K = 10
REPETICIONES = 3


def _carga(cur, corpus: Path, tabla: str) -> float:
    cur.execute(f"DROP TABLE IF EXISTS {tabla}")
    cur.execute(f"CREATE TABLE {tabla}(id integer primary key, texto text)")

    inicio = time.perf_counter()
    with tempfile.TemporaryFile("w+", encoding="utf-8") as copia:
        with corpus.open(encoding="utf-8") as archivo:
            for linea in archivo:
                doc = json.loads(linea)
                copia.write(f"{doc['id']}\t{doc['texto']}\n")
        copia.seek(0)
        cur.copy_expert(f"COPY {tabla} (id, texto) FROM STDIN", copia)

    return time.perf_counter() - inicio


def _indice(cur, tabla: str, config: str) -> float:
    inicio = time.perf_counter()
    cur.execute(
        f"CREATE INDEX {tabla}_{config}_tsv ON {tabla} "
        f"USING gin (to_tsvector('{config}', texto))"
    )
    return time.perf_counter() - inicio


def _tamanos(cur, tabla: str, config: str) -> tuple[float, float]:
    cur.execute(
        "SELECT pg_total_relation_size(%s), "
        f"pg_relation_size('{tabla}_{config}_tsv')",
        (tabla,),
    )
    tabla_bytes, indice_bytes = cur.fetchone()
    return tabla_bytes / 1048576, indice_bytes / 1048576


def _buscar(cur, tabla: str, config: str, terminos: list[str], k: int = K) -> list[int]:
    consulta = " & ".join(terminos)
    cur.execute(
        f"SELECT id FROM {tabla} "
        f"WHERE to_tsvector('{config}', texto) @@ to_tsquery('{config}', %s) "
        f"ORDER BY ts_rank(to_tsvector('{config}', texto), to_tsquery('{config}', %s)) DESC "
        f"LIMIT {k}",
        (consulta, consulta),
    )
    return [fila[0] for fila in cur.fetchall()]


def _usa_indice(cur, tabla: str, config: str, terminos: list[str]) -> bool:
    consulta = " & ".join(terminos)
    cur.execute(
        f"EXPLAIN SELECT id FROM {tabla} "
        f"WHERE to_tsvector('{config}', texto) @@ to_tsquery('{config}', %s)",
        (consulta,),
    )
    plan = "\n".join(fila[0] for fila in cur.fetchall())
    return "Index Scan" in plan


def medir(cur, n: int, config: str, corpus: Path, banco: dict) -> list[dict]:
    tabla = f"{TABLA}_{n}"
    carga_s = _carga(cur, corpus, tabla)
    indice_s = _indice(cur, tabla, config)
    tabla_mb, indice_mb = _tamanos(cur, tabla, config)

    consultas = banco["consultas"]
    usa_indice = _usa_indice(cur, tabla, config, consultas[0]["terminos"])

    filas = [
        {
            "dataset_size": n,
            "config": config,
            "fase": "construccion",
            "grupo": "-",
            "carga_s": round(carga_s, 3),
            "indice_s": round(indice_s, 3),
            "tabla_mb": round(tabla_mb, 2),
            "indice_mb": round(indice_mb, 2),
            "usa_indice": usa_indice,
        }
    ]

    mediciones = []
    for consulta in consultas:
        inicio = time.perf_counter()
        for _ in range(REPETICIONES):
            obtenidos = _buscar(cur, tabla, config, consulta["terminos"])
        milisegundos = (time.perf_counter() - inicio) / REPETICIONES * 1000
        aciertos = len(set(obtenidos) & set(consulta["relevantes"]))
        mediciones.append(
            {
                "grupo": consulta["grupo"],
                "ms": milisegundos,
                "p10": aciertos / K,
                "r10": aciertos / len(consulta["relevantes"]),
            }
        )

    for grupo in ("una", "tres", "larga", "todas"):
        elegidas = [m for m in mediciones if grupo == "todas" or m["grupo"] == grupo]
        filas.append(
            {
                "dataset_size": n,
                "config": config,
                "fase": "consulta",
                "grupo": grupo,
                "consultas": len(elegidas),
                "p10": round(statistics.fmean(m["p10"] for m in elegidas), 4),
                "r10": round(statistics.fmean(m["r10"] for m in elegidas), 4),
                "consulta_ms": round(statistics.fmean(m["ms"] for m in elegidas), 3),
            }
        )

    return filas


def run(sizes: tuple[int, ...], configs: tuple[str, ...], pg_dsn: str, base) -> list[dict]:
    try:
        import psycopg2
    except Exception as error:
        return [{"fase": "disponibilidad", "nota": f"psycopg2 no disponible: {error}"}]

    conexion = psycopg2.connect(pg_dsn)
    conexion.autocommit = True
    cur = conexion.cursor()

    filas: list[dict] = []
    for n in sizes:
        banco = json.loads((Path(base) / str(n) / "queries.json").read_text(encoding="utf-8"))
        for config in configs:
            filas.extend(medir(cur, n, config, Path(base) / str(n) / "corpus.jsonl", banco))

    cur.close()
    conexion.close()
    return filas


def main() -> None:
    ap = argparse.ArgumentParser(description="Baseline GIN de PostgreSQL para la Parte 3")
    ap.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000, 100000])
    ap.add_argument("--configs", nargs="+", default=["simple", "spanish"])
    ap.add_argument("--pg-dsn", default=os.environ.get("BD2_PG_DSN", ""))
    ap.add_argument("--data", default="data/text")
    ap.add_argument("--output", default="benchmarks/results/text")
    args = ap.parse_args()

    if not args.pg_dsn:
        print("Falta --pg-dsn o la variable BD2_PG_DSN")
        return

    filas = run(tuple(args.sizes), tuple(args.configs), args.pg_dsn, args.data)
    for fila in filas:
        print(fila)

    salida = Path(args.output)
    write_rows(
        filas,
        salida / "gin_benchmark.csv",
        salida / "gin_benchmark.json",
        {"sizes": args.sizes, "configs": args.configs, "k": K, "repeticiones": REPETICIONES},
    )


if __name__ == "__main__":
    main()
