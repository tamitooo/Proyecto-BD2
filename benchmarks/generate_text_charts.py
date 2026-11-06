"""Gráficas de la Parte 3 (motor contra GIN) a partir de los CSV ya medidos."""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib.pyplot as plt

BASE = Path("benchmarks/results/text")
PLOTS = BASE / "plots"
PLOTS.mkdir(parents=True, exist_ok=True)


def leer(nombre: str) -> list[dict]:
    with (BASE / nombre).open(encoding="utf-8") as archivo:
        return list(csv.DictReader(archivo))


def serie(rows, filtro, campo):
    elegidas = [r for r in rows if filtro(r)]
    elegidas.sort(key=lambda r: int(r["dataset_size"]))
    return [int(r["dataset_size"]) for r in elegidas], [float(r[campo]) for r in elegidas]


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
    ax.set_xlabel("documentos")
    ax.set_ylabel(ylabel)
    ax.set_title(titulo)
    ax.grid(True, which="both", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS / f"{nombre}.png", dpi=150)
    plt.close(fig)


def main() -> None:
    motor = leer("motor_benchmark.csv")
    gin = leer("gin_benchmark.csv")

    x_motor, y_motor = serie(motor, lambda r: r["fase"] == "construccion", "construccion_s")
    x_gin, y_gin = serie(gin, lambda r: r["config"] == "simple" and r["fase"] == "construccion", "indice_s")
    figura(
        "texto_construccion",
        "Construccion del indice de texto",
        "segundos",
        [("GIN de PostgreSQL", x_gin, y_gin), ("motor propio (estadisticas)", x_motor, y_motor)],
    )

    series = [("GIN de PostgreSQL", *serie(gin, lambda r: r["config"] == "simple" and r["fase"] == "consulta" and r["grupo"] == "todas", "consulta_ms"))]
    for tecnica in ("bm25", "tfidf"):
        series.append((tecnica.upper(), *serie(motor, lambda r, t=tecnica: r["fase"] == "consulta" and r["grupo"] == "todas" and r["tecnica"] == t, "consulta_ms")))
    figura("texto_consulta", "Tiempo de consulta promedio", "milisegundos", series)

    x_ram, y_ram = serie(motor, lambda r: r["fase"] == "construccion", "memoria_mb")
    x_disco, y_disco = serie(gin, lambda r: r["config"] == "simple" and r["fase"] == "construccion", "indice_mb")
    figura(
        "texto_memoria",
        "Espacio ocupado por el indice",
        "megabytes",
        [("motor propio en RAM", x_ram, y_ram), ("GIN en disco", x_disco, y_disco)],
    )

    series = [("GIN de PostgreSQL", *serie(gin, lambda r: r["config"] == "simple" and r["fase"] == "consulta" and r["grupo"] == "todas", "p10"))]
    for tecnica in ("bm25", "tfidf"):
        series.append((tecnica.upper(), *serie(motor, lambda r, t=tecnica: r["fase"] == "consulta" and r["grupo"] == "todas" and r["tecnica"] == t, "p10")))
    figura("texto_precision", "Precision@10", "P@10", series, log_y=False)

    print("figuras:", PLOTS)


if __name__ == "__main__":
    main()
