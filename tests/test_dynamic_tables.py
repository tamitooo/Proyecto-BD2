import json

import pytest

from backend.engine import DemoEngine, TableManagementError


def test_create_manual_heap_table_and_query_it(tmp_path):
    engine = DemoEngine(data_dir=tmp_path, seed=False)

    table = engine.create_table(
        name="productos",
        columns=[
            {"name": "id", "type": "INT"},
            {"name": "nombre", "type": "VARCHAR(64)"},
            {"name": "precio", "type": "FLOAT"},
        ],
        primary_key="id",
        storage_kind="heap",
    )

    assert table["name"] == "productos"
    assert table["storage_kind"] == "heap"
    assert table["row_count"] == 0
    assert table["source"] == "manual"
    assert table["schema"]["primary_key"] == "id"

    # Toda tabla dinámica recibe índice Hash único sobre la PK.
    assert table["indexes"] == [
        {
            "name": "idx_productos_id_hash",
            "column": "id",
            "kind": "hash",
            "unique": True,
        }
    ]

    inserted = engine.run(
        "INSERT INTO productos VALUES (1, 'Laptop', 2500.5)"
    )
    assert inserted.success is True
    assert inserted.affected_rows == 1

    selected = engine.run(
        "SELECT * FROM productos WHERE id = 1"
    )
    assert selected.success is True
    assert selected.rows == [
        {
            "id": 1,
            "nombre": "Laptop",
            "precio": 2500.5,
        }
    ]
    assert selected.execution_plan["access_path"] == "HASH_INDEX_LOOKUP"


def test_manual_table_persists_after_engine_restart(tmp_path):
    first = DemoEngine(data_dir=tmp_path, seed=False)

    first.create_table(
        name="clientes",
        columns=[
            {"name": "id", "type": "INT"},
            {"name": "nombre", "type": "VARCHAR(32)"},
        ],
        primary_key="id",
        storage_kind="heap",
    )

    assert first.run(
        "INSERT INTO clientes VALUES (10, 'Ana')"
    ).success

    second = DemoEngine(data_dir=tmp_path, seed=False)

    assert second.catalog.has_table("clientes")

    selected = second.run(
        "SELECT * FROM clientes WHERE id = 10"
    )
    assert selected.success is True
    assert selected.rows[0]["nombre"] == "Ana"


def test_create_sequential_table(tmp_path):
    engine = DemoEngine(data_dir=tmp_path, seed=False)

    table = engine.create_table(
        name="eventos",
        columns=[
            {"name": "id", "type": "INT"},
            {"name": "descripcion", "type": "VARCHAR(64)"},
        ],
        primary_key="id",
        storage_kind="sequential",
    )

    assert table["storage_kind"] == "sequential"
    assert (tmp_path / "eventos.main").exists()
    assert (tmp_path / "eventos.aux").exists()


def test_duplicate_dynamic_table_is_rejected(tmp_path):
    engine = DemoEngine(data_dir=tmp_path, seed=False)

    kwargs = {
        "name": "productos",
        "columns": [
            {"name": "id", "type": "INT"},
        ],
        "primary_key": "id",
        "storage_kind": "heap",
    }

    engine.create_table(**kwargs)

    with pytest.raises(
        TableManagementError,
        match="already exists",
    ):
        engine.create_table(**kwargs)


def test_invalid_identifier_is_rejected(tmp_path):
    engine = DemoEngine(data_dir=tmp_path, seed=False)

    with pytest.raises(
        TableManagementError,
        match="invalid table",
    ):
        engine.create_table(
            name="clientes 2026",
            columns=[
                {"name": "id", "type": "INT"},
            ],
            primary_key="id",
        )


def test_invalid_column_type_is_rejected(tmp_path):
    engine = DemoEngine(data_dir=tmp_path, seed=False)

    with pytest.raises(TableManagementError):
        engine.create_table(
            name="clientes",
            columns=[
                {"name": "id", "type": "BIGINT"},
            ],
            primary_key="id",
        )


