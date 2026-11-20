"""Pure-data integrity, determinism, co-purchase and anti-leakage tests."""
from __future__ import annotations

import csv
import json
from collections import defaultdict

import pytest

from tools.generate_part5_data import (PRODUCT_FIELDS, generate, read_products, verify)
from benchmarks.benchmark_part5_precision import (Sources, evaluate, fusion,
                                                   precision, split_purchases)


@pytest.fixture
def product_csv(tmp_path):
    path = tmp_path / "products.csv"
    rows = []
    for i, (name, category) in enumerate(
        ([(f"Laptop {x}", "laptops") for x in range(1, 6)]
         + [(f"Mochila {x}", "mochilas") for x in range(1, 6)]
         + [(f"Celular {x}", "celulares") for x in range(1, 6)]
         + [(f"Audifono {x}", "audifonos") for x in range(1, 6)]), 1):
        rows.append([i, name, category, f"{100 + i * 7}.00",
                     f"{name} con características técnicas", f"producto_{i:03d}.png"])
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(PRODUCT_FIELDS)
        writer.writerows(rows)
    return path


def test_store_referential_integrity_and_stock_coverage(tmp_path, product_csv):
    out = tmp_path / "out"
    manifest = generate(products_csv=product_csv, output=out,
                        stores=30, users=70, purchases=280, seed=5)
    assert manifest["stores"] == 30
    assert verify(out) == {"products": 20, "stores": 30,
                           "stock": manifest["stock"], "purchases": 280, "users": 70}
    assert (out / "productos.csv").read_bytes() == product_csv.read_bytes()
    assert manifest["affinity_groups"] == [["laptops", "mochilas"], ["celulares", "audifonos"]] or len(manifest["affinity_groups"]) == 2
    assert not manifest["assets_copied"]


def test_deterministic_reproduction_and_different_seeds(tmp_path, product_csv):
    paths = [tmp_path / x for x in ("a", "b", "c")]
    for path, seed in zip(paths, (2026, 2026, 2027)):
        generate(products_csv=product_csv, output=path, stores=7,
                 users=20, purchases=80, seed=seed)
    for name in ("stock.csv", "compras.csv", "tiendas.csv"):
        assert (paths[0] / name).read_bytes() == (paths[1] / name).read_bytes()
    assert (paths[0] / "compras.csv").read_bytes() != (paths[2] / "compras.csv").read_bytes()


def test_purchase_affinities_are_meaningful(tmp_path, product_csv):
    out = tmp_path / "pairs"
    generate(products_csv=product_csv, output=out, stores=5,
             users=100, purchases=200, seed=9)
    by_id = {int(r["id"]): r["categoria"] for r in read_products(product_csv)}
    bought = defaultdict(set)
    with (out / "compras.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            bought[int(row["usuario_id"])].add(by_id[int(row["producto_id"])])
    assert len(bought) == 100
    assert all(categories in ({"laptops", "mochilas"}, {"celulares", "audifonos"})
               for categories in bought.values())


def test_corrupted_stock_and_purchase_are_rejected(tmp_path, product_csv):
    out = tmp_path / "corrupt"
    generate(products_csv=product_csv, output=out, stores=5, users=5, purchases=20)
    stock_file = out / "stock.csv"
    text = stock_file.read_text()
    stock_file.write_text(text.replace("1,1,", "1,999,", 1))
    with pytest.raises(ValueError, match="invalid/duplicated stock"):
        verify(out)


def test_corrupted_product_image_or_duplicate_id_rejected(tmp_path, product_csv):
    with product_csv.open("a", encoding="utf-8") as f:
        f.write('1,Bad,laptops,100,Desc,../unsafe.png\n')
    with pytest.raises(ValueError):
        read_products(product_csv)


def test_holdout_chronologically_excludes_labels_from_training(tmp_path, product_csv):
    out = tmp_path / "split"
    generate(products_csv=product_csv, output=out, stores=5, users=12, purchases=60)
    train, test = split_purchases(out / "compras.csv", set(range(1, 21)))
    assert len(test) == 12
    assert len(train) + len(test) == 60
    train_by_user = defaultdict(set)
    for row in train:
        train_by_user[row["user"]].add(row["product"])
    assert all(item["product"] not in train_by_user[item["user"]] for item in test)
    assert all(item["anchor"] in train_by_user[item["user"]] for item in test)


def test_precision_and_fusion_match_frontend_semantics():
    assert precision([1, 2, 3], {1, 3}, k=10) == {
        "precision": 0.2, "recall": 1.0, "hit_rate": 1.0,
    }
    assert fusion(1, {"a": [(1, 99), (2, 5), (3, 3)],
                      "b": [(3, 10), (2, 8)]}, k=3) == [2, 3]
    assert fusion(1, {"a": [], "b": []}) == []
    assert fusion(1, {"a": [(1, 100), (2, 7)]}) == [2]
    with pytest.raises(ValueError):
        precision([2, 2], {2}, k=10)


def test_end_to_end_precision_report_is_recomputed(tmp_path, product_csv):
    out = tmp_path / "store"
    generate(products_csv=product_csv, output=out, stores=5,
             users=50, purchases=150)
    result = evaluate(products_csv=out / "productos.csv", purchases_csv=out / "compras.csv",
                      output=tmp_path / "bench", k=10)
    assert result["train_purchases"] == 100
    assert result["held_out_purchases"] == 50
    assert set(result["sources"]) == {"co_compra", "metadatos", "descripcion"}
    assert result["distinct_queries"] > 0
    assert all(0 <= row["precision_at_k"] <= 1 for row in result["results"])
    assert (tmp_path / "bench" / "precision_comparison.png").is_file()
    payload = json.loads((tmp_path / "bench" / "precision_summary.json").read_text())
    assert payload["held_out_purchases"] == 50
