from __future__ import annotations

import math
import os
import random
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from backend.engine import DemoEngine
from indexes.bplus_tree import BPlusTree
from indexes.extendible_hash import ExtendibleHash
from indexes.rtree import RTree
from operators.external_hashing import ExternalHashing
from operators.external_sort import ExternalSort
from query.catalog import CatalogError
from spatial.geo import euclidean, haversine, point_in_polygon
from spatial.index import SpatialIndex
from storage.heap_file import HeapFile
from storage.record import Schema
from storage.sequential_file import SequentialFile, REORG_AUX_RATIO
from transactions.lock_manager import LockManager


@pytest.fixture()
def engine():
    with TemporaryDirectory() as directory:
        yield DemoEngine(directory)


def test_demo_seed_is_complete_and_clustered_physically(engine):
    counts = {t["name"]: t["row_count"] for t in engine.tables()}
    assert counts == {"departments": 2, "employees": 4, "users": 4}
    ages = [row["age"] for _, row in engine.catalog.get_table("users").storage.scan()]
    assert ages == sorted(ages) == [19, 20, 23, 25]


def test_heap_is_paged_reuses_deleted_slots_and_spans_pages(tmp_path):
    schema = Schema([("id", "INT"), ("txt", "VARCHAR(2000)")], "id")
    heap = HeapFile(str(tmp_path / "heap.dat"), schema)
    rids = [heap.insert({"id": i, "txt": str(i)}) for i in range(7)]
    assert len({rid.page for rid in rids}) > 1
    victim = rids[2]
    assert heap.delete(victim)
    replacement = heap.insert({"id": 99, "txt": "reused"})
    assert replacement == victim
    assert heap.read(replacement)["id"] == 99


def test_sequential_main_order_search_range_lazy_delete_and_reorganization(tmp_path):
    schema = Schema([("id", "INT"), ("v", "INT")], "id")
    seq = SequentialFile(str(tmp_path / "seq"), schema)
    # Construir un main estable y luego probar overflow.
    seq.replace_all([{"id": i, "v": i * 10} for i in range(1, 21)])
    for i in (27, 24, 22, 25, 23):
        seq.insert({"id": i, "v": i * 10})
    rid, row = seq.search(24)
    assert rid is not None and row["v"] == 240
    assert [r["id"] for _, r in seq.range_search(20, 25)] == [20, 22, 23, 24, 25]
    assert seq.delete(10)
    assert seq.search(10) == (None, None)
    # Forzar reorganización: 6 inserciones sobre main 20 llegan al 30%.
    before = seq.n_reorganizaciones
    seq.insert({"id": 26, "v": 260})
    assert seq.n_reorganizaciones >= before + 1
    main_ids = [r["id"] for flag, r in seq._leer_todos(seq.main_path) if flag == schema.FLAG_USED]
    assert main_ids == sorted(main_ids)
    assert os.path.getsize(seq.aux_path) == 0


def test_extendible_hash_splits_directory_and_exact_lookup():
    h = ExtendibleHash(bucket_capacity=2, hash_func=lambda x: x)
    for key in range(16):
        h.insert(key, f"rid-{key}")
    assert h.global_depth >= 3
    assert len(h.directory) == 2 ** h.global_depth
    assert all(h.search(i) == [f"rid-{i}"] for i in range(16))
    assert h.validate()


def test_extendible_hash_duplicate_and_unique_semantics():
    h = ExtendibleHash(bucket_capacity=2, unique=False, hash_func=lambda x: x)
    h.insert(7, "a"); h.insert(7, "b")
    assert h.search(7) == ["a", "b"]
    assert h.delete(7, "a")
    assert h.search(7) == ["b"]
    u = ExtendibleHash(bucket_capacity=2, unique=True, hash_func=lambda x: x)
    u.insert(7, "a")
    with pytest.raises(ValueError):
        u.insert(7, "b")


def test_bplus_tree_exact_range_delete_and_invariants():
    tree = BPlusTree(order=4)
    for key in [8, 2, 7, 3, 1, 9, 4, 6, 5, 5]:
        tree.insert(key, f"v{key}")
    assert len(tree.search(5)) == 2
    assert [k for k, _ in tree.range_search(3, 7)] == [3, 4, 5, 5, 6, 7]
    assert tree.delete(5, "v5")
    assert len(tree.search(5)) == 1
    assert tree.validate()


