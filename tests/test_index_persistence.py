"""Pruebas específicas del feedback de la rúbrica.

Demuestran que B+, Hash y R-Tree tienen archivo propio y se restauran desde
ese archivo, sin reconstruirse mediante un scan de la tabla base.
"""
from pathlib import Path
from unittest.mock import patch

from query.catalog import Catalog
from storage.heap_file import HeapFile
from storage.record import Schema

SCHEMA = Schema([
    ("id", "INT"), ("name", "VARCHAR(20)"), ("score", "FLOAT"),
    ("lat", "FLOAT"), ("lon", "FLOAT"),
], primary_key="id")


def _build(tmp_path):
    catalog = Catalog(data_dir=tmp_path)
    table = catalog.create_table(
        "items",
        [("id","INT"),("name","VARCHAR(20)"),("score","FLOAT"),("lat","FLOAT"),("lon","FLOAT")],
        primary_key="id",
        primary_key_index=False,
    )
    for i in range(1, 31):
        table.storage.insert({
            "id": i, "name": f"n{i}", "score": float(i % 7),
            "lat": -12.0 - i / 10000, "lon": -77.0 - i / 10000,
        })
    catalog.create_index("items", "id", kind="hash", unique=True, name="idx_id_hash")
    catalog.create_index("items", "score", kind="bplus_unclustered", name="idx_score_bpu")
    catalog.create_index("items", "name", kind="bplus_clustered", name="idx_name_bpc")
    catalog.create_index("items", "lat", lon_column="lon", kind="rtree", name="idx_geo")
    return catalog


def test_each_index_has_real_file(tmp_path):
    catalog = _build(tmp_path)
    table = catalog.get_table("items")
    assert len(table.indexes) == 4
    for reg in table.indexes.values():
        path = Path(reg.implementation.file_path)
        assert path.exists(), (reg.metadata.name, path)
        assert path.stat().st_size > 0
        assert path.parent.name == "indexes"


def test_restart_loads_indexes_without_scanning_base_table(tmp_path):
    first = _build(tmp_path)
    definition = first.describe_tables()[0]

    # La prueba clave: si restore intentara rebuild_index(), fallaría porque
    # HeapFile.scan está prohibido durante la reapertura.
    second = Catalog(data_dir=tmp_path)
    with patch.object(HeapFile, "scan", side_effect=AssertionError("NO SCAN DURING INDEX RESTORE")):
        second.restore_table(definition, data_dir=tmp_path)

    t = second.get_table("items")
    assert t.indexes["idx_id_hash"].implementation.search(10)
    assert t.indexes["idx_score_bpu"].implementation.search(3.0)
    assert t.indexes["idx_name_bpc"].implementation.search("n10")
    spatial = t.indexes["idx_geo"].implementation
    assert len(spatial) == 30
    spatial.validate()


def test_mutation_is_durable_without_rebuild(tmp_path):
    first = _build(tmp_path)
    t = first.get_table("items")
    h = t.indexes["idx_id_hash"].implementation
    before = Path(h.file_path).stat().st_mtime_ns
    h.insert(999, (99, 99))
    assert Path(h.file_path).stat().st_mtime_ns >= before

    # Un objeto nuevo sobre el mismo archivo ve la mutación.
    from indexes.extendible_hash import ExtendibleHash
    reloaded = ExtendibleHash(bucket_capacity=4, unique=True, file_path=h.file_path)
    assert reloaded.search(999) == [(99, 99)]


def test_drop_index_removes_its_file(tmp_path):
    catalog = _build(tmp_path)
    impl = catalog.get_index("items", "idx_score_bpu").implementation
    path = Path(impl.file_path)
    assert path.exists()
    catalog.drop_index("idx_score_bpu", table="items")
    assert not path.exists()
