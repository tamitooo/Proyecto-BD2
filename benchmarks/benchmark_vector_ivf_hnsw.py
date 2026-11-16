"""IVF contra HNSW (Parte 4); Recall@10 contra fuerza bruta.

Dos fuentes de datos:

* ``--corpus data/multimedia/<n>`` usa los vectores SIFT/MFCC del corpus de la
  Parte 4 (issue #92), que es lo que la rubrica 2.4.4 pide literalmente:
  «datasets de 1 000, 10 000 y 100 000 imágenes/audios»;
* sin ``--corpus`` genera grupos sinteticos, que es la corrida historica.

En ambos casos se mide construccion, consulta k-NN (k=10), Recall@10 contra
fuerza bruta y memoria del indice.
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


def cargar_corpus(base: Path, modalidad: str = "image") -> tuple[dict[int, list[float]], list[list[float]]]:
    """Vectores ya extraidos del corpus; las consultas son objetos del mismo corpus."""
    archivo = base / "vectors.jsonl"
    if not archivo.exists():
        raise SystemExit(f"no existe {archivo}; corre benchmarks.multimedia_corpus primero")
    datos: dict[int, list[float]] = {}
    with archivo.open(encoding="utf-8") as lineas:
        for linea in lineas:
            objeto = json.loads(linea)
            if objeto.get("modalidad") != modalidad or not objeto.get("vector"):
                continue
            datos[int(objeto["id"])] = objeto["vector"]
    if not datos:
        raise SystemExit(f"el corpus {base} no tiene vectores de modalidad '{modalidad}'")
    rng = random.Random(7)
    elegidos = rng.sample(sorted(datos), min(CONSULTAS, len(datos)))
    return datos, [datos[i] for i in elegidos]


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


def medir(datos: dict[int, list[float]], consultas: list[list[float]], metrica: str,
          fuente: str) -> list[dict]:
    n = len(datos)
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
    filas += medir_indice("ivf", ivf, consultas, exactos, ivf_s, {"n": n, "metrica": metrica, "fuente": fuente, "n_lists": ivf.n_lists, "n_probe": ivf.n_probe})
    filas += medir_indice("hnsw", hnsw, consultas, exactos, hnsw_s, {"n": n, "metrica": metrica, "fuente": fuente, "M": 16, "ef_search": 50})
    return filas


def _corpora(raiz: Path, sizes: tuple[int, ...]) -> list[tuple[int, Path]]:
    """Acepta data/multimedia (con subcarpetas por tamano) o un corpus suelto."""
    if (raiz / "vectors.jsonl").exists():
        tamano = int(json.loads((raiz / "vectors.jsonl").open(encoding="utf-8").readline())["id"]) + 1
        return [(tamano, raiz)]
    return [(n, raiz / str(n)) for n in sizes if (raiz / str(n) / "vectors.jsonl").exists()]


def run(sizes: tuple[int, ...], metricas: tuple[str, ...], corpus: Path | None = None,
        modalidad: str = "image", destino: Path | None = None) -> list[dict]:
    filas: list[dict] = []
    if corpus is None:
        for n in sizes:
            datos, consultas = dataset(n)
            for metrica in metricas:
                filas.extend(medir(datos, consultas, metrica, "sintetico"))
                if destino:
                    _guardar(filas, destino, sizes, metricas)
        return filas

    for tamano, ruta in _corpora(corpus, sizes):
        datos, consultas = cargar_corpus(ruta, modalidad)
        for metrica in metricas:
            print(f"[{modalidad} n={tamano} {metrica}] {len(datos)} vectores", flush=True)
            filas.extend(medir(datos, consultas, metrica, f"corpus-{modalidad}"))
            if destino:
                _guardar(filas, destino, sizes, metricas, modalidad, corpus=True)
    return filas


def _guardar(filas: list[dict], destino: Path, sizes, metricas, modalidad: str = "image",
             corpus: bool = False) -> None:
    sufijo = f"_corpus_{modalidad}" if corpus else ""
    write_rows(
        filas,
        destino / f"ivf_hnsw{sufijo}.csv",
        destino / f"ivf_hnsw{sufijo}.json",
        {"sizes": sizes, "metricas": metricas, "k": K, "consultas": CONSULTAS,
         "dim": DIM, "grupos": GRUPOS if not corpus else None,
         "fuente": f"corpus multimedia ({modalidad})" if corpus else "sintetico"},
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="IVF contra HNSW: sintetico o corpus multimedia")
    ap.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000, 100000])
    ap.add_argument("--metricas", nargs="+", default=["euclidean", "cosine"])
    ap.add_argument("--output", default="benchmarks/results/vector")
    ap.add_argument("--corpus", default=None,
                    help="raiz del corpus (data/multimedia) o un corpus concreto")
    ap.add_argument("--modalidad", default="image", choices=["image", "audio"])
    args = ap.parse_args()

    salida = Path(args.output)
    corpus = Path(args.corpus) if args.corpus else None
    filas = run(tuple(args.sizes), tuple(args.metricas), corpus, args.modalidad, salida)
    for fila in filas:
        print(fila)

    if corpus is None:
        _guardar(filas, salida, args.sizes, args.metricas)
    else:
        _guardar(filas, salida, args.sizes, args.metricas, args.modalidad, corpus=True)
        print("resumen:", salida / f"ivf_hnsw_corpus_{args.modalidad}.csv")


if __name__ == "__main__":
    main()
