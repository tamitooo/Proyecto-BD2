"""Load a full Part-5 store dataset through the existing API in bulk.

Requires six-column productos.csv + productos_indexados.csv (pretrained BoVW)
+ imagenes/, modelo/bow_image.npz, tiendas.csv, stock.csv, compras.csv.
All imports use the existing /api/tables/import endpoint, avoiding thousands of
individual EXTRACT_FEATURES SQL INSERT calls. No destructive table replacement.

    python -m tools.seed_part5_fast --dataset data/part5_synthetic --data-dir backend/data

Use a fresh BD2_DATA_DIR for reproducible results; the model is shared across
all image tables and is never overwritten when different.
"""
from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from tools.generate_part5_data import verify
from tools.seed_tienda import Api, SeedError, esperar_api

ROOT = Path(__file__).resolve().parents[1]
INDEXES = (
    ("productos", "idx_productos_embedding",
     "CREATE INDEX idx_productos_embedding ON productos (embedding) USING IVF WITH METRIC=cosine"),
    ("tiendas", "idx_tiendas_ubicacion",
     "CREATE INDEX idx_tiendas_ubicacion ON tiendas (lat, lon) USING RTREE"),
)


def _copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if not filecmp.cmp(src, dst, shallow=False):
            raise SeedError(f"refusing to overwrite existing media/model content: {dst}")
    else:
        shutil.copyfile(src, dst)


def _required(dataset: Path) -> None:
    for file in ("productos.csv", "productos_indexados.csv", "tiendas.csv", "stock.csv", "compras.csv",
                 "modelo/bow_image.npz"):
        if not (dataset / file).is_file():
            raise SeedError(f"missing required file: {dataset / file}")
    if not (dataset / "imagenes").is_dir():
        raise SeedError("missing required images directory")


def seed(api: Api, dataset: Path, data_dir: Path, *, timeout: float = 120) -> dict:
    start = time.perf_counter()
    dataset, data_dir = Path(dataset), Path(data_dir)
    _required(dataset)
    metadata = verify(dataset, image_dir=dataset / "imagenes")
    esperar_api(api, timeout)
    files = ("productos.csv", "productos_indexados.csv", "tiendas.csv", "stock.csv",
             "compras.csv", "modelo/bow_image.npz")
    fingerprint = hashlib.sha256()
    for name in files:
        fingerprint.update(name.encode() + b"\0")
        fingerprint.update((dataset / name).read_bytes())
    dataset_id = fingerprint.hexdigest()
    stamp = data_dir / ".part5_dataset_id"
    tables = {t["name"]: t for t in api.get("/api/tables")}
    known = {table for table in ("productos", "tiendas", "stock", "compras") if table in tables}
    if stamp.exists() and stamp.read_text(encoding="ascii").strip() != dataset_id:
        raise SeedError("dataset fingerprint differs from previous load; use a fresh BD2_DATA_DIR")
    if known and not stamp.exists():
        raise SeedError(f"existing Part 5 tables without a dataset fingerprint: {sorted(known)}; "
                        "use a fresh BD2_DATA_DIR to avoid mixing datasets")
    for table, target in (("productos", "products"), ("tiendas", "stores"),
                          ("stock", "stock"), ("compras", "purchases")):
        if table in tables and int(tables[table]["row_count"]) != metadata[target]:
            raise SeedError(f"existing {table} has {tables[table]['row_count']} records, "
                            f"dataset has {metadata[target]}; use a fresh data dir")

    model = dataset / "modelo" / "bow_image.npz"
    saved_model = data_dir / "models" / "bow_image.npz"
    if saved_model.exists() and not filecmp.cmp(model, saved_model, shallow=False):
        raise SeedError("a different BoVW model already exists; use a fresh BD2_DATA_DIR")
    _copy(model, saved_model)
    for image in (dataset / "imagenes").iterdir():
        if image.is_file():
            _copy(image, data_dir / "media" / image.name)

    csv_sources = (("tiendas", "tiendas.csv"), ("stock", "stock.csv"),
                   ("compras", "compras.csv"), ("productos", "productos_indexados.csv"))
    for name, file in csv_sources:
        if name not in tables:
            answer = api.post_form("/api/tables/import", {
                "name": name, "primary_key": "id", "storage_kind": "heap",
            }, (file, (dataset / file).read_bytes()))
            if int(answer["imported_rows"]) != metadata[{
                "productos": "products", "tiendas": "stores", "stock": "stock", "compras": "purchases",
            }[name]]:
                raise SeedError(f"incomplete CSV import for {name}")

    refreshed = {t["name"]: t for t in api.get("/api/tables")}
    for name, index, sql in INDEXES:
        if not any(entry["name"] == index for entry in refreshed[name]["indexes"]):
            api.sql(sql)

    # Confirm real query visibility, not just accepted HTTP responses.
    response = api.sql("SELECT id, imagen FROM productos WHERE id = 1")
    if not response["rows"]:
        raise SeedError("product 1 is missing after import")
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(dataset_id + "\n", encoding="ascii")
    return {**metadata, "elapsed_seconds": round(time.perf_counter() - start, 3),
            "indices": [item[1] for item in INDEXES]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dataset", type=Path, default=ROOT / "data" / "part5_synthetic")
    p.add_argument("--api", default=os.environ.get("BD2_API_URL", "http://127.0.0.1:8000"))
    p.add_argument("--data-dir", type=Path,
                   default=Path(os.environ.get("BD2_DATA_DIR") or ROOT / "backend" / "data"))
    p.add_argument("--timeout", type=float, default=120)
    args = p.parse_args(argv)
    try:
        result = seed(Api(args.api), args.dataset, args.data_dir, timeout=args.timeout)
    except (SeedError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
