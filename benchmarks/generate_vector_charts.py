"""Graficas comparativas de la Parte 4: IVF contra HNSW.

Usa la distancia euclidiana, que es la unica medida en los tres tamanos.
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt

BASE = Path("benchmark_results/vector")
PLOTS = BASE / "plots"
PLOTS.mkdir(parents=True, exist_ok=True)


def leer(nombre: str) -> list[dict]:
    with (BASE / nombre).open(encoding="utf-8") as archivo:
        return list(csv.DictReader(archivo))


def figura(nombre: str, titulo: str, ylabel: str, series, log_y: bool = True) -> None:
    fig, ax = plt.subplots(figsize=(7, 4.2))
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
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS / f"{nombre}.png", dpi=150)
    plt.close(fig)


def main() -> None:
    filas = [r for r in leer("ivf_hnsw.csv") if r["metrica"] == "euclidean"]

    def serie(indice: str, campo: str):
        elegidas = sorted(
            [r for r in filas if r["indice"] == indice], key=lambda r: int(r["dataset_size"])
        )
        return [int(r["dataset_size"]) for r in elegidas], [float(r[campo]) for r in elegidas]

    figura(
        "vector_construccion",
        "Construccion del indice vectorial",
        "segundos",
        [("IVF", *serie("ivf", "construccion_s")), ("HNSW", *serie("hnsw", "construccion_s"))],
    )
    figura(
        "vector_consulta",
        "Tiempo de consulta k-NN",
        "milisegundos",
        [("IVF", *serie("ivf", "consulta_ms")), ("HNSW", *serie("hnsw", "consulta_ms"))],
    )
    figura(
        "vector_recall",
        "Recall@10 contra fuerza bruta",
        "recall",
        [("IVF", *serie("ivf", "recall10")), ("HNSW", *serie("hnsw", "recall10"))],
        log_y=False,
    )
    figura(
        "vector_memoria",
        "Memoria del indice vectorial",
        "megabytes",
        [("IVF", *serie("ivf", "memoria_mb")), ("HNSW", *serie("hnsw", "memoria_mb"))],
    )

    print("figuras:", PLOTS)


if __name__ == "__main__":
    main()
