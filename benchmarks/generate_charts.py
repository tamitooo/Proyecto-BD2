"""
Genera las graficas comparativas de la Parte 1 (seccion 2.1.6 del
enunciado) a partir de los resultados exportados por:

- `benchmarks/benchmark_indexes.py`  -> benchmark_results/index_benchmark.json
- `benchmarks/benchmark_heap_vs_sequential.py`
                                     -> benchmark_results/storage_benchmark.json

Graficas de indices:
    index_build_time.png      costo de construccion del indice
    index_exact_lookup.png    busqueda por igualdad exacta (hit / miss)
    index_range_search.png    busqueda por rango
    index_ordered_scan.png    recorrido ordenado (ORDER BY sin sort externo)
    index_size.png            espacio adicional del indice
    index_mutations.png       rendimiento con inserciones/borrados frecuentes
    index_dashboard.png       panel resumen 2x2

Graficas de archivos:
    storage_insert.png        tiempo de insercion
    storage_search.png        busqueda por clave primaria (hit / miss)
    storage_space.png         espacio en disco utilizado
    storage_mutation.png      borrado y reorganizacion
    storage_dashboard.png     panel resumen 2x2

Uso:
    python -m benchmarks.generate_charts
    python benchmarks/generate_charts.py --results-dir benchmark_results
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (debe ir despues de use("Agg"))


PALETTE = [
    "#4C72B0",
    "#DD8452",
    "#55A868",
    "#C44E52",
    "#8172B3",
    "#937860",
]

# Etiquetas legibles para las tecnicas del benchmark de indices.
INDEX_LABELS = {
    "bplus_clustered": "B+ agrupado",
    "bplus_unclustered": "B+ no agrupado",
    "extendible_hash": "Hash extendible",
}

# Etiquetas legibles para las tecnicas del benchmark de archivos.
STORAGE_LABELS = {
    "heap_file": "Heap File",
    "archivo_secuencial": "Archivo Secuencial",
}


# ----------------------------------------------------------------------
# Carga y normalizacion de resultados
# ----------------------------------------------------------------------


def _nice_number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def load_results(path: Path) -> Optional[dict]:
    if not path.exists():
        print(f"[aviso] no existe {path}; se omite ese conjunto de graficas")
        return None

    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _technique_field(payload: dict) -> Optional[str]:
    """Detecta el nombre del campo que identifica la tecnica evaluada."""
    for result in payload.get("results", []):
        for candidate in ("index_type", "storage_type"):
            if candidate in result:
                return candidate
    return None


def series(
    payload: dict,
    metric: str,
    value_field: str,
) -> Tuple[List[int], Dict[str, List[Optional[float]]]]:
    """
    Devuelve (tamanos, {tecnica: [valor_por_tamano]}).

    `value_field` es "avg_us", "total_ms" o "size_bytes"; los puntos no
    soportados por una tecnica quedan como None (se dibujan como N/A).
    """
    sizes = sorted({result["dataset_size"] for result in payload["results"]})
    field = _technique_field(payload)
    output: Dict[str, List[Optional[float]]] = {}

    for result in payload["results"]:
        if result["metric"] != metric:
            continue

        tech = result[field]
        output.setdefault(tech, [None] * len(sizes))

        index = sizes.index(result["dataset_size"])
        if not result.get("supported", True):
            continue

        value = result.get(value_field)
        if value is None:
            continue

        output[tech][index] = value

    return sizes, output


def _human_label(name: str, labels: Dict[str, str]) -> str:
    base, separator, suffix = name.partition(" (")
    label = labels.get(base, base.replace("_", " "))

    if separator:
        return f"{label} ({suffix}"

    return label


# ----------------------------------------------------------------------
# Dibujo
# ----------------------------------------------------------------------


def grouped_bars(
    ax,
    sizes: Sequence[int],
    data: Dict[str, List[Optional[float]]],
    labels: Dict[str, str],
    title: str,
    ylabel: str,
    log_scale: bool = False,
    value_fmt: str = "{:,.2f}",
):
    techniques = list(data.keys())
    width = 0.8 / max(1, len(techniques))
    positions = list(range(len(sizes)))

    finite_values = [
        value
        for values in data.values()
        for value in values
        if value
    ]

    for offset, technique in enumerate(techniques):
        values = data[technique]
        xs = [p - 0.4 + width / 2 + offset * width for p in positions]
        ys = [0 if value is None else value for value in values]

        bars = ax.bar(
            xs,
            ys,
            width=width,
            label=_human_label(technique, labels),
            color=PALETTE[offset % len(PALETTE)],
        )

        for bar, value in zip(bars, values):
            if value is None:
                ax.annotate(
                    "N/A",
                    (bar.get_x() + bar.get_width() / 2, 0),
                    ha="center",
                    va="bottom",
                    fontsize=8,
                    color="#888888",
                )
                continue

            ax.annotate(
                value_fmt.format(value),
                (bar.get_x() + bar.get_width() / 2, value),
                ha="center",
                va="bottom",
                fontsize=8,
            )

    # Un solo valor distinto de cero en escala logaritmica confunde: se
    # mantiene escala lineal salvo que los datos abarquen varios ordenes.
    if log_scale and finite_values:
        ratio = max(finite_values) / max(1e-9, min(finite_values))
        if ratio >= 20:
            ax.set_yscale("log")
            ax.set_ylim(bottom=max(0.01, min(finite_values) / 5))

    ax.set_xticks(positions)
    ax.set_xticklabels([_nice_number(size) for size in sizes])
    ax.set_xlabel("Registros en el dataset")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(axis="y", linestyle=":", alpha=0.4)
    ax.set_axisbelow(True)

    if len(techniques) > 1:
        ax.legend(fontsize=9)


def single_chart(
    sizes: Sequence[int],
    data: Dict[str, List[Optional[float]]],
    labels: Dict[str, str],
    title: str,
    ylabel: str,
    path: Path,
    log_scale: bool = False,
    value_fmt: str = "{:,.2f}",
):
    figure, ax = plt.subplots(figsize=(9, 5))
    grouped_bars(
        ax,
        sizes,
        data,
        labels,
        title,
        ylabel,
        log_scale=log_scale,
        value_fmt=value_fmt,
    )
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)
    print(f"[ok] {path}")


def dashboard(
    panels: Sequence[Tuple[str, Sequence[int], Dict[str, List[Optional[float]]], str, str]],
    labels: Dict[str, str],
    title: str,
    path: Path,
):
    figure, axes = plt.subplots(2, 2, figsize=(14, 9))
    figure.suptitle(title, fontsize=14)

    for ax, (panel_title, sizes, data, ylabel, value_fmt) in zip(
        axes.flat,
        panels,
    ):
        grouped_bars(
            ax,
            sizes,
            data,
            labels,
            panel_title,
            ylabel,
            log_scale=True,
            value_fmt=value_fmt,
        )

    figure.tight_layout(rect=(0, 0, 1, 0.96))
    figure.savefig(path, dpi=150)
    plt.close(figure)
    print(f"[ok] {path}")


# ----------------------------------------------------------------------
# Conjuntos de graficas
# ----------------------------------------------------------------------


def charts_for_indexes(payload: dict, output_dir: Path) -> None:
    labels = INDEX_LABELS

    sizes, build = series(payload, "build", "total_ms")
    single_chart(
        sizes,
        build,
        labels,
        "Construccion del indice: B+ agrupado vs B+ no agrupado vs Hash",
        "Tiempo total (ms)",
        output_dir / "index_build_time.png",
        value_fmt="{:,.0f}",
    )

    _, exact_hit = series(payload, "exact_hit", "avg_us")
    _, exact_miss = series(payload, "exact_miss", "avg_us")
    exact = {
        f"{tech} (hit)": values for tech, values in exact_hit.items()
    }
    exact.update(
        {f"{tech} (miss)": values for tech, values in exact_miss.items()}
    )
    single_chart(
        sizes,
        exact,
        labels,
        "Busqueda por igualdad exacta (promedio por consulta)",
        "Tiempo promedio (us)",
        output_dir / "index_exact_lookup.png",
        log_scale=True,
        value_fmt="{:,.1f}",
    )

    _, ranged = series(payload, "range_search", "avg_us")
    single_chart(
        sizes,
        ranged,
        labels,
        "Busqueda por rango (promedio por consulta)",
        "Tiempo promedio (us)",
        output_dir / "index_range_search.png",
        log_scale=True,
        value_fmt="{:,.1f}",
    )

    _, ordered = series(payload, "ordered_scan", "avg_us")
    single_chart(
        sizes,
        ordered,
        labels,
        "Recorrido ordenado (ORDER BY resuelto por el indice)",
        "Tiempo promedio (us)",
        output_dir / "index_ordered_scan.png",
        log_scale=True,
        value_fmt="{:,.1f}",
    )

    _, indexed_size = series(payload, "serialized_size", "size_bytes")
    single_chart(
        sizes,
        indexed_size,
        labels,
        "Espacio adicional requerido por el indice",
        "Bytes",
        output_dir / "index_size.png",
        value_fmt="{:,.0f}",
    )

    _, insert_workload = series(payload, "insert", "avg_us")
    _, delete_workload = series(payload, "delete", "avg_us")
    mutations = {
        f"{tech} (insert)": values
        for tech, values in insert_workload.items()
    }
    mutations.update(
        {f"{tech} (delete)": values for tech, values in delete_workload.items()}
    )
    single_chart(
        sizes,
        mutations,
        labels,
        "Rendimiento con mutaciones frecuentes",
        "Tiempo promedio (us)",
        output_dir / "index_mutations.png",
        log_scale=True,
        value_fmt="{:,.1f}",
    )

    dashboard(
        [
            (
                "Construccion (ms)",
                sizes,
                build,
                "ms",
                "{:,.0f}",
            ),
            (
                "Busqueda exacta hit (us)",
                sizes,
                exact_hit,
                "us",
                "{:,.1f}",
            ),
            (
                "Busqueda por rango (us)",
                sizes,
                ranged,
                "us",
                "{:,.1f}",
            ),
            (
                "Espacio del indice (bytes)",
                sizes,
                indexed_size,
                "bytes",
                "{:,.0f}",
            ),
        ],
        labels,
        "Panel comparativo de indices (Parte 1)",
        output_dir / "index_dashboard.png",
    )


def charts_for_storage(payload: dict, output_dir: Path) -> None:
    labels = STORAGE_LABELS

    sizes, insert = series(payload, "insert", "avg_us")
    single_chart(
        sizes,
        insert,
        labels,
        "Tiempo de insercion: Heap File vs Archivo Secuencial",
        "Tiempo promedio por registro (us)",
        output_dir / "storage_insert.png",
        log_scale=True,
        value_fmt="{:,.1f}",
    )

    _, hit = series(payload, "search_hit", "avg_us")
    _, miss = series(payload, "search_miss", "avg_us")
    search = {f"{tech} (hit)": values for tech, values in hit.items()}
    search.update({f"{tech} (miss)": values for tech, values in miss.items()})
    single_chart(
        sizes,
        search,
        labels,
        "Busqueda por clave primaria",
        "Tiempo promedio por consulta (us)",
        output_dir / "storage_search.png",
        log_scale=True,
        value_fmt="{:,.1f}",
    )

    _, space = series(payload, "disk_space", "size_bytes")
    single_chart(
        sizes,
        space,
        labels,
        "Espacio en disco utilizado",
        "Bytes",
        output_dir / "storage_space.png",
        value_fmt="{:,.0f}",
    )

    _, delete = series(payload, "delete", "avg_us")
    _, reorg = series(payload, "reorganize", "total_ms")
    mutation = {f"{tech} (delete)": values for tech, values in delete.items()}
    mutation.update(
        {f"{tech} (reorganizar)": values for tech, values in reorg.items()}
    )
    single_chart(
        sizes,
        mutation,
        labels,
        "Borrado y reorganizacion",
        "Tiempo (us por borrado / ms por reorganizacion)",
        output_dir / "storage_mutation.png",
        log_scale=True,
    )

    dashboard(
        [
            ("Insercion (us/registro)", sizes, insert, "us", "{:,.1f}"),
            ("Busqueda hit (us)", sizes, hit, "us", "{:,.1f}"),
            ("Espacio en disco (bytes)", sizes, space, "bytes", "{:,.0f}"),
            ("Reorganizacion (ms)", sizes, reorg, "ms", "{:,.1f}"),
        ],
        labels,
        "Panel comparativo de archivos (Parte 1)",
        output_dir / "storage_dashboard.png",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera las graficas comparativas de la Parte 1",
    )
    parser.add_argument(
        "--results-dir",
        default="benchmark_results",
        help="Directorio con los JSON de resultados",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Directorio de salida (por defecto <results-dir>/plots)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    results_dir = Path(args.results_dir)
    output_dir = Path(args.output_dir) if args.output_dir else results_dir / "plots"
    output_dir.mkdir(parents=True, exist_ok=True)

    index_payload = load_results(results_dir / "index_benchmark.json")
    storage_payload = load_results(results_dir / "storage_benchmark.json")

    if index_payload is None and storage_payload is None:
        print(
            "No hay resultados. Ejecuta primero:\n"
            "  python -m benchmarks.benchmark_indexes\n"
            "  python benchmarks/benchmark_heap_vs_sequential.py"
        )
        return 1

    if index_payload is not None:
        charts_for_indexes(index_payload, output_dir)

    if storage_payload is not None:
        charts_for_storage(storage_payload, output_dir)

    print()
    print(f"Graficas generadas en: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
