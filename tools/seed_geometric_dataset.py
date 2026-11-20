"""Importa figuras sintéticas al motor por API sin recalcular SIFT por INSERT.

Generar primero con tools.generate_geometric_dataset. Después, en una instancia
de backend VACÍA y con su mismo BD2_DATA_DIR:

    python -m tools.seed_geometric_dataset --data-dir backend/data

Los vectores fueron extraídos y entrenados una sola vez durante la generación;
el importador envía un CSV con embeddings por un único POST, copia las imágenes
y crea IVF. El vocabulario nunca se reemplaza sin permiso explícito.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import sys
import time
from pathlib import Path

from tools.generate_geometric_dataset import verify_dataset
from tools.seed_tienda import Api, SeedError, esperar_api

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = ROOT / "data" / "geometric"
INDEX_NAME = "idx_figuras_embedding"
INDEX_SQL = f"CREATE INDEX {INDEX_NAME} ON figuras (embedding) USING IVF WITH METRIC=cosine"


def _copy_if_changed(source: Path, target: Path) -> None:
    if target.exists() and filecmp.cmp(source, target, shallow=False):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def seed(api: Api, dataset: Path, data_dir: Path, *, espera: float = 120,
         replace_model: bool = False) -> dict:
    start = time.perf_counter()
    dataset = Path(dataset)
    data_dir = Path(data_dir)
    integrity = verify_dataset(dataset)
    esperar_api(api, espera)

    source_model = dataset / "modelo" / "bow_image.npz"
    target_model = data_dir / "models" / "bow_image.npz"
    if target_model.exists() and not filecmp.cmp(source_model, target_model, shallow=False):
        if not replace_model:
            raise SeedError("ya existe otro vocabulario de imágenes; utiliza una BD2_DATA_DIR "
                            "vacía para las figuras o --replace-model (invalida vectores previos)")
        print("ADVERTENCIA: se reemplazará el vocabulario de imágenes anterior", file=sys.stderr)

    tables = {t["name"]: t for t in api.get("/api/tables")}
    if "figuras" in tables:
        count = int(tables["figuras"]["row_count"])
        if count != integrity["products"]:
            raise SeedError(f"tabla figuras existente con {count} registros, "
                            f"se esperaban {integrity['products']}; usa una base vacía")

    _copy_if_changed(source_model, target_model)
    media = data_dir / "media"
    for folder in ("imagenes", "consultas"):
        for path in sorted((dataset / folder).glob("*.png")):
            _copy_if_changed(path, media / path.name)

    if "figuras" not in tables:
        csv_data = (dataset / "productos_indexados.csv").read_bytes()
        response = api.post_form("/api/tables/import", {
            "name": "figuras", "primary_key": "id", "storage_kind": "heap",
        }, ("productos_indexados.csv", csv_data))
        count = int(response["imported_rows"])
        if count != integrity["products"]:
            raise SeedError(f"importó {count} filas, se esperaban {integrity['products']}")
    else:
        print(f"figuras: {integrity['products']} filas existentes (sin duplicación)")

    table = next(t for t in api.get("/api/tables") if t["name"] == "figuras")
    if not any(index["name"] == INDEX_NAME for index in table["indexes"]):
        api.sql(INDEX_SQL)
    result = api.sql("SELECT id, categoria, imagen FROM figuras WHERE id = 1")
    if not result["rows"]:
        raise SeedError("la primera figura no es consultable tras importar")
    return {**integrity, "table": "figuras", "index": INDEX_NAME,
            "elapsed_seconds": round(time.perf_counter() - start, 2)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--api", default=os.environ.get("BD2_API_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("BD2_DATA_DIR") or ROOT / "backend" / "data"))
    parser.add_argument("--espera", type=float, default=120)
    parser.add_argument("--replace-model", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = seed(Api(args.api), args.dataset, args.data_dir,
                      espera=args.espera, replace_model=args.replace_model)
    except (SeedError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
