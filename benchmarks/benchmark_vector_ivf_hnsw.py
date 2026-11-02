"""IVF contra HNSW sobre vectores sinteticos (Parte 4).

Los vectores se generan con semilla fija en grupos separados, para que IVF
tenga algo que clusterizar. La referencia exacta para medir Recall@10 sale
del k-NN por fuerza bruta de cada indice, no de una aproximacion.

Cuando la extraccion de caracteristicas de la Parte 4 este lista, se cambia
la fuente de vectores sin tocar la medicion.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import time
from pathlib import Path

from benchmarks.common import deep_size, write_rows
from vector import HNSWIndex, IVFIndex

K = 10
CONSULTAS = 100
DIM = 32
GRUPOS = 8
DESVIO = 0.15


def dataset(n: int, semilla: int = 7) -> tuple[dict[int, list[float]], list[list[float]]]:
    rng = random.Random(semilla)
    centros = [[rng.uniform(-1.0, 1.0) for _ in range(DIM)] for _ in range(GRUPOS)]

    datos = {}
    for i in range(n):
        centro = centros[rng.randrange(GRUPOS)]
        datos[i] = [x + rng.gauss(0.0, DESVIO) for x in centro]

    consultas = []
    for _ in range(CONSULTAS):
        centro = centros[rng.randrange(GRUPOS)]
        consultas.append([x + rng.gauss(0.0, DESVIO) for x in centro])

    return datos, consultas


def _exacto(indice, consulta) -> set:
    return {doc for doc, _ in indice.brute_force_knn(consulta, k=K)}


def _recall(obtenidos, exactos) -> float:
    return len(set(obtenidos) & exactos) / len(exactos)


def medir_indice(nombre: str, indice, consultas, exactos, construccion_s: float, extra: dict) -> list[dict]:
    tiempos = []
    recalls = []
    for consulta, referencia in zip(consultas, exactos):
        inicio = time.perf_counter()
        obtenidos = [doc for doc, _ in indice.knn(consulta, k=K)]
        tiempos.append((time.perf_counter() - inicio) * 1000)
        recalls.append(_recall(obtenidos, referencia))

    return [
        {
            "dataset_size": extra.pop("n"),
            "indice": nombre,
            "metrica": extra.pop("metrica"),
            "construccion_s": round(construccion_s, 3),
            "consulta_ms": round(statistics.fmean(tiempos), 3),
            "recall10": round(statistics.fmean(recalls), 4),
            "memoria_mb": round(deep_size(indice) / 1048576, 2),
            **extra,
        }
    ]


def medir(n: int, metrica: str) -> list[dict]:
    datos, consultas = dataset(n)
    elementos = list(datos.items())

    ivf = IVFIndex(n_lists=max(1, int(math.sqrt(n))), metric_name=metrica, random_seed=1)
    inicio = time.perf_counter()
    ivf.build(elementos)
    ivf_s = time.perf_counter() - inicio

    exactos = [_exacto(ivf, consulta) for consulta in consultas]

    hnsw = HNSWIndex(M=16, ef_construction=100, ef_search=50, metric_name=metrica, random_seed=1)
    inicio = time.perf_counter()
    for doc, vector in elementos:
        hnsw.insert(doc, vector)
    hnsw_s = time.perf_counter() - inicio

    filas = []
    filas += medir_indice("ivf", ivf, consultas, exactos, ivf_s, {"n": n, "metrica": metrica, "n_lists": ivf.n_lists, "n_probe": ivf.n_probe})
    filas += medir_indice("hnsw", hnsw, consultas, exactos, hnsw_s, {"n": n, "metrica": metrica, "M": 16, "ef_search": 50})
    return filas


def run(sizes: tuple[int, ...], metricas: tuple[str, ...]) -> list[dict]:
    filas: list[dict] = []
    for n in sizes:
        for metrica in metricas:
            filas.extend(medir(n, metrica))
    return filas


def main() -> None:
    ap = argparse.ArgumentParser(description="IVF contra HNSW en vectores sinteticos")
    ap.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000, 100000])
    ap.add_argument("--metricas", nargs="+", default=["euclidean", "cosine"])
    ap.add_argument("--output", default="benchmark_results/vector")
    args = ap.parse_args()

    filas = run(tuple(args.sizes), tuple(args.metricas))
    for fila in filas:
        print(fila)

    salida = Path(args.output)
    write_rows(
        filas,
        salida / "ivf_hnsw.csv",
        salida / "ivf_hnsw.json",
        {"sizes": args.sizes, "metricas": args.metricas, "k": K, "consultas": CONSULTAS, "dim": DIM, "grupos": GRUPOS},
    )


if __name__ == "__main__":
    main()
