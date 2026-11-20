"""Non-destructive smoke tests for the installed datasets and running BD2 API.

Run AFTER the correct dataset has been imported and the API is running:

  python -m tools.verify_badi_release --mode store --dataset data/part5_synthetic
  python -m tools.verify_badi_release --mode geometric --dataset data/geometric

The mode must match the currently running BD2_DATA_DIR. Outputs JSON
including failures; exit code 1 if an acceptance check fails.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from tools.seed_tienda import Api


def _rows(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f))


def run(mode: str, dataset: Path, api_base: str = "http://127.0.0.1:8000") -> dict:
    if mode not in ("store", "geometric"):
        raise ValueError("mode must be store or geometric")
    from tools.generate_geometric_dataset import verify_dataset
    from tools.generate_part5_data import verify as verify_store

    api = Api(api_base)
    dataset = Path(dataset)
    checks = []
    def assert_check(name: str, operation) -> None:
        try:
            detail = operation()
            if detail is False:
                raise ValueError("returned False")
            checks.append({"name": name, "passed": True, "detail": detail if isinstance(detail,(str,int,float)) else None})
        except Exception as error:
            checks.append({"name": name, "passed": False, "error": str(error)})

    assert_check("dataset_csv_and_files", lambda: verify_dataset(dataset) if mode == "geometric" else verify_store(dataset,image_dir=dataset / "imagenes"))
    assert_check("api_health", lambda: api.get("/api/health")["status"] == "ok")
    table_name = "figuras" if mode == "geometric" else "productos"
    expected_index = "idx_figuras_embedding" if mode == "geometric" else "idx_productos_embedding"
    dataset_table = lambda: next(t for t in api.get("/api/tables") if t["name"] == table_name)
    expected_count = len(_rows(dataset / "productos.csv"))
    assert_check("table_row_count", lambda: int(dataset_table()["row_count"]) == expected_count)
    assert_check("persistent_ivf_index", lambda: any(i["name"] == expected_index and i["kind"].lower() == "ivf" for i in dataset_table()["indexes"]))

    def query(sql, columns=None):
        result = api.sql(sql)
        rows = result["rows"]
        if not rows: raise ValueError(f"empty SQL result: {sql}")
        if columns and not all(c in rows[0] for c in columns):
            raise ValueError("columns missing from SQL result")
        return rows

    assert_check("sql_product_visible", lambda: len(query(f"SELECT id, imagen FROM {table_name} WHERE id = 1",("id","imagen"))))

    def media_http(folder: str, name: str):
        with urlopen(f"{api_base.rstrip('/')}/api/media/{name}",timeout=15) as response:
            if response.status != 200 or not response.read(16):
                raise ValueError(f"image not served: {name}")
        return True
    first_image = _rows(dataset / "productos.csv")[0]["imagen"]
    assert_check("image_served_as_thumbnail",lambda: media_http("imagenes", first_image))

    if mode == "geometric":
        q = _rows(dataset / "consultas.csv")[0]["imagen"]
        assert_check("query_media_served",lambda: media_http("consultas",q))
        assert_check("ivf_similar_to",lambda: len(query(
            f"SELECT id, categoria, imagen, SIMILARITY_SCORE() AS score FROM figuras "
            f"WHERE SIMILAR_TO('{q}', k=10) USING IVF WITH METRIC=cosine",("score","imagen"))) == 10)
    else:
        table_names = {table["name"] for table in api.get("/api/tables")}
        assert_check("all_four_tables_exist",lambda: {"productos","tiendas","stock","compras"}.issubset(table_names))
        assert_check("rtree_index",lambda: any(i["name"] == "idx_tiendas_ubicacion" and i["kind"].lower()=="rtree" for t in api.get("/api/tables") if t["name"]=="tiendas" for i in t["indexes"]))
        assert_check("positive_stock_in_sql",lambda: len(query("SELECT id, tienda_id, producto_id, cantidad FROM stock WHERE cantidad > 0 LIMIT 10")) > 0)
        assert_check("co_purchase_rows_in_sql",lambda: len(query("SELECT id, usuario_id, producto_id FROM compras LIMIT 10")) > 0)
        assert_check("spatial_sql",lambda: len(query("SELECT id, nombre FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428), HAVERSINE) < 50000")) > 0)
        # This confirms the image search pipeline, not recommendation quality.
        assert_check("ivf_visual_sql",lambda: len(query(
            f"SELECT id, imagen, SIMILARITY_SCORE() AS score FROM productos "
            f"WHERE SIMILAR_TO('{first_image}', k=10) USING IVF WITH METRIC=cosine",("score","imagen"))) == 10)
    return {"mode": mode, "dataset": str(dataset), "passed": sum(int(r["passed"]) for r in checks),
            "failed": sum(int(not r["passed"]) for r in checks), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--mode",choices=("store","geometric"),required=True)
    p.add_argument("--dataset",type=Path,required=True)
    p.add_argument("--api",default="http://127.0.0.1:8000")
    p.add_argument("--output",type=Path,default=None)
    args=p.parse_args(argv)
    result=run(args.mode,args.dataset,args.api)
    payload=json.dumps(result,indent=2,ensure_ascii=False)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(payload+"\n",encoding="utf-8")
    return int(result["failed"]!=0)

if __name__ == "__main__":
    raise SystemExit(main())
