import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from indexes.clustered_bplus import ClusteredBPlusIndex
from indexes.extendible_hash import ExtendibleHash
from indexes.rtree import RTree
from indexes.unclustered_bplus import UnclusteredBPlusIndex
from query.query_planner import IndexMetadata
from spatial.index import SpatialIndex
from storage.heap_file import HeapFile
from storage.record import Schema
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
    independent.  The catalog is the small integration layer that lets the
    executor resolve ``FROM users`` into a schema, a storage object and its
    available indexes.
    """

    def __init__(
        self,
        data_dir: Optional[Any] = None,
        on_change: Optional[Callable[[], None]] = None,
        *,
        rtree_max_entries: int = 16,
    ):
        self._tables: Dict[str, TableMetadata] = {}
        #: Directorio donde CREATE TABLE crea los archivos físicos. Sin él, la
        #: creación dinámica de tablas está deshabilitada (solo register_table).
        self.data_dir = Path(data_dir) if data_dir is not None else None
        #: Se invoca tras CREATE/DROP para que la capa que persiste el catálogo
        #: (backend/engine.py) guarde el manifiesto.
        self.on_change = on_change
        #: Capacidad M de los nodos del R-Tree (los índices espaciales tienen
        #: datasets grandes: 16 entradas por nodo es un valor razonable).
        self.rtree_max_entries = rtree_max_entries

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

    # ------------------------------------------------------------------
    # DDL: CREATE TABLE / DROP TABLE
    # ------------------------------------------------------------------

    def create_table(
        self,
        name: str,
        columns: Sequence[Tuple[str, str]],
        primary_key: Optional[str] = None,
        *,
        storage_kind: str = "heap",
        if_not_exists: bool = False,
        data_dir: Optional[Any] = None,
        primary_key_index: bool = True,
    ) -> TableMetadata:
        """Crea la tabla físicamente en disco y la registra en el catálogo."""
        key = self._normalize_identifier(name)

        if key in self._tables:
            if if_not_exists:
                return self._tables[key]
            raise CatalogError(f"la tabla ya existe: {name}")

        if not columns:
            raise CatalogError("CREATE TABLE requiere al menos una columna")

        kind = (storage_kind or "heap").strip().lower()
        if kind not in {"heap", "sequential"}:
            raise CatalogError("storage_kind must be 'heap' or 'sequential'")

        schema = Schema(list(columns), primary_key or columns[0][0])

        directory = Path(data_dir) if data_dir is not None else self.data_dir
        if directory is None:
            raise CatalogError(
                "el catálogo no tiene directorio de datos: crea el catálogo "
                "con Catalog(data_dir=...) para poder crear tablas por SQL"
            )
        directory.mkdir(parents=True, exist_ok=True)

        if kind == "heap":
            storage = HeapFile(str(directory / f"{key}.dat"), schema)
        else:
            storage = SequentialFile(str(directory / key), schema)

        table = self.register_table(
            key,
            storage,
            schema=schema,
            storage_kind=kind,
        )

        if primary_key_index:
            self.register_index(
                name=f"idx_{key}_{schema.primary_key}_hash",
                table=key,
                column=schema.primary_key,
                kind="hash",
                implementation=ExtendibleHash(
                    bucket_capacity=4,
                    unique=True,
                ),
                unique=True,
                rebuild=False,
            )

        self._notify()
        return table

    def drop_table(
        self,
        name: str,
        *,
        if_exists: bool = False,
        delete_files: bool = True,
    ) -> bool:
        """Quita la tabla del catálogo y (por defecto) borra sus archivos."""
        key = self._normalize_identifier(name)
        table = self._tables.get(key)

        if table is None:
            if if_exists:
                return False
            raise CatalogError(f"unknown table: {name}")

        paths = self._storage_paths(table)
        del self._tables[key]

        if delete_files:
            for path in paths:
                try:
                    os.remove(path)
                except OSError:
                    pass

        self._notify()
        return True

    @staticmethod
    def _storage_paths(table: TableMetadata) -> List[str]:
        if table.storage_kind == "heap":
            return [table.storage.path, table.storage.path + ".free"]
        return [table.storage.main_path, table.storage.aux_path]

    # ------------------------------------------------------------------
    # DDL: CREATE INDEX / DROP INDEX
    # ------------------------------------------------------------------

    #: Sufijo del nombre automático de cada técnica, para que el nombre generado
    #: sea estable y legible: idx_<tabla>_<columna>_<sufijo>.
    _INDEX_NAME_SUFFIX = {
        "hash": "hash",
        "bplus_clustered": "bpc",
        "bplus_unclustered": "bpu",
        "rtree": "rtree",
    }

    def index_names(self, table: str) -> List[str]:
        return sorted(self.get_table(table).indexes)

    def find_indexes_on_column(self, table: str, column: str) -> List[str]:
        return sorted(
            name
            for name, registered in self.get_table(table).indexes.items()
            if registered.metadata.column == column
        )

    def create_index(
        self,
        table: str,
        column: str,
        *,
        kind: str = "bplus_unclustered",
        unique: bool = False,
        name: Optional[str] = None,
        if_not_exists: bool = False,
        lon_column: Optional[str] = None,
    ) -> RegisteredIndex:
        """Crea y puebla un índice sobre una columna de una tabla existente.

        El índice se construye recorriendo el almacenamiento de la tabla, así
        que también funciona sobre datos que ya estaban cargados (el caso de
        la demo: cargar el CSV y después indexar).

        Para ``kind="rtree"`` la columna es la de **latitud** y hace falta
        indicar ``lon_column``; el índice se construye con carga masiva porque
        los datasets espaciales son grandes.
        """
        table_meta = self.get_table(table)
        normalized_kind = (kind or "").strip().lower()
        if normalized_kind not in self._INDEX_NAME_SUFFIX:
            raise CatalogError(
                "técnica de índice no soportada: "
                f"'{kind}' (usa hash, bplus_clustered, bplus_unclustered o rtree)"
            )

        resolved_column = (column or "").strip().lower()
        if resolved_column not in table_meta.schema.col_names():
            raise CatalogError(
                f"la columna '{column}' no existe en la tabla '{table_meta.name}'"
            )

        index_name = (
            self._normalize_identifier(name)
            if name
            else f"idx_{table_meta.name}_{resolved_column}_"
            f"{self._INDEX_NAME_SUFFIX[normalized_kind]}"
        )

        if index_name in table_meta.indexes:
            if if_not_exists:
                return table_meta.indexes[index_name]
            raise CatalogError(
                f"el índice '{index_name}' ya existe en la tabla "
                f"'{table_meta.name}'"
            )

        already = self.find_indexes_on_column(table_meta.name, resolved_column)
        if already:
            raise CatalogError(
                f"la columna '{resolved_column}' de '{table_meta.name}' ya tiene "
                f"el índice {', '.join(already)}; usa DROP INDEX antes de crear otro"
            )

        if normalized_kind == "bplus_clustered":
            # Clase (semana 03): "Solo puede existir UN índice agrupado por
            # tabla", porque los datos tienen un único orden físico.
            existentes = [
                r.metadata.name
                for r in table_meta.indexes.values()
                if r.metadata.kind == "bplus_clustered"
            ]
            if existentes:
                raise CatalogError(
                    f"solo puede existir un índice agrupado por tabla: "
                    f"'{table_meta.name}' ya tiene {existentes[0]} "
                    "(usa BPLUS_UNCLUSTERED o elimina el agrupado primero)"
                )

        if unique and normalized_kind != "hash":
            raise CatalogError(
                "solo el índice Hash Extendible soporta UNIQUE en este motor"
            )

        if normalized_kind == "rtree":
            if not lon_column:
                raise CatalogError(
                    "CREATE INDEX ... USING RTREE necesita la columna de "
                    "longitud: CREATE INDEX nombre ON tabla (lat, lon) USING RTREE"
                )
            resolved_lon = self._normalize_identifier(lon_column)
            if resolved_lon not in table_meta.schema.col_names():
                raise CatalogError(
                    f"la columna de longitud '{lon_column}' no existe en la "
                    f"tabla '{table_meta.name}'"
                )
            if resolved_lon == resolved_column:
                raise CatalogError(
                    "la latitud y la longitud no pueden ser la misma columna"
                )
            implementation = SpatialIndex(
                resolved_column,
                resolved_lon,
                max_entries=self.rtree_max_entries,
            )
        else:
            implementation = self._make_index(
                resolved_column, normalized_kind, unique
            )

        registered = self.register_index(
            name=index_name,
            table=table_meta.name,
            column=resolved_column,
            kind=normalized_kind,
            implementation=implementation,
            unique=unique,
            rebuild=True,
        )
        self._notify()
        return registered

    def drop_index(
        self,
        name: str,
        *,
        table: Optional[str] = None,
        if_exists: bool = False,
    ) -> bool:
        """Quita un índice del catálogo (solo metadatos: no hay archivos propios)."""
        index_key = self._normalize_identifier(name)

        if table is not None:
            candidates = [(self.get_table(table), index_key)]
        else:
            candidates = [
                (table_meta, index_key)
                for table_meta in self._tables.values()
                if index_key in table_meta.indexes
            ]

        if not candidates:
            if if_exists:
                return False
            raise CatalogError(f"no existe el índice '{name}'")

        table_meta, _ = candidates[0]
        if index_key not in table_meta.indexes:
            if if_exists:
                return False
            raise CatalogError(
                f"el índice '{name}' no existe en la tabla '{table_meta.name}'"
            )

        # El índice de la clave primaria es el que hace cumplir la unicidad:
        # sin él la tabla podría tener PK duplicadas, así que no se elimina.
        registered = table_meta.indexes[index_key]
        if registered.metadata.column == table_meta.schema.primary_key:
            raise CatalogError(
                f"no se puede eliminar '{index_key}': es el índice de la "
                f"PRIMARY KEY '{table_meta.schema.primary_key}' de "
                f"'{table_meta.name}' y es lo que garantiza que no haya "
                "claves primarias duplicadas"
            )

        del table_meta.indexes[index_key]
        self._notify()
        return True

    def _notify(self) -> None:
        if self.on_change is not None:
            self.on_change()

    # ------------------------------------------------------------------
    # Manifiesto (persistencia del catálogo entre reinicios)
    # ------------------------------------------------------------------

    def describe_tables(self) -> List[Dict[str, Any]]:
        """Definiciones serializables de todas las tablas registradas."""
        description = []
        for table in self._tables.values():
            description.append(
                {
                    "name": table.name,
                    "columns": [tuple(col) for col in table.schema.to_dict()["columnas"]],
                    "primary_key": table.schema.primary_key,
                    "storage_kind": table.storage_kind,
                    "indexes": [
                        {
                            "name": registered.metadata.name,
                            "column": registered.metadata.column,
                            "kind": registered.metadata.kind,
                            "unique": registered.metadata.unique,
                            # El R-Tree necesita también la longitud para
                            # reconstruirse al reiniciar.
                            **(
                                {"lon_column": registered.implementation.lon_column}
                                if registered.metadata.kind == "rtree"
                                else {}
                            ),
                        }
                        for registered in table.indexes.values()
                    ],
                }
            )
        return description

    def restore_table(
        self,
        definition: Dict[str, Any],
        *,
        data_dir: Optional[Any] = None,
    ) -> TableMetadata:
        """Recrea una tabla descrita por ``describe_tables`` (sin tocar los datos)."""
        directory = Path(data_dir) if data_dir is not None else self.data_dir
        if directory is None:
            raise CatalogError("restore_table requiere data_dir")

        name = self._normalize_identifier(definition["name"])
        columns = tuple(tuple(col) for col in definition["columns"])
        storage_kind = definition.get("storage_kind", "heap")

        path = (
            directory / f"{name}.dat"
            if storage_kind == "heap"
            else directory / name
        )
        schema = Schema(list(columns), definition["primary_key"])
        storage = (
            HeapFile(str(path), schema)
            if storage_kind == "heap"
            else SequentialFile(str(path), schema)
        )

        table = self.register_table(
            name,
            storage,
            schema=schema,
            storage_kind=storage_kind,
        )

        for index in definition.get("indexes", []):
            if index["kind"] == "rtree":
                # Parte 2: el R-Tree se restaura igual que los demás índices
                # (definición en el manifiesto + reconstrucción por carga
                # masiva). Antes fallaba con "unsupported index kind: rtree".
                lon_column = index.get("lon_column") or self._guess_lon_column(
                    table, index["column"]
                )
                implementation = SpatialIndex(
                    index["column"],
                    lon_column,
                    max_entries=self.rtree_max_entries,
                )
            else:
                implementation = self._make_index(
                    index["column"],
                    index["kind"],
                    bool(index.get("unique", False)),
                )
            self.register_index(
                name=index["name"],
                table=name,
                column=index["column"],
                kind=index["kind"],
                implementation=implementation,
                unique=bool(index.get("unique", False)),
                rebuild=True,
            )

        return table

    @staticmethod
    def _make_index(column: str, kind: str, unique: bool):
        if kind == "bplus_clustered":
            return ClusteredBPlusIndex(column, order=4, unique=unique)
        if kind == "bplus_unclustered":
            return UnclusteredBPlusIndex(column, order=4, unique=unique)
        if kind == "hash":
            return ExtendibleHash(bucket_capacity=4, unique=unique)
        raise CatalogError(f"unsupported index kind: {kind}")

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

        elif meta.kind == "rtree":
            # El R-Tree necesita latitud Y longitud. La envoltura recuerda su
            # columna de longitud; si se perdió (índice recién registrado), se
            # busca una columna cuyo nombre lo sugiera.
            lon_column = getattr(old, "lon_column", None) or self._guess_lon_column(
                table_meta, meta.column
            )
            new_index = SpatialIndex(
                meta.column,
                lon_column,
                max_entries=getattr(old, "max_entries", self.rtree_max_entries),
                metric=getattr(old, "metric", "haversine"),
            )
            # Carga masiva: los datasets espaciales son grandes (100 000 puntos)
            # y construir el árbol insertando uno a uno es ~38x más lento.
            new_index.bulk_load(
                (row, rid) for rid, row in table_meta.storage.scan()
            )

        else:  # guarded by IndexMetadata, but defensive for future extensions
            raise CatalogError(f"unsupported index kind: {meta.kind}")

        registered.implementation = new_index
        return registered

    @staticmethod
    def _guess_lon_column(table: TableMetadata, lat_column: str) -> str:
        """Deduce la columna de longitud emparejada con la de latitud."""
        candidates = table.schema.col_names()
        pares = {
            "lat": ("lon", "lng", "long", "longitud"),
            "latitud": ("longitud", "lon", "lng", "long"),
            "latitude": ("longitude", "lon", "lng", "long"),
            "y": ("x", "lon", "lng"),
        }
        buscados = pares.get(lat_column.lower())
        if buscados:
            for candidato in buscados:
                if candidato in candidates:
                    return candidato
            # Coincidencia por prefijo (p. ej. lat_centro -> lon_centro).
            sufijo = lat_column[3:] if lat_column.lower().startswith("lat") else ""
            for candidato in candidates:
                if candidato.lower() in {f"lon{sufijo}", f"lng{sufijo}", f"long{sufijo}"}:
                    return candidato

        raise CatalogError(
            "no se pudo deducir la columna de longitud para el índice espacial "
            f"de '{lat_column}'; vuelve a crearlo con USING RTREE"
        )

    def rebuild_indexes(self, table: str) -> None:
        table_meta = self.get_table(table)
        for name in list(table_meta.indexes):
            self.rebuild_index(table_meta.name, name)

    # ------------------------------------------------------------------
    # Espacial (Parte 2)
    # ------------------------------------------------------------------

    def spatial_indexes(self, table: Optional[str] = None) -> List[RegisteredIndex]:
        """Índices espaciales registrados (de una tabla o de todo el catálogo)."""
        tablas = (
            [self.get_table(table)] if table is not None
            else list(self._tables.values())
        )
        result: List[RegisteredIndex] = []
        for table_meta in tablas:
            for registered in table_meta.indexes.values():
                if registered.metadata.kind == "rtree":
                    result.append(registered)
        return result

    def spatial_index_for(
        self,
        table: str,
        column: str,
    ) -> Optional[RegisteredIndex]:
        """Índice espacial cuyo **RID cubre** la columna indicada.

        ``distancia(ubicacion, POINT(...))`` se resuelve tanto si ``ubicacion``
        es la columna de latitud del índice como si es la de longitud. Con
        ``column=""`` devuelve el primer índice espacial de la tabla.
        """
        table_meta = self.get_table(table)
        objetivo = (column or "").strip().lower()

        for registered in table_meta.indexes.values():
            if registered.metadata.kind != "rtree":
                continue
            if not objetivo:
                return registered
            implementation = registered.implementation
            if objetivo in {
                registered.metadata.column.lower(),
                str(getattr(implementation, "lon_column", "")).lower(),
                str(getattr(implementation, "lat_column", "")).lower(),
            }:
                return registered
        return None
