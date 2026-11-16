"""Graficas de la Parte 4: IVF contra HNSW.

Por defecto dibuja la corrida sintetica con distancia euclidiana, que es la que
estaba publicada. Con ``--csv`` y ``--metricas`` se puede graficar cualquier
otra tabla, por ejemplo el corpus multimedia con las dos metricas:

    python -m benchmarks.generate_vector_charts --csv ivf_hnsw_corpus_image.csv \
        --prefijo vector_corpus --metricas euclidean cosine
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt

BASE = Path("benchmarks/results/vector")
PLOTS = BASE / "plots"


def leer(nombre: str) -> list[dict]:
    with (BASE / nombre).open(encoding="utf-8") as archivo:
        return list(csv.DictReader(archivo))


def figura(nombre: str, titulo: str, ylabel: str, series, log_y: bool = True) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    for etiqueta, xs, ys in series:
        ax.plot(xs, ys, marker="o", label=etiqueta)
    ax.set_xscale("log")
    if log_y:
        ax.set_yscale("log")
    else:
        valores = [y for _, _, ys in series for y in ys]
        ax.set_ylim(max(0.0, min(valores) - 0.05), min(1.02, max(valores) + 0.02))
    ax.set_xlabel("vectores")
    ax.set_ylabel(ylabel)
    ax.set_title(titulo)
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(PLOTS / f"{nombre}.png", dpi=150)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Graficas de IVF contra HNSW")
    ap.add_argument("--csv", default="ivf_hnsw.csv")
    ap.add_argument("--prefijo", default="vector")
    ap.add_argument("--metricas", nargs="+", default=["euclidean"])
    args = ap.parse_args()

    PLOTS.mkdir(parents=True, exist_ok=True)
    filas = [r for r in leer(args.csv) if r["metrica"] in args.metricas]
    if not filas:
        raise SystemExit(f"{args.csv} no tiene filas para {args.metricas}")

    def serie(indice: str, metrica: str, campo: str):
        elegidas = sorted(
            [r for r in filas if r["indice"] == indice and r["metrica"] == metrica],
            key=lambda r: int(r["dataset_size"]),
        )
        return [int(r["dataset_size"]) for r in elegidas], [float(r[campo]) for r in elegidas]

    etiquetas = [(f"{indice.upper()} {metrica}", indice, metrica)
                 for indice in ("ivf", "hnsw") for metrica in args.metricas]

    figura(
        f"{args.prefijo}_construccion",
        "Construccion del indice vectorial",
        "segundos",
        [(etiqueta, *serie(indice, metrica, "construccion_s"))
         for etiqueta, indice, metrica in etiquetas],
    )
    figura(
        f"{args.prefijo}_consulta",
        "Tiempo de consulta k-NN",
        "milisegundos",
        [(etiqueta, *serie(indice, metrica, "consulta_ms"))
         for etiqueta, indice, metrica in etiquetas],
    )
    figura(
        f"{args.prefijo}_recall",
        "Recall@10 contra fuerza bruta",
        "recall",
        [(etiqueta, *serie(indice, metrica, "recall10"))
         for etiqueta, indice, metrica in etiquetas],
        log_y=False,
    )
    figura(
        f"{args.prefijo}_memoria",
        "Memoria del indice vectorial",
        "megabytes",
        [(etiqueta, *serie(indice, metrica, "memoria_mb"))
         for etiqueta, indice, metrica in etiquetas],
    )

    print("figuras:", PLOTS)


if __name__ == "__main__":
    main()
