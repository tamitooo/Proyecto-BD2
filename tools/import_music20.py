"""Load licensed music segment fingerprints into the BD2 SQL engine + IVF.

The recognition endpoint uses SIMILAR_TO over audio_segmentos by default; it
never replaces the existing image or whole-audio BoAW tables/models.
"""
from __future__ import annotations

import argparse
import csv
import filecmp
import hashlib
import json
import shutil
import sys
from pathlib import Path

from tools.seed_tienda import Api, SeedError, esperar_api
from tools.build_music20 import verify


def _copy(source: Path, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if not filecmp.cmp(source, target, shallow=False):
            raise SeedError(f"refusing to overwrite different audio: {target}")
    else:
        shutil.copy2(source, target)


def seed(api: Api, dataset: Path, data_dir: Path) -> dict:
    dataset, data_dir = Path(dataset), Path(data_dir)
    counts = verify(dataset)
    esperar_api(api, 45)
    tables = {t["name"]: t for t in api.get("/api/tables")}
    wanted = {"audio_segmentos": counts["segments"], "audio_canciones": counts["tracks"]}
    fingerprint = hashlib.sha256((dataset / "catalog.csv").read_bytes() +
                                 (dataset / "audio_segmentos.csv").read_bytes()).hexdigest()
    marker = data_dir / "music20" / ".fingerprint"
    if marker.exists() and marker.read_text(encoding="ascii").strip() != fingerprint:
        raise SeedError("existing music dataset differs; use an isolated fresh BD2_DATA_DIR")
    for table, count in wanted.items():
        if table in tables and (not marker.exists() or int(tables[table]["row_count"]) != count):
            raise SeedError(f"table {table} conflicts with expected dataset; use fresh BD2_DATA_DIR")
    for row in csv.DictReader((dataset / "catalog.csv").open(encoding="utf-8", newline="")):
        _copy(dataset / "media" / row["audio"], data_dir / "media" / row["audio"])
    for file in ("catalog.csv", "audio_index.npz"):
        _copy(dataset / file, data_dir / "music20" / file)
    for table, file in (("audio_canciones", "catalog.csv"),
                        ("audio_segmentos", "audio_segmentos.csv")):
        if table not in tables:
            answer = api.post_form("/api/tables/import", {
                "name": table, "primary_key": "id", "storage_kind": "heap"},
                (file, (dataset / file).read_bytes()))
            if int(answer["imported_rows"]) != wanted[table]:
                raise SeedError(f"short import for {table}")
    indexes = [i["name"] for t in api.get("/api/tables") if t["name"] == "audio_segmentos"
               for i in t["indexes"]]
    if "idx_audio_segmentos_embedding" not in indexes:
        api.sql("CREATE INDEX idx_audio_segmentos_embedding ON audio_segmentos (embedding) USING IVF WITH METRIC=cosine")
    # Test query with a nonzero saved segment vector.
    one = next(csv.DictReader((dataset / "audio_segmentos.csv").open(encoding="utf-8",newline="")))
    sql = ("SELECT track_id, segundo, SIMILARITY_SCORE() AS score FROM audio_segmentos "
           f"WHERE SIMILAR_TO({one['embedding']}, k=3) USING IVF WITH METRIC=cosine")
    result = api.sql(sql)
    if not result["rows"] or int(result["rows"][0]["track_id"]) != int(one["track_id"]):
        raise SeedError("IVF similarity smoke test did not find expected first track")
    marker.write_text(fingerprint + "\n", encoding="ascii")
    return {**counts, "index": "idx_audio_segmentos_embedding", "query_success": True}


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dataset",type=Path,default=Path("data/music20"))
    p.add_argument("--data-dir",type=Path,required=True,help="MUST match backend BD2_DATA_DIR")
    p.add_argument("--api",default="http://127.0.0.1:8000")
    args=p.parse_args(argv)
    try:
        result=seed(Api(args.api),args.dataset,args.data_dir)
    except (ValueError,SeedError,OSError,FileNotFoundError,StopIteration) as exc:
        print(f"error: {exc}",file=sys.stderr);return 1
    print(json.dumps(result,indent=2));return 0

if __name__=="__main__":
    raise SystemExit(main())