def test_unclustered_bplus_stores_rids_and_drives_heap_fetch(engine):
    r = engine.run("SELECT * FROM employees WHERE salary >= 3900 ORDER BY salary")
    assert r.success
    assert r.execution_plan["access_path"] == "BPLUS_UNCLUSTERED_RANGE_SCAN"
    assert [row["salary"] for row in r.rows] == [3900.0, 4800.0, 5100.0]
    reg = engine.catalog.get_index("employees", "idx_emp_salary_bplus")
    rids = reg.implementation.range_search(3900, 5100)
    assert rids and all(not isinstance(x, dict) for x in rids)


def test_clustered_bplus_is_one_per_table_and_physical(engine):
    users = engine.catalog.get_table("users")
    clustered = [i for i in users.indexes.values() if i.metadata.kind == "bplus_clustered"]
    assert len(clustered) == 1
    with pytest.raises(CatalogError, match="solo puede existir"):
        engine.catalog.create_index("users", "dept", kind="bplus_clustered", name="second_clustered")
    ages = [row["age"] for _, row in users.storage.scan()]
    assert ages == sorted(ages)


def test_dynamic_clustered_index_physically_reorders_and_dml_keeps_it(engine):
    assert engine.run("CREATE TABLE demo (id INT PRIMARY KEY, score INT, grp VARCHAR(8))").success
    for sql in [
        "INSERT INTO demo VALUES (1,30,'a')",
        "INSERT INTO demo VALUES (2,10,'b')",
        "INSERT INTO demo VALUES (3,20,'a')",
    ]:
        assert engine.run(sql).success
    assert engine.run("CREATE INDEX idx_demo_score ON demo (score) USING BPLUS_CLUSTERED").success
    physical = [row["score"] for _, row in engine.catalog.get_table("demo").storage.scan()]
    assert physical == [10, 20, 30]
    assert engine.run("INSERT INTO demo VALUES (4,15,'b')").success
    physical = [row["score"] for _, row in engine.catalog.get_table("demo").storage.scan()]
    assert physical == [10, 15, 20, 30]
    assert engine.run("UPDATE demo SET score = 5 WHERE id = 1").success
    physical = [row["score"] for _, row in engine.catalog.get_table("demo").storage.scan()]
    assert physical == [5, 10, 15, 20]
    # Hash de PK debe seguir apuntando a RIDs válidos tras cada reclustering.
    row = engine.run("SELECT * FROM demo WHERE id = 1")
    assert row.rows[0]["score"] == 5


def test_clustered_is_rejected_on_sequential_storage(engine):
    r = engine.run("CREATE INDEX bad_cluster ON employees (salary) USING BPLUS_CLUSTERED")
    assert not r.success
    assert "requiere Heap File" in (r.error or "")


def test_external_sort_creates_runs_and_kway_merge():
    sorter = ExternalSort(memory_rows=7, fan_in=3)
    rows = [{"x": x} for x in reversed(range(75))]
    out = sorter.sort(rows, key=lambda r: r["x"])
    assert [r["x"] for r in out] == list(range(75))
    assert sorter.last_stats.initial_runs > 1
    assert sorter.last_stats.merge_passes >= 1
    out_desc = sorter.sort(rows, key=lambda r: r["x"], descending=True)
    assert [r["x"] for r in out_desc] == list(reversed(range(75)))


def test_external_hash_group_by_and_hash_join_with_partitioning():
    h = ExternalHashing(memory_rows=5, partitions=4)
    rows = [{"g": i % 3, "v": i} for i in range(40)]
    grouped = sorted(h.group_by(rows, key="g", aggregates={"n": "count", "s": ("sum", "v")}), key=lambda r:r["g"])
    assert sum(r["n"] for r in grouped) == 40
    assert h.last_stats.partitions_created == 4
    left = [{"id": 1, "k": "x"}, {"id": 2, "k": "y"}]
    right = [{"k": "x", "value": 9}, {"k": "z", "value": 3}]
    joined = h.hash_join(left, right, left_key="k", right_key="k", join_type="inner")
    assert len(joined) == 1 and joined[0]["value"] == 9


def test_sql_crud_where_group_order_join_and_plan(engine):
    assert engine.run("INSERT INTO users VALUES (9,'Nuevo',30,'CS')").success
    r = engine.run("SELECT * FROM users WHERE age BETWEEN 20 AND 30 ORDER BY age DESC")
    assert r.success and [x["age"] for x in r.rows] == sorted([x["age"] for x in r.rows], reverse=True)
    g = engine.run("SELECT dept, COUNT(*) AS n FROM users GROUP BY dept ORDER BY dept")
    assert g.success and sum(x["n"] for x in g.rows) == 5
    j = engine.run("SELECT users.name, employees.salary FROM users JOIN employees ON users.dept = employees.dept")
    assert j.success and len(j.rows) > 0
    u = engine.run("UPDATE users SET age = 31 WHERE id = 9")
    assert u.success and u.affected_rows == 1
    d = engine.run("DELETE FROM users WHERE id = 9")
    assert d.success and d.affected_rows == 1
    assert engine.run("SELECT * FROM users WHERE id = 9").rows == []


