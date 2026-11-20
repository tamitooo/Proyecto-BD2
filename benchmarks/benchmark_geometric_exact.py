"""Reproducible exact-cosine baseline for the scattered-shapes corpus.

Important: this is NOT IVF/SQL. It compares each held-out query image's
actual BoVW embedding against every indexed embedding by exact dot product.
The production IVF benchmark remains benchmarks.benchmark_geometric_retrieval.

    python -m benchmarks.benchmark_geometric_exact --dataset data/geometric
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


def _csv(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def evaluate(dataset: Path, output: Path, *, k: int = 10, limit: int | None = None) -> dict:
    from tools.generate_geometric_dataset import verify_dataset
    from vector.bow import FeatureModel, model_path
    from vector.extract_features import ExtractFeatures

    dataset, output = Path(dataset), Path(output)
    verify_dataset(dataset)
    products = _csv(dataset / "productos_indexados.csv")
    labels = {int(row["id"]): row for row in _csv(dataset / "etiquetas.csv")}
    queries = _csv(dataset / "consultas.csv")
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        queries = queries[:limit]
    if k < 1 or k > len(products):
        raise ValueError("k must be in [1, number of products]")
    model = FeatureModel.load(model_path(dataset / "modelo", "image"))
    identifiers = np.array([int(product["id"]) for product in products])
    matrix = np.asarray([json.loads(product["embedding"]) for product in products], dtype=np.float64)
    if matrix.shape != (len(products), model.n_words):
        raise ValueError("indexed embeddings do not match vocabulary")
    # Source model emits L2 normalized vectors; normalize once more after
    # six-decimal JSON rounding to compare actual cosine similarities.
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
    rows = []
    for query in queries:
        descriptors = ExtractFeatures.local_descriptors(dataset / "consultas" / query["imagen"],kind="image")
        qvector = model.encode(descriptors)
        if qvector.shape != (model.n_words,) or not np.linalg.norm(qvector):
            raise ValueError(f"query {query['imagen']} has no valid embedding")
        similarity = matrix @ (qvector / np.linalg.norm(qvector))
        # Lexsort keeps a stable product-ID tie break for determinism.
        indices = np.lexsort((identifiers, -similarity))[:k]
        ids = identifiers[indices].tolist()
        shape_hits = sum(labels[pid]["figura"] == query["figura"] for pid in ids)
        color_hits = sum(labels[pid]["color"] == query["color"] for pid in ids)
        both_hits = sum(labels[pid]["figura"] == query["figura"] and labels[pid]["color"] == query["color"] for pid in ids)
        rows.append({"query": query["imagen"], "figura": query["figura"], "color": query["color"],
                     "precision_shape": shape_hits / k, "precision_color": color_hits / k,
                     "precision_both": both_hits / k,
                     "top1_shape": int(labels[ids[0]]["figura"] == query["figura"]),
                     "neighbors": " ".join(map(str,ids))})
    averages = {key: round(float(np.mean([row[key] for row in rows])), 4)
                for key in ("precision_shape", "precision_color", "precision_both", "top1_shape")}
    per_shape = defaultdict(list)
    for row in rows: per_shape[row["figura"]].append(row)
    summary = {"method": "exact cosine on BoVW (offline baseline; not IVF)", "products": len(products),
               "queries": len(queries), "k": k, "ground_truth": "most frequent geometric shape",
               "random_shape_baseline": round(1/len(set(row["figura"] for row in labels.values())),4),
               "averages": averages,
               "per_shape": {shape: {key: round(float(np.mean([row[key] for row in records])),4)
                     for key in averages} for shape,records in sorted(per_shape.items())}}
    output.mkdir(parents=True, exist_ok=True)
    with (output / "precision_queries.csv").open("w",encoding="utf-8",newline="") as f:
        writer = csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (output / "precision_summary.json").write_text(json.dumps(summary, indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset",type=Path,default=Path("data/geometric"))
    parser.add_argument("--output",type=Path,default=Path("benchmarks/results/geometric_exact"))
    parser.add_argument("--limit",type=int,default=None)
    parser.add_argument("--k",type=int,default=10)
    options = parser.parse_args(argv)
    print(json.dumps(evaluate(options.dataset, options.output,k=options.k,limit=options.limit), indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
