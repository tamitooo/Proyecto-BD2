"""Mide Precision@10 real de SIMILAR_TO/IVF contra etiquetas sintéticas.

No usa las consultas para entrenar: son imágenes nuevas en consultas/.
El CSV de evaluación separa coincidencias por figura, color y ambas.

    python -m benchmarks.benchmark_geometric_retrieval \
        --dataset data/geometric --api http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from tools.seed_tienda import Api

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "geometric"
DEFAULT_OUTPUT = ROOT / "benchmarks" / "results" / "geometric"


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def precision(ids: list[int], query: dict, labels: dict[int, dict], *, k: int = 10) -> dict:
    """Relevancia definida antes de medir, nunca inferida por el propio modelo."""
    if k < 1:
        raise ValueError("k debe ser positivo")
    top = ids[:k]
    same_shape = sum(labels[i]["figura"] == query["figura"] for i in top)
    same_color = sum(labels[i]["color"] == query["color"] for i in top)
    both = sum(labels[i]["figura"] == query["figura"] and labels[i]["color"] == query["color"] for i in top)
    return {"p_shape": same_shape / k, "p_color": same_color / k, "p_both": both / k,
            "top1_shape": int(bool(top) and labels[top[0]]["figura"] == query["figura"])}


def evaluate(api: Api, dataset: Path, output: Path, *, k: int = 10,
             limit: int | None = None) -> dict:
    from tools.generate_geometric_dataset import verify_dataset
    integrity = verify_dataset(dataset)
    labels = {int(r["id"]): r for r in _read(dataset / "etiquetas.csv")}
    queries = _read(dataset / "consultas.csv")[:limit] if limit is not None else _read(dataset / "consultas.csv")
    if not queries:
        raise ValueError("no hay consultas para evaluar")
    if len(labels) < k:
        raise ValueError("hay menos productos que k")

    rows: list[dict] = []
    for q in queries:
        filename = q["imagen"].replace("'", "''")
        response = api.sql(
            f"SELECT id, categoria, SIMILARITY_SCORE() AS score FROM figuras "
            f"WHERE SIMILAR_TO('{filename}', k={k}) USING IVF WITH METRIC=cosine")
        ids = [int(r["id"]) for r in response["rows"]]
        if len(ids) != k or len(set(ids)) != len(ids) or any(i not in labels for i in ids):
            raise ValueError(f"consulta {filename}: top {k} incompleto, duplicado o fuera del CSV")
        metrics = precision(ids, q, labels, k=k)
        rows.append({"query_id": q["id"], "figura": q["figura"], "color": q["color"],
                     **metrics, "ids": " ".join(map(str, ids))})

    means = {key: round(sum(r[key] for r in rows) / len(rows), 4)
             for key in ("p_shape", "p_color", "p_both", "top1_shape")}
    by_shape: dict[str, dict] = {}
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["figura"]].append(r)
    for shape, group in sorted(groups.items()):
        by_shape[shape] = {key: round(sum(r[key] for r in group) / len(group), 4)
                           for key in ("p_shape", "p_color", "p_both", "top1_shape")}
    from tools.generate_geometric_dataset import SHAPES
    report = {"queries": len(rows), "products": integrity["products"], "k": k,
              "method": "SIMILAR_TO(image) USING IVF WITH METRIC=cosine",
              "relevance": "shape, color and shape+color labels independent of image features",
              "averages": means, "by_shape": by_shape,
              "random_shape_baseline": round(1 / len(SHAPES), 4)}
    output.mkdir(parents=True, exist_ok=True)
    with (output / "precision_queries.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output / "precision_summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Gráfico imprimible para el informe del curso (misma verdad de terreno).
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    names = list(by_shape)
    positions = list(range(len(names)))
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar([x - 0.18 for x in positions], [by_shape[n]["p_shape"] for n in names],
           width=0.36, label="Figura", color="#2563eb")
    ax.bar([x + 0.18 for x in positions], [by_shape[n]["p_color"] for n in names],
           width=0.36, label="Color (sin descriptor cromático)", color="#f59e0b")
    ax.axhline(1 / len(SHAPES), color="#64748b", linestyle="--", linewidth=1,
               label=f"Azar por figura (1/{len(SHAPES)})")
    ax.set_xticks(positions, names)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Precision@10")
    ax.set_title(f"Recuperación por similitud: {len(rows)} consultas, {len(labels)} figuras")
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output / "precision_por_figura.png", dpi=150)
    plt.close(fig)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    print(json.dumps(evaluate(Api(args.api), args.dataset, args.output, k=args.k,
                              limit=args.limit), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
