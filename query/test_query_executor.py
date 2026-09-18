import pytest

from indexes.extendible_hash import ExtendibleHash
from indexes.unclustered_bplus import UnclusteredBPlusIndex
from query.catalog import Catalog
from query.query_executor import QueryExecutor
from storage.heap_file import HeapFile
from storage.record import Schema
from storage.sequential_file import SequentialFile


@pytest.fixture
def schema():
    return Schema(
        [
            ("id", "INT"),
            ("name", "VARCHAR(32)"),
            ("age", "INT"),
            ("dept", "VARCHAR(16)"),
            ("salary", "FLOAT"),
        ],
        primary_key="id",
    )


@pytest.fixture
def heap_db(tmp_path, schema):
    storage = HeapFile(str(tmp_path / "users.dat"), schema)
    catalog = Catalog()
    catalog.register_table("users", storage)
    executor = QueryExecutor(catalog)
    return catalog, executor, storage


def _seed(executor):
    rows = [
        (1, "Ana", 19, "CS", 3000.0),
        (2, "Badi", 21, "CS", 4500.0),
        (3, "Carla", 17, "EE", 2500.0),
        (4, "Daniel", 21, "EE", 5000.0),
        (5, "Elena", 30, "CS", 6000.0),
    ]
    for row in rows:
        result = executor.execute(
            "INSERT INTO users VALUES " + repr(row).replace("'", "'")
        )
        assert result.success, result.error


def test_insert_select_and_frontend_result_contract(heap_db):
    _, executor, _ = heap_db

    inserted = executor.execute(
        "INSERT INTO users VALUES (1, 'Ana', 19, 'CS', 3000.0)"
    )
    assert inserted.success
    assert inserted.statement == "INSERT"
    assert inserted.affected_rows == 1

    selected = executor.execute("SELECT id, name FROM users")
    assert selected.success
    assert selected.columns == ["id", "name"]
    assert selected.rows == [{"id": 1, "name": "Ana"}]
    assert selected.to_dict()["execution_plan"]["runtime_steps"]


def test_where_supports_all_required_comparison_operators(heap_db):
    _, executor, _ = heap_db
    _seed(executor)

    cases = [
        ("age = 21", {2, 4}),
        ("age != 21", {1, 3, 5}),
        ("age <> 21", {1, 3, 5}),
        ("age < 21", {1, 3}),
        ("age <= 21", {1, 2, 3, 4}),
        ("age > 21", {5}),
        ("age >= 21", {2, 4, 5}),
        ("age BETWEEN 18 AND 25", {1, 2, 4}),
    ]

    for where, expected in cases:
        result = executor.execute(f"SELECT id FROM users WHERE {where}")
        assert result.success, result.error
        assert {row["id"] for row in result.rows} == expected


def test_where_multiple_and_predicates(heap_db):
    _, executor, _ = heap_db
    _seed(executor)

    result = executor.execute(
        "SELECT id, name FROM users WHERE age >= 21 AND dept = 'CS'"
    )
    assert result.success, result.error
    assert result.rows == [
        {"id": 2, "name": "Badi"},
        {"id": 5, "name": "Elena"},
    ]


def test_order_by_uses_external_sort_and_supports_desc(heap_db):
    _, executor, _ = heap_db
    _seed(executor)

    result = executor.execute(
        "SELECT id, age FROM users ORDER BY age DESC, id ASC"
    )
    assert result.success, result.error
    assert [row["id"] for row in result.rows] == [5, 2, 4, 1, 3]

    runtime_ops = [
        step["operator"]
        for step in result.execution_plan["runtime_steps"]
    ]
    assert "EXTERNAL_SORT" in runtime_ops


def test_group_by_without_aggregate_returns_distinct_groups(heap_db):
    _, executor, _ = heap_db
    _seed(executor)

    result = executor.execute("SELECT dept FROM users GROUP BY dept")
    assert result.success, result.error
    assert {row["dept"] for row in result.rows} == {"CS", "EE"}


def test_group_by_with_common_aggregates(heap_db):
    _, executor, _ = heap_db
    _seed(executor)

    result = executor.execute(
        "SELECT dept, COUNT(*) AS total, AVG(salary) AS avg_salary "
        "FROM users GROUP BY dept ORDER BY dept"
    )
    assert result.success, result.error

    by_dept = {row["dept"]: row for row in result.rows}
    assert by_dept["CS"]["total"] == 3
    assert by_dept["CS"]["avg_salary"] == pytest.approx(4500.0)
    assert by_dept["EE"]["total"] == 2
    assert by_dept["EE"]["avg_salary"] == pytest.approx(3750.0)


