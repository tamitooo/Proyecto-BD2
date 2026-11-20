"""Basket-aware Precision@10 for BD2 Part 5 (#141).

Ground truth: the OTHER products purchased by the SAME user on the SAME day.
Train co-purchases on disjoint USERS in five deterministic folds; never let a
held-out user's purchased products inform the recommendation score. Static
content features (metadata, BM25-equivalent, exact cosine) use catalog-only data.

This is an OFFLINE reference evaluation; visual uses exact cosine, NOT SQL/IVF.
No claim of SQL runtime speed or real Amazon/Flipkart data is made.

Usage (from repository root):
  python -m benchmarks.p5_precision_por_fuente \\
    --products examples/tienda/productos.csv \\
    --purchases examples/tienda/compras.csv \\
    --output benchmarks/results/parte5
  python -m benchmarks.p5_precision_por_fuente \\
    --products BD2_Badi_Demo_Data/data/part5_synthetic/productos.csv \\
    --purchases BD2_Badi_Demo_Data/data/part5_synthetic/compras.csv \\
    --indexed BD2_Badi_Demo_Data/data/part5_synthetic/productos_indexados.csv \\
    --limit 300 --output benchmarks/results/parte5
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import math
from collections import defaultdict
from pathlib import Path

from benchmarks.benchmark_part5_precision import Sources, fusion, precision, read_products

SOURCES = ("co_compra", "metadatos", "descripcion", "visual")
ALIAS = {"co_compra": "Co-compra", "metadatos": "Metadatos", "descripcion": "Descripcion", "visual": "Visual (coseno)", "fusion_igual": "Fusion: pesos iguales", "fusion_cocompra": "Fusion: solo co-compra", "fusion_validada": "Fusion: pesos seleccionados en entrenamiento"}


def baskets_from_csv(path: Path, products: set[int]) -> tuple[dict[tuple[int, str], set[int]], int]:
    baskets: dict[tuple[int, str], set[int]] = defaultdict(set)
    ids: set[int] = set()
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"id", "usuario_id", "producto_id", "fecha", "cantidad"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"compras.csv needs columns {sorted(required)}")
        for r in reader:
            tx, u, pid = int(r["id"]), int(r["usuario_id"]), int(r["producto_id"])
            if tx in ids: raise ValueError(f"repeated purchase id: {tx}")
            if pid not in products: raise ValueError(f"product {pid} not in catalog")
            if int(r["cantidad"]) <= 0: raise ValueError(f"nonpositive purchase quantity for {tx}")
            if not r["fecha"].strip(): raise ValueError(f"missing date for {tx}")
            ids.add(tx)
            baskets[(u, r["fecha"].strip())].add(pid)
    return dict(baskets), len(ids)


def cases_from_baskets(baskets: dict[tuple[int, str], set[int]]) -> list[dict]:
    cases = []
    for (u, date), basket in sorted(baskets.items()):
        if len(basket) < 2: continue
        for anchor in sorted(basket):
            cases.append({"user": u, "date": date, "anchor": anchor,
                          "relevant": frozenset(basket - {anchor})})
    return cases


def folds_by_user(users: set[int], k: int, seed: int) -> list[set[int]]:
    if k < 2 or len(users) < k: raise ValueError("need >= 2 folds and at least k distinct users")
    shuf = sorted(users)
    random.Random(seed).shuffle(shuf)
    return [set(shuf[i::k]) for i in range(k)]



def extra_metrics(ranked: list[int], relevant: frozenset[int], catalog_count: int, k: int = 10) -> dict:
    """All denominators fixed; no artificial padding of ground truth.

    The random Precision baseline assumes uniformly sampling min(k,N-1)
    items without replacement from the N-1 possible recommendations.
    """
    if k < 1 or catalog_count < 2:
        raise ValueError('invalid k/catalog_count')
    top=list(ranked[:k])
    if len(top)!=len(set(top)):
        raise ValueError('duplicate ranked ids')
    hits=[1 if p in relevant else 0 for p in top]
    num=sum(hits)
    # Ranking ceiling includes k and catalog size, but not padded results.
    upper=min(k, len(relevant), catalog_count-1)/k
    discount=sum(1/math.log2(i+2) for i,h in enumerate(hits) if h)
    ideal=sum(1/math.log2(i+2) for i in range(min(k,len(relevant))))
    return {
        'precision_at_k': num/k,
        'recall_at_k': num/len(relevant) if relevant else 0.0,
        'hit_rate_at_k':float(num>0),
        'ndcg_at_k':discount/ideal if ideal else 0.0,
        'mrr_at_k':next((1/(i+1) for i,h in enumerate(hits) if h),0.0),
        'p_at_3':sum(hits[:3])/3,
        'max_precision_at_k':upper,
        'random_precision_at_k':min(k,catalog_count-1)/k*len(relevant)/(catalog_count-1),
        'hits':num,
        'opportunities':min(k,len(relevant)),
    }


def candidate_weights(sources: list[str]) -> dict[str,dict[str,float]]:
    """Small, predetermined grid, not chosen on held-out test cases."""
    defaults={s:1.0 for s in sources}
    choices={'equal':defaults,
             'co_only':{s:(1.0 if s=='co_compra' else 0.0) for s in sources},
             'co_strong':{s:(3.0 if s=='co_compra' else 1.0) for s in sources},
             'co_text':{s:(2.0 if s=='co_compra' else (1.0 if s=='descripcion' else 0.0)) for s in sources}}
    return choices


def choose_weights(products:dict, baskets:dict, outer_users:set[int], *,
                   indexed_csv:Path|None, sources:list[str], k:int,
                   candidate_k:int, seed:int) -> tuple[str,dict[str,float],dict[str,float]]:
    """3-fold inner user CV: never optimize on users from outer test fold."""
    candidates=candidate_weights(sources)
    if len(outer_users)<3:
        return 'equal',candidates['equal'],{}
    inner=folds_by_user(outer_users,3,seed)
    raw={name:[] for name in candidates}
    for hold in inner:
        training=[{'user':u,'product':pid}
                  for (u,date),basket in baskets.items() if u in outer_users and u not in hold for pid in basket]
        model=Sources(products,training,indexed=indexed_csv)
        cache={}
        inner_cases=cases_from_baskets({b:v for b,v in baskets.items() if b[0] in hold})
        random.Random(seed + len(hold)).shuffle(inner_cases)
        for c in inner_cases[:80]:
            if c['anchor'] not in cache:
                cache[c['anchor']]={src:model.recommend(c['anchor'],src,top=candidate_k) for src in sources}
            scores=cache[c['anchor']]
            for name,weights in candidates.items():
                found=fusion(c['anchor'],scores,k=k,weights=weights)
                raw[name].append(extra_metrics(found,c['relevant'],len(products),k)['precision_at_k'])
    score={name:sum(values)/len(values) if values else 0.0 for name,values in raw.items()}
    # Deterministic tie break: prefer equal weights (less brittle), then mixed.
    priority=['equal','co_strong','co_text','co_only']
    best=max(priority,key=lambda name:(score[name],-priority.index(name)))
    return best,candidates[best],{name:round(v,6) for name,v in score.items()}

def evaluate(products_csv: Path, purchases_csv: Path, output: Path, *,
             indexed_csv: Path | None = None, folds: int = 5,
             seed: int = 2026, limit: int | None = 300, top_k: int = 10,
             candidate_k: int = 10, render_chart: bool = True) -> dict:
    if top_k < 1 or candidate_k < top_k: raise ValueError("invalid top_k/candidate_k")
    if limit is not None and limit <= 0: raise ValueError("limit must be positive")
    products = read_products(Path(products_csv))
    baskets, total_purchase_rows = baskets_from_csv(Path(purchases_csv), set(products))
    cases = cases_from_baskets(baskets)
    if not cases: raise ValueError("no baskets with 2+ distinct products")
    users = {u for u, _ in baskets}
    user_folds = folds_by_user(users, folds, seed)
    # Deterministic random case sample, not the first 300 product IDs.
    # A user remains wholly in one training/test fold.
    rng = random.Random(seed + 1)
    rng.shuffle(cases)
    if limit is not None: cases = cases[:limit]
    used_sources = list(SOURCES if indexed_csv else SOURCES[:3])
    methods = used_sources + ["fusion_igual", "fusion_cocompra", "fusion_validada"]
    observations = {m: [] for m in methods}
    detailed = []
    train_test = []
    for fold_id, held_users in enumerate(user_folds, 1):
        training = [{"user": u, "product": pid} for (u, date), basket in baskets.items()
                    if u not in held_users for pid in basket]
        test = [c for c in cases if c["user"] in held_users]
        if not test: continue
        # All model selection is nested inside the outer training users.
        learned_name, learned_weights, inner_scores=choose_weights(
            products,baskets,users-held_users,indexed_csv=indexed_csv,
            sources=used_sources,k=top_k,candidate_k=candidate_k,seed=seed+fold_id)
        source_model = Sources(products, training, indexed=indexed_csv)
        train_test.append({"fold": fold_id, "train_users": len(users - held_users),
                           "test_users": len(held_users), "test_cases": len(test),
                           "chosen_model":learned_name,"chosen_weights":learned_weights,
                           "inner_cv_precision":inner_scores})
        # Request each candidate source as the app does. Source data is cached
        # only within a fold: no transactions from held-out users are used.
        cache = {}
        for c in test:
            anchor = c["anchor"]
            if anchor not in cache:
                cache[anchor] = {s: source_model.recommend(anchor, s, top=candidate_k) for s in used_sources}
            predictions = cache[anchor]
            equal = fusion(anchor, predictions, k=top_k)
            co_only = [pid for pid, _ in predictions["co_compra"][:top_k]]
            per_method = {s: [pid for pid, _ in predictions[s][:top_k]] for s in used_sources}
            per_method.update(fusion_igual=equal, fusion_cocompra=co_only,
                              fusion_validada=fusion(anchor,predictions,k=top_k,weights=learned_weights))
            for method, ids in per_method.items():
                value = extra_metrics(ids,c["relevant"],len(products),k=top_k)
                observations[method].append(value)
                detailed.append({"fold": fold_id, "usuario": c["user"], "fecha": c["date"],
                                 "producto_X": anchor, "relevantes": " ".join(map(str, sorted(c["relevant"]))),
                                 "fuente": method, "precision_at_10": value["precision_at_k"],
                                 "recall_at_10": value["recall_at_k"], "hit_at_10": int(value["hit_rate_at_k"]),
                                 "p_at_3":value["p_at_3"],"ndcg_at_k":value["ndcg_at_k"],
                                 "mrr_at_k":value["mrr_at_k"],
                                 "max_precision_at_k":value["max_precision_at_k"],
                                 "random_precision_at_k":value["random_precision_at_k"],
                                 "hits":value["hits"],"opportunities":value["opportunities"],
                                 "recomendados": " ".join(map(str, ids))})
    if not observations["fusion_igual"]: raise ValueError("no test cases selected")
    summary = []
    for method in methods:
        vals = observations[method]
        summary.append({"source": method, "label": ALIAS[method], "queries": len(vals),
                        "k": top_k,
                        "precision_at_k": round(sum(v["precision_at_k"] for v in vals)/len(vals), 6),
                        "recall_at_k": round(sum(v["recall_at_k"] for v in vals)/len(vals), 6),
                        "hit_rate_at_k": round(sum(v["hit_rate_at_k"] for v in vals)/len(vals), 6),
                        "p_at_3":round(sum(v["p_at_3"] for v in vals)/len(vals),6),
                        "ndcg_at_k":round(sum(v["ndcg_at_k"] for v in vals)/len(vals),6),
                        "mrr_at_k":round(sum(v["mrr_at_k"] for v in vals)/len(vals),6),
                        "coverage_at_k":round(len({p for d in detailed if d["fuente"]==method for p in map(int,d["recomendados"].split())})/len(products),6),
                        "total_hits":sum(v["hits"] for v in vals)})
    dest = Path(output);dest.mkdir(parents=True, exist_ok=True)
    def csv_out(name, rows):
        with (dest / name).open('w', encoding='utf-8', newline='') as f:
            writer=csv.DictWriter(f, fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    csv_out('p5_precision_por_fuente.csv', summary)
    csv_out('p5_precision_casos.csv', detailed)
    report = {"protocol":"Same user+date basket; every other DISTINCT product is relevant",
              "leakage_prevention":"5fold held-out USERS; co-purchase trained only on other users",
              "evaluation_scope":"OFFLINE: BM25 reference + exact cosine, not live SQL/IVF",
              "dataset_kind":"fixture or user-supplied; does not establish real Amazon/Flipkart provenance",
              "seed":seed,"products":len(products),"purchases":total_purchase_rows,
              "baskets":len(baskets),"eligible_cases":len(cases_from_baskets(baskets)),
              "evaluated_cases":len(observations["fusion_igual"]),"total_users":len(users),
              "folds":train_test,"visual_included":bool(indexed_csv),"results":summary,
              "max_precision_at_k":round(sum(v["max_precision_at_k"] for v in observations["fusion_igual"])/len(observations["fusion_igual"]),6),
              "expected_random_precision_at_k":round(sum(v["random_precision_at_k"] for v in observations["fusion_igual"])/len(observations["fusion_igual"]),6),
              "nested_cv_weights":True}
    (dest / 'p5_precision_por_fuente.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    lines = [
        '### Evaluación Precision@10 — cestas del mismo usuario y fecha',
        '',
        f'Catálogo evaluado: **{len(products)} productos**; **{total_purchase_rows} compras**; '
        f'**{len(observations["fusion_igual"])} casos** de evaluación; '
        f'**{folds} pliegues por usuario** (semilla {seed}).',
        '',
        '| Fuente | P@10 | Recall@10 | Hit@10 | P@3 | NDCG@10 |',
        '|---|---:|---:|---:|---:|---:|',
    ]
    for r in summary:
        lines.append(f'| {r["label"]} | {r["precision_at_k"]:.4f} | '
                     f'{r["recall_at_k"]:.4f} | {r["hit_rate_at_k"]:.4f} | '
                     f'{r["p_at_3"]:.4f} | {r["ndcg_at_k"]:.4f} |')
    lines += [
        '',
        '![Precision@10 por fuente](../../benchmarks/results/parte5/p5_precision_por_fuente.png)',
        '',
        f'**Máximo P@{top_k} bajo esta relevancia:** {report["max_precision_at_k"]:.4f}; '
        f'**azar esperado:** {report["expected_random_precision_at_k"]:.4f}. '
        'Estos valores impiden interpretar P@10 como porcentaje de acierto general.',
        '',
        '**Validación de pesos:** los pesos de fusion_validada se seleccionan en '
        'una validación interna por usuarios de ENTRENAMIENTO (no en test). '
        'El modelo final de la aplicación se debe reentrenar por separado.',
        '',
        '**Protocolo:** relevante = otros productos distintos de la misma cesta '
        '(mismo usuario y fecha). La co-compra se entrena con usuarios distintos '
        'de los evaluados para evitar fuga de datos.',
        '',
        '**Limitación:** referencia offline (BM25 aproximado y coseno exacto), '
        'no medición de ejecución SQL/IVF del motor. No presupone productos '
        'Amazon/Flipkart auténticos.' if indexed_csv else
        '**Limitación:** no se incluyó búsqueda visual porque no se entregaron '
        'embeddings visuales del catálogo; no se debe reportar esta fuente como 0. '
        'Las otras fuentes son offline, no SQL/IVF real.',
        '',
    ]
    (dest / 'p5_precision_para_informe.md').write_text('\n'.join(lines), encoding='utf-8')
    if render_chart:
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            vals=[r['precision_at_k'] for r in summary]
            names=[r['label'] for r in summary]
            fig,ax=plt.subplots(figsize=(10,5.2))
            bars=ax.bar(range(len(vals)), vals)
            ax.set_xticks(range(len(vals)), names, rotation=16, ha='right')
            ax.set_ylabel(f'Precision@{top_k}')
            ax.set_title(f'Part 5 — basket labels, {len(observations["fusion_igual"])} cases, {len(products)} products')
            ax.set_ylim(0, max(0.0015,max(vals)*1.35))
            for bar,n in zip(bars,vals):
                ax.text(bar.get_x()+bar.get_width()/2,bar.get_height()+max(vals)*.02, f'{n:.4f}',ha='center',fontsize=9)
            fig.tight_layout()
            fig.savefig(dest/'p5_precision_por_fuente.png',dpi=155)
            plt.close(fig)
        except ImportError:
            print('matplotlib not installed: CSV/JSON written but PNG skipped')
    print(json.dumps({"products": report["products"], "purchases":report["purchases"],
                      "evaluated_cases":report["evaluated_cases"],"visual":report["visual_included"],
                      "results":[{r['source']:r['precision_at_k']} for r in summary],"output":str(dest)},
                     ensure_ascii=False,indent=2))
    return report


def main(argv=None):
    a=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument('--products', type=Path,required=True)
    a.add_argument('--purchases',type=Path,required=True)
    a.add_argument('--indexed',type=Path,default=None)
    a.add_argument('--output',type=Path,default=Path('benchmarks/results/parte5'))
    a.add_argument('--folds',type=int,default=5)
    a.add_argument('--seed',type=int,default=2026)
    a.add_argument('--limit',type=int,default=300,help='Randomly sampled basket cases, 0 for all cases')
    a.add_argument('--candidate-k',type=int,default=10)
    a.add_argument('--k',type=int,default=10)
    args=a.parse_args(argv)
    evaluate(args.products,args.purchases,args.output,indexed_csv=args.indexed,
             folds=args.folds,seed=args.seed,
             limit=None if args.limit==0 else args.limit,candidate_k=args.candidate_k,top_k=args.k)


if __name__=='__main__': main()
