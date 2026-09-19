"""Catálogo de demostración y ejecutor SQL.

Además de las tablas de demostración, este módulo administra tablas dinámicas
creadas desde el frontend o importadas desde CSV.

Las tablas dinámicas se registran en query.catalog.Catalog y su metadata se
persiste en backend/data/catalog.json, por lo que vuelven a estar disponibles
después de reiniciar FastAPI.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from indexes.clustered_bplus import ClusteredBPlusIndex
from indexes.extendible_hash import ExtendibleHash
from indexes.unclustered_bplus import UnclusteredBPlusIndex
from query.catalog import Catalog, CatalogError, TableMetadata
from query.query_executor import QueryExecutor
from query.query_result import QueryResult
from storage.heap_file import HeapFile
from storage.record import Schema
from storage.sequential_file import SequentialFile


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
INT_RE = re.compile(r"^[+-]?\d+$")
FLOAT_RE = re.compile(
    r"^[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?$"
)

DEMO_TABLES = {"users", "employees", "departments"}

USERS_SCHEMA = Schema(
    [
        ("id", "INT"),
        ("name", "VARCHAR(32)"),
        ("age", "INT"),
        ("dept", "VARCHAR(16)"),
    ],
    primary_key="id",
)
EMPLOYEES_SCHEMA = Schema(
    [
        ("id", "INT"),
        ("name", "VARCHAR(32)"),
        ("dept", "VARCHAR(16)"),
        ("salary", "FLOAT"),
    ],
    primary_key="id",
)
DEPARTMENTS_SCHEMA = Schema(
    [
        ("id", "INT"),
        ("name", "VARCHAR(32)"),
        ("city", "VARCHAR(24)"),
    ],
    primary_key="id",
)

SEED_SQL = [
    "INSERT INTO users VALUES (1, 'Ana Torres', 20, 'CS')",
    "INSERT INTO users VALUES (2, 'Luis Paredes', 23, 'EE')",
    "INSERT INTO users VALUES (3, 'Mia Rojas', 19, 'CS')",
    "INSERT INTO users VALUES (4, 'Karla Ruiz', 25, 'EE')",
    "INSERT INTO employees VALUES (10, 'Ana Torres', 'CS', 3200.0)",
    "INSERT INTO employees VALUES (11, 'Luis Paredes', 'EE', 4800.0)",
    "INSERT INTO employees VALUES (12, 'Mia Rojas', 'CS', 5100.0)",
    "INSERT INTO employees VALUES (13, 'Karla Ruiz', 'EE', 3900.0)",
    "INSERT INTO departments VALUES (1, 'Ciencias de la Computacion', 'Lima')",
    "INSERT INTO departments VALUES (2, 'Ingenieria Electronica', 'Arequipa')",
]


class TableManagementError(ValueError):
    """Error legible para creación/importación de tablas."""


class DemoEngine:
    """Une el motor real del proyecto con el API y administra tablas dinámicas."""

    CATALOG_FILENAME = "catalog.json"

    def __init__(self, data_dir: str | Path | None = None, seed: bool = True) -> None:
        base = data_dir or os.environ.get("BD2_DATA_DIR") or (
            Path(__file__).resolve().parent / "data"
        )
        self.data_dir = Path(base)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # RLock permite que import_csv() reutilice helpers que también asumen
        # exclusión mutua sin producir deadlocks.
        self._lock = threading.RLock()
        self._catalog_path = self.data_dir / self.CATALOG_FILENAME
        self._dynamic_tables: Dict[str, Dict[str, Any]] = {}

        self.users = HeapFile(str(self.data_dir / "users.dat"), USERS_SCHEMA)
        self.departments = HeapFile(
            str(self.data_dir / "departments.dat"),
            DEPARTMENTS_SCHEMA,
        )
        self.employees = SequentialFile(
            str(self.data_dir / "employees"),
            EMPLOYEES_SCHEMA,
        )

        self.catalog = Catalog()
        self.catalog.register_table("users", self.users)
        self.catalog.register_table("employees", self.employees)
        self.catalog.register_table("departments", self.departments)

        self.catalog.register_index(
            name="idx_users_id_hash",
            table="users",
            column="id",
            kind="hash",
            implementation=ExtendibleHash(bucket_capacity=4, unique=True),
            rebuild=True,
        )
        self.catalog.register_index(
            name="idx_emp_salary_bplus",
            table="employees",
            column="salary",
            kind="bplus_clustered",
            implementation=ClusteredBPlusIndex("salary", order=4),
            rebuild=True,
        )
        self.catalog.register_index(
            name="idx_emp_dept_bplus",
            table="employees",
            column="dept",
            kind="bplus_unclustered",
            implementation=UnclusteredBPlusIndex("dept", order=4),
            rebuild=True,
        )

        self._load_dynamic_tables()

        self.executor = QueryExecutor(self.catalog)
        if seed and self._count(self.users) == 0:
            self._seed()

    # ------------------------------------------------------------------ API

    def run(self, sql: str) -> QueryResult:
        with self._lock:
            return self.executor.execute(sql)

    def tables(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                self._table_info(self.catalog.get_table(name))
                for name in self.catalog.table_names()
            ]

    def table_info(self, name: str) -> Dict[str, Any]:
        with self._lock:
            return self._table_info(self.catalog.get_table(name))

    def create_table(
        self,
        *,
        name: str,
        columns: Sequence[Mapping[str, str] | Sequence[str]],
        primary_key: str,
        storage_kind: str = "heap",
    ) -> Dict[str, Any]:
        """Create and persist an empty dynamic table."""
        with self._lock:
            normalized_name = self._normalize_identifier(name, "table")
            normalized_columns = self._normalize_columns(columns)
            normalized_pk = self._normalize_identifier(primary_key, "primary key")
            normalized_storage = self._normalize_storage_kind(storage_kind)

            schema = self._build_schema(normalized_columns, normalized_pk)

            table = self._create_dynamic_table_unlocked(
                name=normalized_name,
                schema=schema,
                storage_kind=normalized_storage,
                register_primary_key_index=True,
            )

            metadata = self._metadata_for_table(
                table,
                source="manual",
            )

            try:
                self._dynamic_tables[normalized_name] = metadata
                self._persist_dynamic_catalog()
            except Exception:
                self._dynamic_tables.pop(normalized_name, None)
                self._rollback_table(table)
                raise

            return self._table_info(table)

    def import_csv(
        self,
        *,
        name: str,
        filename: str,
        content: bytes,
        primary_key: str,
        storage_kind: str = "heap",
    ) -> Dict[str, Any]:
        """Infer a schema, create a physical table and load a CSV atomically."""
        with self._lock:
            normalized_name = self._normalize_identifier(name, "table")
            normalized_pk = self._normalize_identifier(primary_key, "primary key")
            normalized_storage = self._normalize_storage_kind(storage_kind)

            headers, raw_rows = self._parse_csv(content)
            normalized_headers = [
                self._normalize_identifier(header, "CSV column")
                for header in headers
            ]

            if len(set(normalized_headers)) != len(normalized_headers):
                raise TableManagementError(
                    "CSV contains duplicate column names after normalization"
                )

            if normalized_pk not in normalized_headers:
                raise TableManagementError(
                    f"primary key '{normalized_pk}' is not present in the CSV header"
                )

            column_values = {
                column: [
                    row[index]
                    for row in raw_rows
                ]
                for index, column in enumerate(normalized_headers)
            }

            inferred_columns = [
                {
                    "name": column,
                    "type": self._infer_csv_type(column_values[column]),
                }
                for column in normalized_headers
            ]
            schema = self._build_schema(inferred_columns, normalized_pk)

            typed_rows = [
                self._coerce_csv_row(
                    normalized_headers,
                    raw_row,
                    inferred_columns,
                )
                for raw_row in raw_rows
            ]
            self._validate_primary_key_values(
                typed_rows,
                normalized_pk,
            )

            table = self._create_dynamic_table_unlocked(
                name=normalized_name,
                schema=schema,
                storage_kind=normalized_storage,
                register_primary_key_index=False,
            )

            try:
                for row in typed_rows:
                    table.storage.insert(row)

                self._register_primary_key_index(
                    table.name,
                    table.schema.primary_key,
                    rebuild=True,
                )

                metadata = self._metadata_for_table(
                    table,
                    source="csv",
                    original_filename=filename,
                )
                self._dynamic_tables[normalized_name] = metadata
                self._persist_dynamic_catalog()

            except Exception:
                self._dynamic_tables.pop(normalized_name, None)
                self._rollback_table(table)
                raise

            return {
                "table": self._table_info(table),
                "imported_rows": len(typed_rows),
                "inferred_schema": table.schema.to_dict(),
                "filename": filename,
            }

    # ------------------------------------------------------ dynamic tables

    def _create_dynamic_table_unlocked(
        self,
        *,
        name: str,
        schema: Schema,
        storage_kind: str,
        register_primary_key_index: bool,
    ) -> TableMetadata:
        if self.catalog.has_table(name):
            raise TableManagementError(f"table already exists: {name}")

        storage_paths = self._expected_storage_paths(name, storage_kind)
        existing = [path for path in storage_paths if path.exists()]
        if existing:
            rendered = ", ".join(str(path) for path in existing)
            raise TableManagementError(
                f"physical storage already exists for table '{name}': {rendered}"
            )

        storage = self._create_storage(name, storage_kind, schema)

        try:
            table = self.catalog.register_table(
                name,
                storage,
                schema=schema,
                storage_kind=storage_kind,
            )

            if register_primary_key_index:
                self._register_primary_key_index(
                    table.name,
                    schema.primary_key,
                    rebuild=True,
                )

            return table

        except Exception:
            if self.catalog.has_table(name):
                self.catalog.unregister_table(name)
            self._delete_storage_files(storage)
            raise

    def _register_primary_key_index(
        self,
        table_name: str,
        primary_key: str,
        *,
        rebuild: bool,
    ) -> None:
        index_name = f"idx_{table_name}_{primary_key}_hash"

        self.catalog.register_index(
            name=index_name,
            table=table_name,
            column=primary_key,
            kind="hash",
            implementation=ExtendibleHash(
                bucket_capacity=32,
                unique=True,
            ),
            unique=True,
            rebuild=rebuild,
        )

    def _load_dynamic_tables(self) -> None:
        if not self._catalog_path.exists():
            return

        try:
            payload = json.loads(
                self._catalog_path.read_text(encoding="utf-8")
            )
        except Exception as exc:
            raise RuntimeError(
                f"could not read dynamic catalog: {self._catalog_path}"
            ) from exc

        tables = payload.get("tables", [])
        if not isinstance(tables, list):
            raise RuntimeError("dynamic catalog has invalid 'tables' value")

        for metadata in tables:
            name = self._normalize_identifier(
                metadata.get("name", ""),
                "table",
            )
            storage_kind = self._normalize_storage_kind(
                metadata.get("storage_kind", "")
            )

            if name in DEMO_TABLES:
                raise RuntimeError(
                    f"dynamic catalog cannot redefine demo table: {name}"
                )

            schema_payload = metadata.get("schema")
            if not isinstance(schema_payload, dict):
                raise RuntimeError(
                    f"missing schema for dynamic table: {name}"
                )

            schema = Schema.from_dict(schema_payload)

            expected_paths = self._expected_storage_paths(
                name,
                storage_kind,
            )
            missing = [
                str(path)
                for path in expected_paths
                if not path.exists()
            ]
            if missing:
                raise RuntimeError(
                    f"missing physical files for dynamic table '{name}': "
                    + ", ".join(missing)
                )

            storage = self._create_storage(
                name,
                storage_kind,
                schema,
            )
            table = self.catalog.register_table(
                name,
                storage,
                schema=schema,
                storage_kind=storage_kind,
            )
            self._register_primary_key_index(
                table.name,
                schema.primary_key,
                rebuild=True,
            )
            self._dynamic_tables[name] = dict(metadata)

    def _persist_dynamic_catalog(self) -> None:
        payload = {
            "version": 1,
            "tables": [
                self._dynamic_tables[name]
                for name in sorted(self._dynamic_tables)
            ],
        }

        tmp_path = self._catalog_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(
                payload,
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(tmp_path, self._catalog_path)

    def _metadata_for_table(
        self,
        table: TableMetadata,
        *,
        source: str,
        original_filename: str | None = None,
    ) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {
            "name": table.name,
            "storage_kind": table.storage_kind,
            "schema": table.schema.to_dict(),
            "source": source,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if original_filename:
            metadata["original_filename"] = original_filename
        return metadata

    def _rollback_table(self, table: TableMetadata) -> None:
        if self.catalog.has_table(table.name):
            self.catalog.unregister_table(table.name)
        self._delete_storage_files(table.storage)

    # -------------------------------------------------------------- CSV

    @staticmethod
    def _parse_csv(content: bytes) -> Tuple[List[str], List[List[str]]]:
        if not content:
            raise TableManagementError("CSV file is empty")

        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise TableManagementError(
                "CSV must be encoded as UTF-8"
            ) from exc

        reader = csv.reader(io.StringIO(text))

        try:
            raw_headers = next(reader)
        except StopIteration as exc:
            raise TableManagementError("CSV file is empty") from exc

        headers = [header.strip() for header in raw_headers]
        if not headers or any(not header for header in headers):
            raise TableManagementError(
                "CSV header contains an empty column name"
            )

        rows: List[List[str]] = []

        for line_number, raw_row in enumerate(reader, start=2):
            if not raw_row or all(not value.strip() for value in raw_row):
                continue

            if len(raw_row) != len(headers):
                raise TableManagementError(
                    f"CSV row {line_number} has {len(raw_row)} values; "
                    f"expected {len(headers)}"
                )

            rows.append([value.strip() for value in raw_row])

        return headers, rows

    @staticmethod
    def _infer_csv_type(values: Sequence[str]) -> str:
        # Empty values are kept as VARCHAR because the physical Schema has no
        # NULL representation in the current Part 1 implementation.
        if values and all(INT_RE.fullmatch(value) for value in values):
            return "INT"

        if values and all(FLOAT_RE.fullmatch(value) for value in values):
            return "FLOAT"

        max_bytes = max(
            [len(value.encode("utf-8")) for value in values] + [1]
        )
        return f"VARCHAR({max_bytes})"

    @staticmethod
    def _coerce_csv_row(
        headers: Sequence[str],
        raw_row: Sequence[str],
        columns: Sequence[Mapping[str, str]],
    ) -> Dict[str, Any]:
        row: Dict[str, Any] = {}

        for header, raw_value, column in zip(headers, raw_row, columns):
            data_type = column["type"].upper()

            if data_type == "INT":
                row[header] = int(raw_value)
            elif data_type == "FLOAT":
                row[header] = float(raw_value)
            else:
                row[header] = raw_value

        return row

    @staticmethod
    def _validate_primary_key_values(
        rows: Sequence[Mapping[str, Any]],
        primary_key: str,
    ) -> None:
        seen = set()

        for position, row in enumerate(rows, start=2):
            value = row[primary_key]

            if value is None or value == "":
                raise TableManagementError(
                    f"primary key '{primary_key}' is empty at CSV row {position}"
                )

            if value in seen:
                raise TableManagementError(
                    f"duplicate primary key '{value}' at CSV row {position}"
                )

            seen.add(value)

    # -------------------------------------------------------------- schema

    @classmethod
    def _normalize_columns(
        cls,
        columns: Sequence[Mapping[str, str] | Sequence[str]],
    ) -> List[Dict[str, str]]:
        if not columns:
            raise TableManagementError(
                "at least one column is required"
            )

        result: List[Dict[str, str]] = []

        for item in columns:
            if isinstance(item, Mapping):
                raw_name = item.get("name", "")
                raw_type = item.get("type", "")
            else:
                if len(item) != 2:
                    raise TableManagementError(
                        "column tuple must contain (name, type)"
                    )
                raw_name, raw_type = item

            name = cls._normalize_identifier(
                str(raw_name),
                "column",
            )
            data_type = str(raw_type).strip().upper()

            if not data_type:
                raise TableManagementError(
                    f"column '{name}' requires a type"
                )

            result.append(
                {
                    "name": name,
                    "type": data_type,
                }
            )

        names = [column["name"] for column in result]
        if len(set(names)) != len(names):
            raise TableManagementError(
                "column names must be unique"
            )

        return result

    @staticmethod
    def _build_schema(
        columns: Sequence[Mapping[str, str]],
        primary_key: str,
    ) -> Schema:
        names = [column["name"] for column in columns]
        if primary_key not in names:
            raise TableManagementError(
                f"primary key '{primary_key}' is not one of the table columns"
            )

        try:
            return Schema(
                [
                    (column["name"], column["type"])
                    for column in columns
                ],
                primary_key=primary_key,
            )
        except Exception as exc:
            raise TableManagementError(str(exc)) from exc

    @staticmethod
    def _normalize_identifier(value: str, label: str) -> str:
        normalized = str(value).strip().lower()

        if not normalized:
            raise TableManagementError(
                f"{label} cannot be empty"
            )

        if not IDENTIFIER_RE.fullmatch(normalized):
            raise TableManagementError(
                f"invalid {label} '{value}'; use letters, numbers and "
                "underscores, and do not start with a number"
            )

        return normalized

    @staticmethod
    def _normalize_storage_kind(value: str) -> str:
        normalized = str(value).strip().lower()
        if normalized not in {"heap", "sequential"}:
            raise TableManagementError(
                "storage_kind must be 'heap' or 'sequential'"
            )
        return normalized

    # -------------------------------------------------------------- storage

    def _create_storage(
        self,
        name: str,
        storage_kind: str,
        schema: Schema,
    ) -> Any:
        if storage_kind == "heap":
            return HeapFile(
                str(self.data_dir / f"{name}.dat"),
                schema,
            )

        return SequentialFile(
            str(self.data_dir / name),
            schema,
        )

    def _expected_storage_paths(
        self,
        name: str,
        storage_kind: str,
    ) -> List[Path]:
        if storage_kind == "heap":
            # .free is created lazily by HeapFile, therefore only .dat is
            # mandatory for a persistent table.
            return [self.data_dir / f"{name}.dat"]

        return [
            self.data_dir / f"{name}.main",
            self.data_dir / f"{name}.aux",
        ]

    @staticmethod
    def _delete_storage_files(storage: Any) -> None:
        paths: List[str] = []

        if hasattr(storage, "path"):
            paths.extend(
                [
                    storage.path,
                    getattr(storage, "free_path", storage.path + ".free"),
                ]
            )
        else:
            paths.extend(
                [
                    storage.main_path,
                    storage.aux_path,
                ]
            )

        for raw_path in paths:
            path = Path(raw_path)
            if path.exists():
                path.unlink()

    # -------------------------------------------------------------- info

    @staticmethod
    def _count(storage: Any) -> int:
        return sum(1 for _ in storage.scan())

    @staticmethod
    def _storage_files(storage: Any) -> List[Tuple[str, str]]:
        if hasattr(storage, "path"):
            files = [("datos", storage.path)]
            free_path = getattr(storage, "free_path", None)
            if free_path:
                files.append(("espacio libre", free_path))
            return files

        return [
            ("principal", storage.main_path),
            ("auxiliar", storage.aux_path),
        ]

    def _table_info(self, table: TableMetadata) -> Dict[str, Any]:
        files = []

        for label, path in self._storage_files(table.storage):
            size = os.path.getsize(path) if os.path.exists(path) else 0
            files.append(
                {
                    "label": label,
                    "path": path,
                    "size_bytes": size,
                }
            )

        dynamic_metadata = self._dynamic_tables.get(table.name)

        return {
            "name": table.name,
            "storage_kind": table.storage_kind,
            "schema": table.schema.to_dict(),
            "indexes": [
                {
                    "name": item.metadata.name,
                    "column": item.metadata.column,
                    "kind": item.metadata.kind,
                    "unique": item.metadata.unique,
                }
                for item in table.indexes.values()
            ],
            "files": files,
            "row_count": self._count(table.storage),
            "record_size": table.schema.record_size,
            "source": (
                dynamic_metadata.get("source")
                if dynamic_metadata
                else "demo"
            ),
            "original_filename": (
                dynamic_metadata.get("original_filename")
                if dynamic_metadata
                else None
            ),
        }

    def _seed(self) -> None:
        for sql in SEED_SQL:
            result = self.executor.execute(sql)
            if not result.success:
                raise RuntimeError(
                    f"seed falló: {sql} -> {result.error}"
                )


engine = DemoEngine()