def test_delete_with_where_and_delete_all(heap_db):
    _, executor, _ = heap_db
    _seed(executor)

    deleted = executor.execute("DELETE FROM users WHERE age < 18")
    assert deleted.success
    assert deleted.affected_rows == 1

    remaining = executor.execute("SELECT id FROM users ORDER BY id")
    assert [row["id"] for row in remaining.rows] == [1, 2, 4, 5]

    delete_all = executor.execute("DELETE FROM users")
    assert delete_all.success
    assert delete_all.affected_rows == 4
    assert executor.execute("SELECT * FROM users").rows == []


def test_hash_index_is_planned_used_and_maintained(heap_db):
    catalog, executor, _ = heap_db
    _seed(executor)

    index = ExtendibleHash(bucket_capacity=2, unique=True, hash_func=int)
    catalog.register_index(
        name="idx_users_id_hash",
        table="users",
        column="id",
        kind="hash",
        implementation=index,
        rebuild=True,
    )

    result = executor.execute("SELECT name FROM users WHERE id = 4")
    assert result.success, result.error
    assert result.rows == [{"name": "Daniel"}]
    assert result.execution_plan["access_path"] == "HASH_INDEX_LOOKUP"
    assert result.execution_plan["used_indexes"] == ["idx_users_id_hash"]

    inserted = executor.execute(
        "INSERT INTO users VALUES (6, 'Fabio', 25, 'CS', 4100.0)"
    )
    assert inserted.success, inserted.error
    live_index = catalog.get_index("users", "idx_users_id_hash").implementation
    assert live_index.search(6)

    deleted = executor.execute("DELETE FROM users WHERE id = 6")
    assert deleted.success
    assert live_index.search(6) == []


def test_unique_index_failure_rolls_back_heap_insert(heap_db):
    catalog, executor, storage = heap_db
    executor.execute("INSERT INTO users VALUES (1, 'Ana', 19, 'CS', 3000.0)")

    index = ExtendibleHash(bucket_capacity=2, unique=True, hash_func=int)
    catalog.register_index(
        name="idx_users_id_hash",
        table="users",
        column="id",
        kind="hash",
        implementation=index,
        rebuild=True,
    )

    duplicate = executor.execute(
        "INSERT INTO users VALUES (1, 'Other', 22, 'EE', 1000.0)"
    )
    assert not duplicate.success
    assert len(list(storage.scan())) == 1


def test_unclustered_bplus_range_scan_materializes_heap_rows(heap_db):
    catalog, executor, _ = heap_db
    _seed(executor)

    index = UnclusteredBPlusIndex("age", unique=False)
    catalog.register_index(
        name="idx_users_age",
        table="users",
        column="age",
        kind="bplus_unclustered",
        implementation=index,
        rebuild=True,
    )

    result = executor.execute(
        "SELECT id, age FROM users WHERE age BETWEEN 19 AND 21 ORDER BY age"
    )
    assert result.success, result.error
    assert [row["id"] for row in result.rows] == [1, 2, 4]
    assert result.execution_plan["access_path"] == "BPLUS_UNCLUSTERED_RANGE_SCAN"


def test_invalid_table_column_and_insert_arity_return_clean_errors(heap_db):
    _, executor, _ = heap_db

    unknown_table = executor.execute("SELECT * FROM missing")
    assert not unknown_table.success
    assert "unknown table" in unknown_table.error.lower()

    unknown_column = executor.execute("SELECT nope FROM users")
    assert not unknown_column.success
    assert "unknown selected column" in unknown_column.error.lower()

    bad_insert = executor.execute("INSERT INTO users VALUES (1, 'Ana')")
    assert not bad_insert.success
    assert "expected 5 values" in bad_insert.error


def test_sequential_storage_rebuilds_rid_indexes_after_reorganization(tmp_path, schema):
    storage = SequentialFile(str(tmp_path / "events"), schema)
    catalog = Catalog()
    catalog.register_table("users", storage)

    hash_index = ExtendibleHash(bucket_capacity=2, unique=True, hash_func=int)
    catalog.register_index(
        name="idx_users_id_hash",
        table="users",
        column="id",
        kind="hash",
        implementation=hash_index,
    )

    executor = QueryExecutor(catalog)
    for i in range(1, 14):
        result = executor.execute(
            f"INSERT INTO users VALUES ({i}, 'U{i}', {18+i}, 'CS', {1000.0+i})"
        )
        assert result.success, result.error

    result = executor.execute("SELECT name FROM users WHERE id = 12")
    assert result.success, result.error
    assert result.rows == [{"name": "U12"}]
    assert result.execution_plan["access_path"] == "HASH_INDEX_LOOKUP"