def test_create_drop_index_changes_plan(engine):
    assert engine.run("CREATE TABLE q (id INT PRIMARY KEY, v INT)").success
    for i in range(10): assert engine.run(f"INSERT INTO q VALUES ({i},{i%4})").success
    before = engine.run("SELECT * FROM q WHERE v >= 2")
    assert before.execution_plan["access_path"] == "HEAP_SCAN"
    assert engine.run("CREATE INDEX idx_q_v ON q (v) USING BPLUS_UNCLUSTERED").success
    after = engine.run("SELECT * FROM q WHERE v >= 2")
    assert after.execution_plan["access_path"] == "BPLUS_UNCLUSTERED_RANGE_SCAN"
    assert engine.run("DROP INDEX idx_q_v ON q").success
    again = engine.run("SELECT * FROM q WHERE v >= 2")
    assert again.execution_plan["access_path"] == "HEAP_SCAN"


def test_transaction_commit_and_rollback(engine):
    baseline = engine.run("SELECT * FROM departments ORDER BY id").rows
    assert engine.run("BEGIN TRANSACTION").success
    assert engine.run("INSERT INTO departments VALUES (9,'Temporal','Cusco')").success
    assert engine.run("ROLLBACK").success
    assert engine.run("SELECT * FROM departments ORDER BY id").rows == baseline
    assert engine.run("BEGIN TRANSACTION").success
    assert engine.run("INSERT INTO departments VALUES (9,'Persistente','Cusco')").success
    assert engine.run("COMMIT").success
    assert len(engine.run("SELECT * FROM departments WHERE id = 9").rows) == 1


def _spatial_setup(engine):
    assert engine.run("CREATE TABLE tiendas (id INT PRIMARY KEY, nombre VARCHAR(30), lat FLOAT, lon FLOAT)").success
    points = [
        (1,"A",-12.0464,-77.0428),
        (2,"B",-12.0500,-77.0400),
        (3,"C",-12.1000,-77.1000),
        (4,"D",-12.0400,-77.0500),
        (5,"E",-12.0600,-77.0200),
    ]
    for row in points:
        assert engine.run(f"INSERT INTO tiendas VALUES ({row[0]},'{row[1]}',{row[2]},{row[3]})").success
    assert engine.run("CREATE INDEX idx_tiendas_geo ON tiendas (lat, lon) USING RTREE").success
    return points


def test_rtree_core_random_range_and_knn_against_bruteforce():
    rng = random.Random(7)
    points = [(rng.random()*100, rng.random()*100) for _ in range(300)]
    tree = RTree(max_entries=8)
    tree.bulk_load([(p, i) for i,p in enumerate(points)])
    assert tree.validate()
    q = (41.5, 62.3)
    box = ((20.0,30.0),(70.0,80.0))
    got = {rid for rid,_ in tree.range_search(box)}
    expected = {i for i,(x,y) in enumerate(points) if 20 <= x <= 70 and 30 <= y <= 80}
    assert got == expected
    got_knn = [rid for rid,_ in tree.knn(q, 17, distance=lambda rid: euclidean(q, points[rid]))]
    expected_knn = [i for i,_ in sorted(enumerate(points), key=lambda x: euclidean(q,x[1]))[:17]]
    assert got_knn == expected_knn

@pytest.mark.parametrize("metric,radius", [("haversine", 5000.0), ("euclidean", 0.05)])
def test_spatial_range_matches_bruteforce(engine, metric, radius):
    points = _spatial_setup(engine)
    origin=(-12.0464,-77.0428)
    r=engine.run(f"SELECT * FROM tiendas WHERE distancia(lat, POINT({origin[0]},{origin[1]}), {metric.upper()}) < {radius}")
    assert r.success and r.execution_plan["access_path"] == "RTREE_RANGE_SCAN"
    distance = haversine if metric == "haversine" else euclidean
    expected={p[0] for p in points if distance(origin,(p[2],p[3])) < radius}
    assert {x["id"] for x in r.rows} == expected

