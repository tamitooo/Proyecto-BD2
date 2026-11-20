"""Evaluate original-song excerpt identification using held-out TIME windows.

The source song identity remains in the indexed database: this evaluates whether
an independent cropped query excerpt retrieves its own song, NOT recognition of
unseen music or copyright ownership. Reports top-1, recall@5, MRR and silence.

    python -m tools.evaluate_music20 --dataset data/music20 --limit 100
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from audio_recognition.temporal import RATE, match_audio, query_candidates, read_wav_bytes


def evaluate(dataset: Path, *, limit: int | None = None, k: int = 5,
             candidate_k: int = 40) -> dict:
    dataset = Path(dataset)
    with (dataset / "catalog.csv").open(encoding="utf-8", newline="") as f:
        catalog = list(csv.DictReader(f))
    with np.load(dataset / "audio_index.npz", allow_pickle=False) as data:
        emb, ids, secs = (data[key].copy() for key in ("embedding", "track_id", "segundo"))
        mean, std = data["mean"].copy(), data["std"].copy()
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        catalog = catalog[:limit]
    if not catalog:
        raise ValueError("no indexed audio tracks")
    results = []
    for row in catalog:
        sound = read_wav_bytes((dataset / "media" / row["audio"]).read_bytes())
        # Query samples are cropped independently, with two seconds muted to
        # make the test silence-aware. The first 4 seconds are omitted.
        query = sound[4*RATE:16*RATE].copy()
        query[3*RATE:5*RATE] = 0
        output = match_audio(query, mean=mean, std=std,
            candidate_provider=lambda vectors: query_candidates(emb, ids, secs, vectors, k=candidate_k),
            top_k=k, min_similarity=.50)
        predicted = [m["track_id"] for m in output["matches"]]
        answer = int(row["id"])
        rank = predicted.index(answer) + 1 if answer in predicted else 0
        results.append({"id": answer, "genre": row["genre"], "rank": rank,
                        "correct_at_1": int(rank == 1), "hit_at_5": int(0 < rank <= 5),
                        "reciprocal_rank": 1/rank if rank else 0,
                        "active_seconds": output["active_seconds"],
                        "silent_seconds": output["silent_seconds"]})
    count = len(results)
    report = {"queries": count, "top1_accuracy": sum(x["correct_at_1"] for x in results)/count,
              "recall_at_5": sum(x["hit_at_5"] for x in results)/count,
              "mean_reciprocal_rank": sum(x["reciprocal_rank"] for x in results)/count,
              "protocol": "12s crops from indexed 20s clips; 2 silent seconds; exact cosine baseline",
              "limitations": "queries derived from indexed songs, not independent unseen recordings; SQL IVF not measured"}
    output = dataset / "evaluation"
    output.mkdir(exist_ok=True)
    with (output / "results.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0])); writer.writeheader(); writer.writerows(results)
    (output / "summary.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0]);
    p.add_argument('--dataset',type=Path,default=Path('data/music20'))
    p.add_argument('--limit',type=int)
    args=p.parse_args(argv)
    print(json.dumps(evaluate(args.dataset,limit=args.limit),indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