def test_import_csv_infers_schema_and_loads_rows(tmp_path):
    engine = DemoEngine(data_dir=tmp_path, seed=False)

    content = (
        "id,nombre,edad,saldo\n"
        "1,Ana,23,1200.50\n"
        "2,Luis,31,2450.00\n"
        "3,Maria,27,850.25\n"
    ).encode("utf-8")

    result = engine.import_csv(
        name="clientes",
        filename="clientes.csv",
        content=content,
        primary_key="id",
        storage_kind="heap",
    )

    assert result["imported_rows"] == 3
    assert result["table"]["row_count"] == 3
    assert result["table"]["source"] == "csv"
    assert result["table"]["original_filename"] == "clientes.csv"

    assert result["inferred_schema"]["columnas"] == [
        ("id", "INT"),
        ("nombre", "VARCHAR(5)"),
        ("edad", "INT"),
        ("saldo", "FLOAT"),
    ]

    selected = engine.run(
        "SELECT * FROM clientes WHERE id = 2"
    )
    assert selected.success is True
    assert selected.rows == [
        {
            "id": 2,
            "nombre": "Luis",
            "edad": 31,
            "saldo": 2450.0,
        }
    ]
    assert selected.execution_plan["access_path"] == "HASH_INDEX_LOOKUP"


def test_import_csv_sequential_is_queryable(tmp_path):
    engine = DemoEngine(data_dir=tmp_path, seed=False)

    result = engine.import_csv(
        name="mediciones",
        filename="mediciones.csv",
        content=(
            "id,valor\n"
            "1,10.5\n"
            "2,11.75\n"
        ).encode("utf-8"),
        primary_key="id",
        storage_kind="sequential",
    )

    assert result["table"]["storage_kind"] == "sequential"
    assert result["imported_rows"] == 2

    selected = engine.run(
        "SELECT * FROM mediciones WHERE id = 2"
    )
    assert selected.success is True
    assert selected.rows[0]["valor"] == 11.75


def test_csv_duplicate_primary_key_rolls_back(tmp_path):
    engine = DemoEngine(data_dir=tmp_path, seed=False)

    with pytest.raises(
        TableManagementError,
        match="duplicate primary key",
    ):
        engine.import_csv(
            name="duplicados",
            filename="duplicados.csv",
            content=(
                "id,nombre\n"
                "1,Ana\n"
                "1,Luis\n"
            ).encode("utf-8"),
            primary_key="id",
        )

    assert not engine.catalog.has_table("duplicados")
    assert not (tmp_path / "duplicados.dat").exists()


def test_csv_missing_primary_key_column_is_rejected(tmp_path):
    engine = DemoEngine(data_dir=tmp_path, seed=False)

    with pytest.raises(
        TableManagementError,
        match="is not present",
    ):
        engine.import_csv(
            name="clientes",
            filename="clientes.csv",
            content=(
                "codigo,nombre\n"
                "1,Ana\n"
            ).encode("utf-8"),
            primary_key="id",
        )


def test_csv_wrong_row_width_is_rejected_without_creating_table(tmp_path):
    engine = DemoEngine(data_dir=tmp_path, seed=False)

    with pytest.raises(
        TableManagementError,
        match="expected 2",
    ):
        engine.import_csv(
            name="malformada",
            filename="malformada.csv",
            content=(
                "id,nombre\n"
                "1,Ana,Extra\n"
            ).encode("utf-8"),
            primary_key="id",
        )

    assert not engine.catalog.has_table("malformada")
    assert not (tmp_path / "malformada.dat").exists()


def test_dynamic_catalog_json_contains_created_table(tmp_path):
    engine = DemoEngine(data_dir=tmp_path, seed=False)

    engine.create_table(
        name="productos",
        columns=[
            {"name": "id", "type": "INT"},
            {"name": "nombre", "type": "VARCHAR(32)"},
        ],
        primary_key="id",
    )

    payload = json.loads(
        (tmp_path / "catalog.json").read_text(encoding="utf-8")
    )

    assert payload["version"] == 1
    assert payload["tables"][0]["name"] == "productos"
    assert payload["tables"][0]["source"] == "manual"


def test_dynamic_primary_key_is_unique_for_later_sql_inserts(tmp_path):
    engine = DemoEngine(data_dir=tmp_path, seed=False)

    engine.create_table(
        name="productos",
        columns=[
            {"name": "id", "type": "INT"},
            {"name": "nombre", "type": "VARCHAR(32)"},
        ],
        primary_key="id",
    )

    first = engine.run(
        "INSERT INTO productos VALUES (1, 'Uno')"
    )
    second = engine.run(
        "INSERT INTO productos VALUES (1, 'Duplicado')"
    )

    assert first.success is True
    assert second.success is False

    selected = engine.run("SELECT * FROM productos")
    assert len(selected.rows) == 1
    assert selected.rows[0]["nombre"] == "Uno"