@pytest.mark.parametrize("metric", ["haversine", "euclidean"])
def test_spatial_knn_matches_bruteforce(engine, metric):
    points=_spatial_setup(engine); origin=(-12.0464,-77.0428); distance=haversine if metric=="haversine" else euclidean
    r=engine.run(f"SELECT * FROM tiendas ORDER BY distancia(lat, POINT({origin[0]},{origin[1]}), {metric.upper()}) LIMIT 3")
    assert r.success and r.execution_plan["access_path"] == "RTREE_KNN"
    expected=[p[0] for p in sorted(points,key=lambda p:distance(origin,(p[2],p[3])))[:3]]
    assert [x["id"] for x in r.rows] == expected


def test_spatial_polygon_matches_bruteforce(engine):
    points=_spatial_setup(engine)
    ring=[(-12.065,-77.065),(-12.065,-77.015),(-12.035,-77.015),(-12.035,-77.065)]
    sql="SELECT * FROM tiendas WHERE dentro_de(lat, POLYGON((" + ", ".join(f"{a} {b}" for a,b in ring) + ")) )"
    r=engine.run(sql)
    assert r.success and r.execution_plan["access_path"] == "RTREE_POLYGON"
    expected={p[0] for p in points if point_in_polygon((p[2],p[3]),ring)}
    assert {x["id"] for x in r.rows} == expected


def test_rtree_is_persisted_and_restored_after_restart(tmp_path):
    first=DemoEngine(tmp_path)
    _spatial_setup(first)
    first=None
    second=DemoEngine(tmp_path,seed=False)
    info=second.table_info("tiendas")
    assert any(i["kind"]=="rtree" and i.get("lon_column")=="lon" for i in info["indexes"])
    r=second.run("SELECT * FROM tiendas WHERE distancia(lat, POINT(-12.0464,-77.0428), HAVERSINE) < 5000")
    assert r.success and r.execution_plan["access_path"]=="RTREE_RANGE_SCAN"
    assert {x["id"] for x in r.rows} >= {1,2,4}


def test_spatial_index_survives_insert_delete_update(engine):
    _spatial_setup(engine)
    assert engine.run("INSERT INTO tiendas VALUES (8,'H',-12.045,-77.043)").success
    assert 8 in {x["id"] for x in engine.run("SELECT * FROM tiendas WHERE distancia(lat, POINT(-12.0464,-77.0428), HAVERSINE) < 1000").rows}
    assert engine.run("UPDATE tiendas SET lat=-12.2 WHERE id=8").success
    assert 8 not in {x["id"] for x in engine.run("SELECT * FROM tiendas WHERE distancia(lat, POINT(-12.0464,-77.0428), HAVERSINE) < 1000").rows}
    assert engine.run("DELETE FROM tiendas WHERE id=8").success
    assert engine.run("SELECT * FROM tiendas WHERE id=8").rows == []


def test_explain_and_explain_analyze(engine):
    e=engine.run("EXPLAIN SELECT * FROM users WHERE id = 2")
    assert e.success and e.execution_plan["access_path"]=="HASH_INDEX_LOOKUP"
    a=engine.run("EXPLAIN ANALYZE SELECT * FROM users WHERE age >= 20")
    assert a.success and "analyze" in a.execution_plan

def test_concurrency_demo_reproduces_lost_update_and_locks_fix_it():
    from transactions.demo_concurrencia import correr_demo
    broken, expected, _ = correr_demo(False)
    correct, expected2, _ = correr_demo(True)
    assert broken != expected
    assert correct == expected2 == 190


def test_spatial_sql_accepts_ubicacion_alias(engine):
    _spatial_setup(engine)
    r = engine.run(
        "SELECT * FROM tiendas WHERE "
        "distancia(ubicacion, POINT(-12.0464,-77.0428), HAVERSINE) < 5000"
    )
    assert r.success, r.error
    assert r.execution_plan["access_path"] == "RTREE_RANGE_SCAN"
    assert {x["id"] for x in r.rows} >= {1, 2, 4}


def test_spatial_sql_accepts_named_query_point(engine):
    _spatial_setup(engine)
    set_result = engine.run("SET mi_ubicacion = POINT(-12.0464,-77.0428)")
    assert set_result.success, set_result.error
    r = engine.run(
        "SELECT * FROM tiendas "
        "ORDER BY distancia(ubicacion, mi_ubicacion, HAVERSINE) LIMIT 3"
    )
    assert r.success, r.error
    assert r.execution_plan["access_path"] == "RTREE_KNN"
    assert r.rows[0]["id"] == 1
