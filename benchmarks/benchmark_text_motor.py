"""Medicion del motor propio sobre el corpus de la Parte 3.

Corre las mismas 36 consultas y las mismas etiquetas que el baseline de
PostgreSQL. La tokenizacion es la provisional del experimento: minusculas y
separacion por espacios, sin stemming ni stopwords, para quedar al mismo
nivel que la configuracion ``simple`` de Postgres.

El indice que se mide es el que existe hoy: las estadisticas en memoria de
``BM25Statistics``. SPIMI con bloques en disco es otra entrega.
"""

from __future__ import annotations

import argparse
import json
import statistics as medidor
import time
from pathlib import Path

from benchmarks.common import deep_size, write_rows
from text import BM25Ranker, BM25Statistics, TFIDFRanker

K = 10
REPETICIONES = 3


def cargar(corpus: Path) -> tuple[BM25Statistics, float]:
    estadisticas = BM25Statistics()
    inicio = time.perf_counter()
    with corpus.open(encoding="utf-8") as archivo:
        for linea in archivo:
            doc = json.loads(linea)
            estadisticas.add_document(doc["id"], doc["texto"].lower().split())
    return estadisticas, time.perf_counter() - inicio


def medir(n: int, base: Path) -> list[dict]:
    banco = json.loads((base / str(n) / "queries.json").read_text(encoding="utf-8"))
    estadisticas, construccion_s = cargar(base / str(n) / "corpus.jsonl")
    memoria_mb = deep_size(estadisticas) / 1048576

    filas = [
        {
            "dataset_size": n,
            "tecnica": "bm25+tfidf",
            "fase": "construccion",
            "grupo": "-",
            "construccion_s": round(construccion_s, 3),
            "memoria_mb": round(memoria_mb, 2),
        }
    ]

    rankers = [("bm25", BM25Ranker(estadisticas)), ("tfidf", TFIDFRanker(estadisticas))]
    for tecnica, ranker in rankers:
        preparacion_s = 0.0
        if tecnica == "tfidf":
            inicio = time.perf_counter()
            ranker.document_norms()
            preparacion_s = time.perf_counter() - inicio

        mediciones = []
        for consulta in banco["consultas"]:
            inicio = time.perf_counter()
            for _ in range(REPETICIONES):
                top = [doc for doc, _ in ranker.search(consulta["terminos"], k=K)]
            milisegundos = (time.perf_counter() - inicio) / REPETICIONES * 1000
            aciertos = len(set(top) & set(consulta["relevantes"]))
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
                    "tecnica": tecnica,
                    "fase": "consulta",
                    "grupo": grupo,
                    "consultas": len(elegidas),
                    "p10": round(medidor.fmean(m["p10"] for m in elegidas), 4),
                    "r10": round(medidor.fmean(m["r10"] for m in elegidas), 4),
                    "consulta_ms": round(medidor.fmean(m["ms"] for m in elegidas), 3),
                    "preparacion_s": round(preparacion_s, 3),
                }
            )

        del mediciones

    return filas


def run(sizes: tuple[int, ...], base: Path) -> list[dict]:
    filas: list[dict] = []
    for n in sizes:
        filas.extend(medir(n, base))
    return filas


def main() -> None:
    ap = argparse.ArgumentParser(description="Motor propio sobre el corpus de la Parte 3")
    ap.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000, 100000])
    ap.add_argument("--data", default="data/text")
    ap.add_argument("--output", default="benchmark_results/text")
    args = ap.parse_args()

    filas = run(tuple(args.sizes), Path(args.data))
    for fila in filas:
        print(fila)

    salida = Path(args.output)
    write_rows(
        filas,
        salida / "motor_benchmark.csv",
        salida / "motor_benchmark.json",
        {"sizes": args.sizes, "k": K, "repeticiones": REPETICIONES, "tokenizacion": "lower+split"},
    )


if __name__ == "__main__":
    main()
