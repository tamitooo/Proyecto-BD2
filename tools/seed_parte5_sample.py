"""Carga la muestra de la Parte 5 en el ``data_dir`` del API.

Sirve para probar las fuentes de la Persona 4 (i, j, k) sin esperar el dataset
completo de la Persona 1.  La muestra es determinista y pequeña: 20 productos,
5 tiendas, 6 filas de stock y 20 compras.

Uso:

    python -m tools.seed_parte5_sample
    python -m tools.seed_parte5_sample --data-dir backend/data
    python -m tools.seed_parte5_sample --replace   # borra y recarga

Si el backend está corriendo, hay que reiniciarlo para que vea las tablas.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from backend.engine import DemoEngine
from recommender import (
    create_schema,
    recommend_by_copurchase,
    recommend_by_metadata,
    stores_with_product,
)
from recommender.fixture import load_sample


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        default=None,
        help="directorio de datos; por defecto BD2_DATA_DIR o backend/data",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="borra las filas de las cuatro tablas antes de cargar",
    )
    args = parser.parse_args()

    data_dir = (
        args.data_dir
        or os.environ.get("BD2_DATA_DIR")
        or str(Path(__file__).resolve().parent.parent / "backend" / "data")
    )
    engine = DemoEngine(data_dir=data_dir)
    create_schema(engine)
    inserted = load_sample(engine, replace=args.replace)
    print(json.dumps({"data_dir": str(data_dir), "insertadas": inserted}, ensure_ascii=False))

    print("\nCo-compra del producto 1:")
    for item in recommend_by_copurchase(engine, 1, k=3):
        print(" ", item.as_dict())

    print("\nMetadatos del producto 1:")
    for item in recommend_by_metadata(engine, 1, k=3):
        print(" ", item.as_dict())

    print("\nTiendas con el producto 1 a menos de 3 km del centro de Lima:")
    for store in stores_with_product(engine, 1, (-12.0464, -77.0428), radius_m=3000):
        print(" ", store.as_dict())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
