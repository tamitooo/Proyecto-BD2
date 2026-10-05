"""Gráficas comparativas de la Parte 2 (datos espaciales).

A partir de ``benchmark_results/spatial_benchmark.json`` (que genera
``benchmarks/benchmark_spatial.py``) produce:

    spatial_range.png        consultas por rango (1, 5, 10 km)
    spatial_knn.png          k-NN (k = 10, 50, 100)
    spatial_build.png        tiempo de construcción del índice
    spatial_space.png        espacio del índice
    spatial_dashboard.png    panel resumen
    spatial_speedup.png      mejora frente a la búsqueda secuencial

Se mantiene aparte de ``generate_charts.py`` para no tocar las gráficas de la
Parte 1.

Uso:
    python -m benchmarks.generate_spatial_charts
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

#: Colores por técnica, estables en todas las gráficas.
TECHNIQUE_LABELS = {
    "secuencial": "Secuencial (sin índice)",
    "rtree": "R-Tree propio",
    "postgres_gist": "GiST de PostgreSQL",
    "rtree_memory": "R-Tree propio (memoria Python)",
}

TECHNIQUE_COLORS = {
    "secuencial": "#C44E52",
    "rtree": "#4C72B0",
    "postgres_gist": "#55A868",
    "rtree_memory": "#8DA0CB",
}

ORDER = ["secuencial", "rtree", "rtree_memory", "postgres_gist"]


def _nice(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def load_results(path: Path) -> Optional[dict]:
    if not path.exists():
        print(f"[aviso] no existe {path}; ejecuta antes el benchmark espacial")
        return None
    with path.open(encoding="utf-8") as manejador:
        return json.load(manejador)


def _indexar(payload: dict):
    """``{(N, tecnica, consulta, parametro): resultado}``."""
    tabla = {}
    for resultado in payload["results"]:
        clave = (
            resultado["dataset_size"],
            resultado["technique"],
            resultado["query"],
            resultado["parameter"],
        )
        tabla[clave] = resultado
    return tabla


def _barras_agrupadas(
    tamaños: Sequence[int],
    series: Dict[str, List[Optional[float]]],
    titulo: str,
    ylabel: str,
    ruta: Path,
    *,
    log: bool = True,
    formato: str = "{:,.1f}",
) -> None:
    """Gráfica de barras agrupadas: una barra por técnica dentro de cada N."""
    tecnicas = [t for t in ORDER if t in series]
    if not tecnicas:
        return

    ancho = 0.8 / len(tecnicas)
    posiciones = range(len(tamaños))

    figura, ejes = plt.subplots(figsize=(11, 6))
    for indice, tecnica in enumerate(tecnicas):
        valores = series[tecnica]
        desplazamiento = (indice - (len(tecnicas) - 1) / 2) * ancho
        barras = ejes.bar(
            [p + desplazamiento for p in posiciones],
            [v if v is not None else 0 for v in valores],
            ancho,
            label=TECHNIQUE_LABELS.get(tecnica, tecnica),
            color=TECHNIQUE_COLORS.get(tecnica),
        )
        for barra, valor in zip(barras, valores):
            if valor is None:
                continue
            ejes.annotate(
                formato.format(valor),
                (barra.get_x() + barra.get_width() / 2, barra.get_height()),
                ha="center",
                va="bottom",
                fontsize=8,
            )

    ejes.set_title(titulo)
    ejes.set_xlabel("Puntos en el dataset")
    ejes.set_ylabel(ylabel)
    ejes.set_xticks(list(posiciones))
    ejes.set_xticklabels([_nice(n) for n in tamaños])
    if log:
        ejes.set_yscale("log")
    ejes.grid(axis="y", linestyle=":", alpha=0.4)
    ejes.legend()
    figura.tight_layout()
    figura.savefig(ruta, dpi=110)
    plt.close(figura)
    print(f"[ok] {ruta}")


def charts_for_spatial(payload: dict, output_dir: Path) -> None:
    tamaños = sorted({r["dataset_size"] for r in payload["results"]})
    tabla = _indexar(payload)
    radios = [p for p in payload["config"]["radii_m"]]
    ks = [p for p in payload["config"]["k_values"]]

    def recolectar(consulta: str, parametro: str) -> Dict[str, List[Optional[float]]]:
        series: Dict[str, List[Optional[float]]] = {}
        for tecnica in ORDER:
            valores: List[Optional[float]] = []
            for n in tamaños:
                resultado = tabla.get((n, tecnica, consulta, parametro))
                if resultado is None or not resultado.get("supported"):
                    valores.append(None)
                else:
                    valores.append(resultado.get("avg_ms"))
            if any(v is not None for v in valores):
                series[tecnica] = valores
        return series

    # 1) Una gráfica por radio, con las tres técnicas.
    for radio in radios:
        etiqueta = f"{radio // 1000} km"
        series = recolectar("range", etiqueta)
        if series:
            _barras_agrupadas(
                tamaños,
                series,
                f"Consulta por rango de {etiqueta} (promedio por consulta)",
                "Tiempo promedio (ms)",
                output_dir / f"spatial_range_{radio // 1000}km.png",
            )

    # 2) k-NN: una gráfica por k.
    for k in ks:
        series = recolectar("knn", f"k={k}")
        if series:
            _barras_agrupadas(
                tamaños,
                series,
                f"k-NN con k = {k} (promedio por consulta)",
                "Tiempo promedio (ms)",
                output_dir / f"spatial_knn_k{k}.png",
            )

    # 3) Gráfica resumen: radio 5 km y k = 10 en un panel 2x2.
    figura, ejes = plt.subplots(2, 2, figsize=(13, 9))

    def panel(eje, consulta, parametro, titulo):
        series = recolectar(consulta, parametro)
        tecnicas = [t for t in ORDER if t in series]
        if not tecnicas:
            eje.set_visible(False)
            return
        ancho = 0.8 / len(tecnicas)
        posiciones = range(len(tamaños))
        for indice, tecnica in enumerate(tecnicas):
            valores = series[tecnica]
            desplazamiento = (indice - (len(tecnicas) - 1) / 2) * ancho
            eje.bar(
                [p + desplazamiento for p in posiciones],
                [v if v is not None else 0 for v in valores],
                ancho,
                label=TECHNIQUE_LABELS.get(tecnica, tecnica),
                color=TECHNIQUE_COLORS.get(tecnica),
            )
        eje.set_title(titulo)
        eje.set_xticks(list(posiciones))
        eje.set_xticklabels([_nice(n) for n in tamaños])
        eje.set_yscale("log")
        eje.grid(axis="y", linestyle=":", alpha=0.4)
        eje.set_ylabel("ms")

    panel(ejes[0][0], "range", "1 km", "Rango de 1 km")
    panel(ejes[0][1], "range", "10 km", "Rango de 10 km")
    panel(ejes[1][0], "knn", "k=10", "k-NN con k = 10")
    panel(ejes[1][1], "knn", "k=100", "k-NN con k = 100")
    ejes[0][0].legend(fontsize=8)
    figura.suptitle("Parte 2 · Secuencial vs R-Tree propio vs GiST de PostgreSQL")
    figura.tight_layout()
    figura.savefig(output_dir / "spatial_dashboard.png", dpi=110)
    plt.close(figura)
    print(f"[ok] {output_dir / 'spatial_dashboard.png'}")

    # 4) Tiempo de construcción del índice (una barra por técnica y tamaño).
    construir: Dict[str, List[Optional[float]]] = {}
    for tecnica in ORDER:
        valores = []
        for n in tamaños:
            encontrado = None
            for clave, resultado in tabla.items():
                if (
                    clave[0] == n
                    and clave[1] == tecnica
                    and resultado.get("supported")
                    and resultado.get("build_ms") is not None
                ):
                    encontrado = resultado["build_ms"]
                    break
            valores.append(encontrado)
        if any(v is not None for v in valores):
            construir[tecnica] = valores
    if construir:
        _barras_agrupadas(
            tamaños,
            construir,
            "Tiempo de construcción del índice espacial",
            "Milisegundos",
            output_dir / "spatial_build.png",
        )

    # 5) Espacio del índice.
    espacio: Dict[str, List[Optional[float]]] = {}
    for tecnica in ORDER:
        valores = []
        for n in tamaños:
            encontrado = None
            for clave, resultado in tabla.items():
                if (
                    clave[0] == n
                    and clave[1] == tecnica
                    and resultado.get("supported")
                    and resultado.get("size_bytes")
                ):
                    encontrado = resultado["size_bytes"] / (1024 * 1024)
                    break
            valores.append(encontrado)
        if any(v is not None for v in valores):
            espacio[tecnica] = valores
    # Memoria del R-Tree en Python (tracemalloc), como serie aparte: no es
    # comparable con el tamaño en disco del GiST, pero el enunciado pide
    # "uso de memoria/espacio en disco" y se reportan las dos cosas.
    memoria = []
    for n in tamaños:
        encontrado = None
        for clave, resultado in tabla.items():
            if clave[0] == n and clave[1] == "rtree" and resultado.get("memory_bytes"):
                encontrado = resultado["memory_bytes"] / (1024 * 1024)
                break
        memoria.append(encontrado)
    if any(v is not None for v in memoria):
        espacio["rtree_memory"] = memoria
    if espacio:
        _barras_agrupadas(
            tamaños,
            espacio,
            "Espacio del índice: R-Tree serializado vs pg_relation_size(GiST)",
            "Megabytes (escala log)",
            output_dir / "spatial_space.png",
            log=True,
            formato="{:,.2f}",
        )

    # 6) Mejora frente a la secuencial (cuántas veces más rápido).
    for consulta, parametros, nombre in (
        ("range", [f"{r // 1000} km" for r in radios], "rango"),
        ("knn", [f"k={k}" for k in ks], "k-NN"),
    ):
        for parametro in parametros:
            base = {
                n: (tabla.get((n, "secuencial", consulta, parametro)) or {}).get("avg_ms")
                for n in tamaños
            }
            if not any(base.values()):
                continue
            figura, eje = plt.subplots(figsize=(10, 5.5))
            ancho = 0.35
            posiciones = range(len(tamaños))
            for indice, tecnica in enumerate(("rtree", "postgres_gist")):
                valores = []
                for n in tamaños:
                    resultado = tabla.get((n, tecnica, consulta, parametro))
                    referencia = base.get(n)
                    if (
                        resultado is None
                        or not resultado.get("supported")
                        or not resultado.get("avg_ms")
                        or not referencia
                    ):
                        valores.append(0)
                    else:
                        valores.append(referencia / resultado["avg_ms"])
                barras = eje.bar(
                    [p + (indice - 0.5) * ancho for p in posiciones],
                    valores,
                    ancho,
                    label=TECHNIQUE_LABELS.get(tecnica, tecnica),
                    color=TECHNIQUE_COLORS.get(tecnica),
                )
                for barra, valor in zip(barras, valores):
                    if valor:
                        eje.annotate(
                            f"{valor:,.1f}x",
                            (barra.get_x() + barra.get_width() / 2, valor),
                            ha="center",
                            va="bottom",
                            fontsize=8,
                        )
            eje.axhline(1.0, color="#64748b", linestyle="--", linewidth=1)
            eje.set_title(
                f"Mejora frente a la búsqueda secuencial · {nombre} ({parametro})"
            )
            eje.set_xlabel("Puntos en el dataset")
            eje.set_ylabel("Veces más rápido que secuencial")
            eje.set_xticks(list(posiciones))
            eje.set_xticklabels([_nice(n) for n in tamaños])
            eje.grid(axis="y", linestyle=":", alpha=0.4)
            eje.legend()
            figura.tight_layout()
            sufijo = parametro.replace(" ", "").replace("=", "")
            figura.savefig(
                output_dir / f"spatial_speedup_{consulta}_{sufijo}.png", dpi=110
            )
            plt.close(figura)
            print(f"[ok] {output_dir / f'spatial_speedup_{consulta}_{sufijo}.png'}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera las gráficas comparativas de la Parte 2",
    )
    parser.add_argument("--results-dir", default="benchmark_results")
    parser.add_argument("--output-dir", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    results_dir = Path(args.results_dir)
    output_dir = Path(args.output_dir) if args.output_dir else results_dir / "plots"
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = load_results(results_dir / "spatial_benchmark.json")
    if payload is None:
        return 1

    charts_for_spatial(payload, output_dir)
    print()
    print(f"Gráficas espaciales generadas en: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
