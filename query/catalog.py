from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from indexes.clustered_bplus import ClusteredBPlusIndex
from indexes.extendible_hash import ExtendibleHash
from indexes.unclustered_bplus import UnclusteredBPlusIndex
from query.query_planner import IndexMetadata
from storage.heap_file import HeapFile
from storage.sequential_file import SequentialFile


class CatalogError(Exception):
    pass


@dataclass
class RegisteredIndex:
    metadata: IndexMetadata
    implementation: Any


@dataclass
class TableMetadata:
    name: str
    schema: Any
    storage: Any
    storage_kind: str
    indexes: Dict[str, RegisteredIndex] = field(default_factory=dict)

    def read_rid(self, rid):
        if self.storage_kind == "heap":
            return self.storage.read(rid)
        return self.storage.read_rid(rid)


class Catalog:
    """Runtime registry that bridges SQL names with physical DB modules.

    The storage/index implementations in this project are intentionally kept
    independent. The catalog is the small integration layer that lets the
    executor resolve ``FROM users`` into a schema, a storage object and its
    available indexes.
    """

    def __init__(self):
        self._tables: Dict[str, TableMetadata] = {}

    @staticmethod
    def _normalize_identifier(name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise CatalogError("identifier must be a non-empty string")
        return name.strip().lower()

    @staticmethod
    def _infer_storage_kind(storage: Any) -> str:
        if isinstance(storage, HeapFile):
            return "heap"
        if isinstance(storage, SequentialFile):
            return "sequential"
        raise CatalogError(
            "cannot infer storage kind; pass storage_kind='heap' or 'sequential'"
        )

    def register_table(
        self,
        name: str,
        storage: Any,
        *,
        schema: Optional[Any] = None,
        storage_kind: Optional[str] = None,
        replace: bool = False,
    ) -> TableMetadata:
        key = self._normalize_identifier(name)
        if key in self._tables and not replace:
            raise CatalogError(f"table already registered: {name}")

        resolved_schema = schema or getattr(storage, "schema", None)
        if resolved_schema is None:
            raise CatalogError(f"schema is required for table: {name}")

        kind = (
            self._infer_storage_kind(storage)
            if storage_kind is None
            else storage_kind.strip().lower()
        )
        if kind not in {"heap", "sequential"}:
            raise CatalogError("storage_kind must be 'heap' or 'sequential'")

        table = TableMetadata(
            name=key,
            schema=resolved_schema,
            storage=storage,
            storage_kind=kind,
        )
        self._tables[key] = table
        return table

    def unregister_table(self, name: str) -> TableMetadata:
        """Remove a table from the runtime catalog.

        This method only removes the in-memory registration. Physical files
        are deliberately managed by the backend/engine layer, which owns the
        table lifecycle and can therefore perform an atomic rollback.
        """
        key = self._normalize_identifier(name)
        try:
            return self._tables.pop(key)
        except KeyError as exc:
            raise CatalogError(f"unknown table: {name}") from exc

    def get_table(self, name: str) -> TableMetadata:
        key = self._normalize_identifier(name)
        try:
            return self._tables[key]
        except KeyError as exc:
            raise CatalogError(f"unknown table: {name}") from exc

    def has_table(self, name: str) -> bool:
        try:
            key = self._normalize_identifier(name)
        except CatalogError:
            return False
        return key in self._tables

    def register_index(
        self,
        *,
        name: str,
        table: str,
        column: str,
        kind: str,
        implementation: Any,
        unique: Optional[bool] = None,
        rebuild: bool = False,
    ) -> RegisteredIndex:
        table_meta = self.get_table(table)
        index_name = self._normalize_identifier(name)
        normalized_kind = kind.strip().lower()

        if index_name in table_meta.indexes:
            raise CatalogError(f"index already registered: {name}")
        if column not in table_meta.schema.col_names():
            raise CatalogError(
                f"unknown indexed column '{column}' in table '{table}'"
            )

        inferred_unique = bool(getattr(implementation, "unique", False))
        metadata = IndexMetadata(
            name=index_name,
            table=table_meta.name,
            column=column,
            kind=normalized_kind,
            unique=inferred_unique if unique is None else bool(unique),
        )
        registered = RegisteredIndex(metadata, implementation)
        table_meta.indexes[index_name] = registered

        if rebuild:
            self.rebuild_index(table_meta.name, index_name)

        return registered

    def get_index(self, table: str, name: str) -> RegisteredIndex:
        table_meta = self.get_table(table)
        key = self._normalize_identifier(name)
        try:
            return table_meta.indexes[key]
        except KeyError as exc:
            raise CatalogError(
                f"unknown index '{name}' for table '{table}'"
            ) from exc

    def planner_indexes(self) -> List[IndexMetadata]:
        result: List[IndexMetadata] = []
        for table in self._tables.values():
            result.extend(item.metadata for item in table.indexes.values())
        return result

    def planner_storage(self) -> Dict[str, str]:
        return {
            table.name: table.storage_kind
            for table in self._tables.values()
        }

    def table_names(self) -> List[str]:
        return sorted(self._tables)

    def rebuild_index(self, table: str, index_name: str) -> RegisteredIndex:
        table_meta = self.get_table(table)
        registered = self.get_index(table, index_name)
        old = registered.implementation
        meta = registered.metadata

        if meta.kind == "bplus_clustered":
            new_index = ClusteredBPlusIndex(
                meta.column,
                order=getattr(old, "order", 4),
                unique=meta.unique,
            )
            for _, row in table_meta.storage.scan():
                new_index.insert(row)

        elif meta.kind == "bplus_unclustered":
            new_index = UnclusteredBPlusIndex(
                meta.column,
                order=getattr(old, "order", 4),
                unique=meta.unique,
            )
            for rid, row in table_meta.storage.scan():
                new_index.insert(row, rid)

        elif meta.kind == "hash":
            new_index = ExtendibleHash(
                bucket_capacity=getattr(old, "bucket_capacity", 4),
                unique=meta.unique,
                hash_func=getattr(old, "hash_func", None),
                max_depth=getattr(old, "max_depth", 64),
            )
            for rid, row in table_meta.storage.scan():
                new_index.insert(row[meta.column], rid)

        else:
            raise CatalogError(f"unsupported index kind: {meta.kind}")

        registered.implementation = new_index
        return registered

    def rebuild_indexes(self, table: str) -> None:
        table_meta = self.get_table(table)
        for name in list(table_meta.indexes):
            self.rebuild_index(table_meta.name, name)
