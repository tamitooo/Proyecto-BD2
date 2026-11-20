"""Reproducible purchase hold-out benchmark for Part 5 recommendation sources.

One purchase (last chronologically) is withheld per eligible user. Every
recommendation source is trained from ONLY the remaining purchases; the
withheld items form independent query relevance labels. No future test rows
are used by the co-purchase source.

This is an OFFLINE reference implementation, not a claim about engine/IVF
runtime speed: descriptions use BM25-equivalent lexical scoring and visual
similarity uses exact cosine on the saved product embeddings. The source
ranking and fusion weights can be compared with the online recommender.

    python -m benchmarks.benchmark_part5_precision \\
        --products data/part5_synthetic/productos.csv \\
        --purchases data/part5_synthetic/compras.csv \\
        --indexed data/geometric/productos_indexados.csv \\
        --output benchmarks/results/parte5 --limit 250
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

SOURCES = ("co_compra", "metadatos", "descripcion", "visual")
TOKEN = re.compile(r"[a-z0-9áéíóúñü]+", re.IGNORECASE)


def _load(path: Path) -> list[dict]:
    with Path(path).open("r", newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def _tokens(s: str) -> list[str]:
    return TOKEN.findall(s.casefold())


def read_products(path: Path) -> dict[int, dict]:
    from tools.generate_part5_data import PRODUCT_FIELDS
    rows = _load(path)
    if not rows or tuple(rows[0]) != PRODUCT_FIELDS:
        raise ValueError("products.csv must use the six-column store schema")
    data = {}
    for row in rows:
        pid = int(row["id"])
        if pid in data:
            raise ValueError(f"duplicated product {pid}")
        row["precio"] = float(row["precio"])
        data[pid] = row
    return data


def split_purchases(path: Path, product_ids: set[int]) -> tuple[list[dict], list[dict]]:
    """Chronological user-level leave-last-one-out split; no random leakage."""
    from tools.generate_part5_data import PURCHASE_FIELDS
    data = _load(path)
    if not data or tuple(data[0]) != PURCHASE_FIELDS:
        raise ValueError("compras.csv must use the store schema")
    per_user = defaultdict(list)
    seen = set()
    for row in data:
        uid = int(row["usuario_id"])
        pid = int(row["producto_id"])
        purchase_id = int(row["id"])
        if pid not in product_ids or purchase_id in seen:
            raise ValueError(f"invalid product FK or repeated purchase PK: {purchase_id}")
        seen.add(purchase_id)
        per_user[uid].append((row["fecha"], purchase_id, uid, pid))
    train, test = [], []
    for uid, sequence in sorted(per_user.items()):
        sequence.sort(key=lambda r: (r[0], r[1]))
        if len(sequence) < 2:
            train.extend({"user": uid, "product": r[3]} for r in sequence)
            continue
        train.extend({"user": uid, "product": r[3]} for r in sequence[:-1])
        test.append({"user": uid, "product": sequence[-1][3],
                     "anchor": sequence[-2][3]})
    return train, test


class Sources:
    def __init__(self, products: dict[int, dict], purchases: list[dict], indexed: Path | None = None):
        self.products = products
        self.user_products = defaultdict(set)
        self.product_users = defaultdict(set)
        for p in purchases:
            uid, pid = int(p["user"]), int(p["product"])
            self.user_products[uid].add(pid)
            self.product_users[pid].add(uid)
        self.doc_counts = {pid: Counter(_tokens(row["descripcion"])) for pid, row in products.items()}
        self.avg_len = sum(sum(c.values()) for c in self.doc_counts.values()) / len(products)
        self.df = Counter(word for bag in self.doc_counts.values() for word in bag)
        self.matrix = None
        self.indexed_ids = []
        if indexed is not None:
            rows = _load(indexed)
            if not rows or "embedding" not in rows[0]:
                raise ValueError("indexed CSV requires embedding column")
            vectors, ids, size = [], [], None
            for row in rows:
                pid = int(row["id"])
                if pid not in products:
                    raise ValueError(f"indexed product ID unknown: {pid}")
                v = np.asarray(json.loads(row["embedding"]), dtype=np.float64)
                if v.ndim != 1 or not np.isfinite(v).all() or not np.linalg.norm(v):
                    raise ValueError(f"invalid visual vector for product {pid}")
                if size is None:
                    size = len(v)
                elif len(v) != size:
                    raise ValueError("inconsistent image embedding sizes")
                ids.append(pid)
                vectors.append(v / np.linalg.norm(v))
            if len(set(ids)) != len(ids):
                raise ValueError("duplicated indexed image product ID")
            if set(ids) != set(products):
                raise ValueError("indexed product IDs differ from catalog")
            self.indexed_ids = ids
            self.matrix = np.stack(vectors)
            self.row_for_id = {pid: row for row, pid in enumerate(ids)}

    def recommend(self, pid: int, source: str, *, top: int = 50) -> list[tuple[int, float]]:
        if source == "co_compra":
            buyers = self.product_users.get(pid, set())
            if not buyers:
                return []
            hits = Counter(candidate for user in buyers
                           for candidate in self.user_products[user] if candidate != pid)
            scores = {p: count / len(buyers) for p, count in hits.items()}
        elif source == "metadatos":
            item = self.products[pid]
            category, price = item["categoria"], float(item["precio"])
            denom = max(abs(price), 1.0)
            scores = {p: 1.0 / (1.0 + abs(float(row["precio"]) - price) / denom)
                      for p, row in self.products.items()
                      if p != pid and row["categoria"] == category}
        elif source == "descripcion":
            # BM25 uses the anchor's description tokens, not its product category label.
            words = set(self.doc_counts[pid])
            scores = {}
            for other, freq in self.doc_counts.items():
                if other == pid:
                    continue
                length = sum(freq.values())
                value = 0.0
                for word in words:
                    if not freq[word]:
                        continue
                    idf = math.log1p((len(self.products) - self.df[word] + 0.5) / (self.df[word] + 0.5))
                    tf = freq[word]
                    value += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / self.avg_len))
                if value:
                    scores[other] = value
        elif source == "visual":
            if self.matrix is None or pid not in self.row_for_id:
                return []
            similarities = self.matrix @ self.matrix[self.row_for_id[pid]]
            scores = {p: float(similarities[i]) for i, p in enumerate(self.indexed_ids)
                      if p != pid and np.isfinite(similarities[i])}
        else:
            raise ValueError(f"unknown source: {source}")
        return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:top]


def fusion(anchor: int, per_source: dict[str, list[tuple[int, float]]], k: int = 10,
           weights: dict[str, float] | None = None) -> list[int]:
    """Match frontend/src/tienda/fusion.ts: min-max scores + weighted sum."""
    weights = weights or {}
    active = [name for name in per_source if weights.get(name, 1) > 0]
    total = sum(weights.get(name, 1) for name in active)
    scores = defaultdict(float)
    contributors = defaultdict(set)
    if total <= 0:
        return []
    for name in active:
        data = {}
        for pid, score in per_source[name]:
            if pid != anchor and math.isfinite(score):
                data[pid] = max(data.get(pid, float("-inf")), score)
        if not data:
            continue
        lo, hi = min(data.values()), max(data.values())
        span = hi - lo
        weight = weights.get(name, 1) / total
        for pid, score in data.items():
            scores[pid] += weight * ((score - lo) / span if span > 0 else 1)
            contributors[pid].add(name)
    return sorted(scores, key=lambda pid: (-scores[pid], -len(contributors[pid]), pid))[:k]


def precision(ids: list[int], relevant: set[int], k: int = 10) -> dict[str, float]:
    if k < 1:
        raise ValueError("k must be positive")
    top = ids[:k]
    if len(top) != len(set(top)):
        raise ValueError("duplicate recommendations")
    hits = len(set(top) & relevant)
    return {"precision": hits / k, "recall": hits / len(relevant) if relevant else 0.0,
            "hit_rate": float(hits > 0)}


def evaluate(*, products_csv: Path, purchases_csv: Path, output: Path,
             indexed_csv: Path | None = None, k: int = 10,
             limit: int | None = None, candidate_k: int = 50) -> dict:
    if k < 1 or candidate_k < k:
        raise ValueError("k >= 1 and candidate_k >= k required")
    products = read_products(products_csv)
    train, test = split_purchases(purchases_csv, set(products))
    if not test:
        raise ValueError("no users with at least two purchases to evaluate")
    # The query is an observed TRAIN product X, and the ground truth is a
    # withheld TEST product Y bought by the same users. Aggregate by X.
    relevant = defaultdict(set)
    for row in test:
        relevant[row["anchor"]].add(row["product"])
    anchors = sorted(relevant)
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        anchors = anchors[:limit]
    scorer = Sources(products, train, indexed=indexed_csv)
    sources = [s for s in SOURCES if s != "visual" or indexed_csv is not None]
    metrics = defaultdict(list)
    details = []
    for anchor in anchors:
        candidates = {source: scorer.recommend(anchor, source, top=candidate_k) for source in sources}
        candidates["fusion"] = [(pid, 1.0) for pid in fusion(anchor, candidates, k=k)]
        for name, ranking in candidates.items():
            predicted = [int(pid) for pid, _ in ranking[:k]]
            if anchor in predicted:
                raise ValueError("source recommended its own anchor")
            values = precision(predicted, relevant[anchor], k=k)
            metrics[name].append(values)
            details.append({"anchor": anchor, "source": name,
                            "relevant_count": len(relevant[anchor]),
                            "precision_at_k": values["precision"],
                            "recall_at_k": values["recall"],
                            "hit_rate_at_k": values["hit_rate"],
                            "recommended_ids": " ".join(map(str, predicted))})
    summary = []
    for name, observations in metrics.items():
        summary.append({"source": name, "queries": len(observations), "k": k,
                        "precision_at_k": round(sum(x["precision"] for x in observations) / len(observations), 6),
                        "recall_at_k": round(sum(x["recall"] for x in observations) / len(observations), 6),
                        "hit_rate_at_k": round(sum(x["hit_rate"] for x in observations) / len(observations), 6)})
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name, rows in (("precision_queries.csv", details), ("precision_results.csv", summary)):
        with (output / name).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    report = {"products": len(products), "total_purchases": len(train) + len(test),
              "train_purchases": len(train), "held_out_purchases": len(test),
              "distinct_queries": len(anchors), "sources": sources,
              "k": k, "candidate_k": candidate_k,
              "protocol": "last chronological purchase per user is withheld; no held-out rows in co-purchase",
              "engine_caveat": "offline BM25 reference and exact cosine, not SQL/IVF speed or runtime",
              "results": summary}
    (output / "precision_summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                                   encoding="utf-8")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.bar([x["source"] for x in summary], [x["precision_at_k"] for x in summary])
        ax.set_ylim(0, max(0.1, min(1.0, max(x["precision_at_k"] for x in summary) * 1.2)))
        ax.set_ylabel(f"Precision@{k}")
        ax.set_title(f"Part 5 purchase hold-out: {len(anchors)} queries, {len(products)} products")
        fig.tight_layout()
        fig.savefig(output / "precision_comparison.png", dpi=140)
        plt.close(fig)
    except ImportError:
        pass
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--products", required=True, type=Path)
    p.add_argument("--purchases", required=True, type=Path)
    p.add_argument("--indexed", type=Path)
    p.add_argument("--output", type=Path, default=Path("benchmarks/results/parte5"))
    p.add_argument("--k", type=int, default=10)
    p.add_argument("--candidate-k", type=int, default=50)
    p.add_argument("--limit", type=int)
    args = p.parse_args(argv)
    result = evaluate(products_csv=args.products, purchases_csv=args.purchases,
                      indexed_csv=args.indexed, output=args.output,
                      k=args.k, candidate_k=args.candidate_k, limit=args.limit)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
