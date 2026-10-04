"""Catálogo de demostración y ejecutor SQL.

Construye el Catalog con tablas físicas reales (HeapFile y SequentialFile),
registra los índices (Hash extendible, B+ agrupado y no agrupado) y expone el
QueryExecutor del proyecto. El frontend nunca habla con el storage: solo con
este módulo, vía backend/api.py.
"""

from __future__ import annotations

import json
import math
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Tuple

from indexes.clustered_bplus import ClusteredBPlusIndex
from indexes.extendible_hash import ExtendibleHash
from indexes.unclustered_bplus import UnclusteredBPlusIndex
from query.catalog import Catalog, CatalogError, TableMetadata
from query.csv_loader import CsvImportReport, import_csv as import_csv_into
from query.query_executor import QueryExecutor
from query.query_result import QueryResult
from storage.heap_file import HeapFile
from storage.record import Schema
from storage.sequential_file import SequentialFile

# El enunciado solo soporta INT, FLOAT y VARCHAR(n): no hay BOOL.
USERS_SCHEMA = Schema(
    [("id", "INT"), ("name", "VARCHAR(32)"), ("age", "INT"), ("dept", "VARCHAR(16)")],
    primary_key="id",
)
EMPLOYEES_SCHEMA = Schema(
    [("id", "INT"), ("name", "VARCHAR(32)"), ("dept", "VARCHAR(16)"), ("salary", "FLOAT")],
    primary_key="id",
)
DEPARTMENTS_SCHEMA = Schema(
    [("id", "INT"), ("name", "VARCHAR(32)"), ("city", "VARCHAR(24)")],
    primary_key="id",
)

SEED_SQL = [
    ("users", "INSERT INTO users VALUES (1, 'Ana Torres', 20, 'CS')"),
    ("users", "INSERT INTO users VALUES (2, 'Luis Paredes', 23, 'EE')"),
    ("users", "INSERT INTO users VALUES (3, 'Mia Rojas', 19, 'CS')"),
    ("users", "INSERT INTO users VALUES (4, 'Karla Ruiz', 25, 'EE')"),
    ("employees", "INSERT INTO employees VALUES (10, 'Ana Torres', 'CS', 3200.0)"),
    ("employees", "INSERT INTO employees VALUES (11, 'Luis Paredes', 'EE', 4800.0)"),
    ("employees", "INSERT INTO employees VALUES (12, 'Mia Rojas', 'CS', 5100.0)"),
    ("employees", "INSERT INTO employees VALUES (13, 'Karla Ruiz', 'EE', 3900.0)"),
    ("departments", "INSERT INTO departments VALUES (1, 'Ciencias de la Computacion', 'Lima')"),
    ("departments", "INSERT INTO departments VALUES (2, 'Ingenieria Electronica', 'Arequipa')"),
]


class DemoEngine:
    """Une el motor real del proyecto con una API pensada para el frontend."""

    #: Tablas creadas por código: no entran en el manifiesto del catálogo.
    DEMO_TABLES = {"users", "employees", "departments"}

    def __init__(self, data_dir: str | Path | None = None, seed: bool = True) -> None:
        base = data_dir or os.environ.get("BD2_DATA_DIR") or (
            Path(__file__).resolve().parent / "data"
        )
        self.data_dir = Path(base)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.catalog_path = self.data_dir / "catalog.json"
        self._lock = threading.Lock()  # el motor no es thread-safe: serializamos
        self._ready = False

        # Heap File (.dat + .free)
        self.users = HeapFile(str(self.data_dir / "users.dat"), USERS_SCHEMA)
        self.departments = HeapFile(str(self.data_dir / "departments.dat"), DEPARTMENTS_SCHEMA)
        # Archivo Secuencial Paginado: el constructor agrega .main y .aux
        self.employees = SequentialFile(str(self.data_dir / "employees"), EMPLOYEES_SCHEMA)

        self.catalog = Catalog(
            data_dir=self.data_dir,
            on_change=self._save_catalog,
        )
        self.catalog.register_table("users", self.users)
        self.catalog.register_table("employees", self.employees)
        self.catalog.register_table("departments", self.departments)

        self.catalog.register_index(
            name="idx_users_id_hash", table="users", column="id", kind="hash",
            implementation=ExtendibleHash(bucket_capacity=4, unique=True), rebuild=True,
        )
        self.catalog.register_index(
            name="idx_emp_salary_bplus", table="employees", column="salary",
            kind="bplus_clustered", implementation=ClusteredBPlusIndex("salary", order=4),
            rebuild=True,
        )
        self.catalog.register_index(
            name="idx_emp_dept_bplus", table="employees", column="dept",
            kind="bplus_unclustered", implementation=UnclusteredBPlusIndex("dept", order=4),
            rebuild=True,
        )

        self.executor = QueryExecutor(self.catalog)
        self.restored_tables = self._load_catalog()
        self._ready = True

        if seed:
            self._seed()

    # ------------------------------------------------------------------ API

    def run(self, sql: str) -> QueryResult:
        with self._lock:
            return self.executor.execute(sql)

    def import_csv(
        self,
        table: str,
        source: Any,
        **options: Any,
    ) -> CsvImportReport:
        """Carga un CSV en una tabla existente (mismo camino que INSERT).

        El API recibe el **texto** del CSV, así que un argumento de una sola
        línea sin comas se trata como error de nombre de archivo y no como
        contenido (``allow_path=False``), para no reportar "0 filas" como éxito.
        """
        options.setdefault("allow_path", False)
        with self._lock:
            report = import_csv_into(self.executor, table, source, **options)
            self._save_catalog()
            return report

    def tables(self) -> List[Dict[str, Any]]:
        return [self._table_info(self.catalog.get_table(n)) for n in self.catalog.table_names()]

    def transaction_state(self) -> Optional[Dict[str, Any]]:
        """Transacción activa del motor, o ``None`` si no hay BEGIN pendiente.

        El frontend lo usa para avisar de que hay una transacción abierta sin
        confirmar (es el estado que el enunciado pide poder demostrar).
        """
        txn = self.executor.transaction
        if txn is None or not txn.active:
            return None
        return {
            "id": txn.id,
            "statements": txn.statements,
            "tables": sorted(txn.snapshots),
            "locked_tables": list(txn.locked_tables),
            "active": True,
        }

    # ------------------------------------------------------------ espacial

    def spatial_query(
        self,
        table_name: str,
        *,
        kind: str = "range",
        lat: float = -12.0464,
        lon: float = -77.0428,
        radius_m: float = 5000.0,
        k: int = 10,
        metric: str = "haversine",
        polygon: Optional[List[List[float]]] = None,
    ) -> Dict[str, Any]:
        """Ejecuta una consulta espacial y la devuelve lista para el mapa.

        Es el camino que usa el panel de mapa: construye la consulta SQL
        equivalente y la ejecuta con el motor, así el R-Tree se usa igual que en
        el panel de consultas (una sola ruta de código, no dos).
        """
        lat_column, lon_column = self._spatial_columns(
            self.catalog.get_table(table_name), table_name
        )
        point = f"POINT({lat!r}, {lon!r})"

        if kind == "knn":
            sql = (
                f"SELECT * FROM {table_name} "
                f"ORDER BY distancia({lat_column}, {point}, {metric}) "
                f"LIMIT {int(k)}"
            )
        elif kind == "polygon":
            if not polygon or len(polygon) < 3:
                raise CatalogError(
                    "la consulta por polígono necesita al menos 3 vértices "
                    "[[lat, lon], ...]"
                )
            vertices = ", ".join(
                f"{float(par[0])!r} {float(par[1])!r}" for par in polygon
            )
            sql = (
                f"SELECT * FROM {table_name} "
                f"WHERE dentro_de({lat_column}, POLYGON(({vertices})))"
            )
        else:
            sql = (
                f"SELECT * FROM {table_name} "
                f"WHERE distancia({lat_column}, {point}, {metric}) <= {float(radius_m)!r}"
            )

        resultado = self.run(sql)
        plan = resultado.execution_plan or {}

        points = []
        for row in resultado.rows:
            entry = {
                "lat": row.get("_lat"),
                "lon": row.get("_lon"),
                "distance_m": row.get("_distance"),
                "label": self._label_of(row),
                "row": {
                    clave: valor
                    for clave, valor in row.items()
                    if not clave.startswith("_")
                },
            }
            points.append(entry)

        return {
            "success": resultado.success,
            "kind": kind,
            "metric": metric,
            "table": table_name,
            "sql": sql,
            "access_path": plan.get("access_path"),
            "used_indexes": plan.get("used_indexes", []),
            "execution_time_ms": resultado.execution_time_ms,
            "distance_unit": "m" if metric == "haversine" else "grados",
            "count": len(points),
            "candidates_visited": self._candidates_visited(plan),
            "points": points,
            "error": resultado.error,
        }

    @staticmethod
    def _candidates_visited(plan: Dict[str, Any]) -> Optional[int]:
        """Cuántos candidatos visitó el R-Tree, si el plan lo reporta."""
        for paso in plan.get("steps", []):
            detalles = paso.get("details") or {}
            if "candidates" in detalles:
                return detalles["candidates"]
        return None

    def spatial_points(
        self,
        table_name: str,
        *,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Puntos de una tabla espacial, para el panel de mapa (Parte 2).

        Devuelve las coordenadas y el ``bounds`` para que el frontend pueda
        dibujar el mapa sin recorrer la tabla. Se apoya en el índice R-Tree si
        existe, y si no, en un escaneo del almacenamiento.
        """
        table = self.catalog.get_table(table_name)
        registered = self.catalog.spatial_index_for(table_name, "")
        lat_column, lon_column = self._spatial_columns(table, table_name)

        points: List[Dict[str, Any]] = []
        bounds = [math.inf, -math.inf, math.inf, -math.inf]

        for rid, row in table.storage.scan():
            try:
                lat = float(row[lat_column])
                lon = float(row[lon_column])
            except (KeyError, TypeError, ValueError):
                continue
            points.append(
                {
                    "rid": repr(rid),
                    "lat": lat,
                    "lon": lon,
                    "label": self._label_of(row),
                    "row": dict(row),
                }
            )
            bounds[0] = min(bounds[0], lat)
            bounds[1] = max(bounds[1], lat)
            bounds[2] = min(bounds[2], lon)
            bounds[3] = max(bounds[3], lon)

        if limit is not None and limit > 0:
            points = points[:limit]

        return {
            "table": table.name,
            "lat_column": lat_column,
            "lon_column": lon_column,
            "label_column": self._label_column(table),
            "count": len(points),
            "bounds": (
                {
                    "min_lat": bounds[0],
                    "max_lat": bounds[1],
                    "min_lon": bounds[2],
                    "max_lon": bounds[3],
                }
                if points
                else None
            ),
            "index": registered.metadata.name if registered else None,
            "points": points,
        }

    @staticmethod
    def _label_column(table: TableMetadata) -> Optional[str]:
        """Columna que sirve de etiqueta legible (nombre/name/label)."""
        columnas = [c.lower() for c in table.schema.col_names()]
        for candidato in ("nombre", "name", "titulo", "label", "descripcion"):
            if candidato in columnas:
                return candidato
        return None

    @classmethod
    def _label_of(cls, row: Dict[str, Any]) -> str:
        columna = cls._label_column_from_row(row)
        if columna:
            return str(row[columna])
        return ""

    @staticmethod
    def _label_column_from_row(row: Dict[str, Any]) -> Optional[str]:
        for candidato in ("nombre", "name", "titulo", "label", "descripcion"):
            for clave in row:
                if str(clave).lower() == candidato:
                    return clave
        return None

    def _spatial_columns(self, table: TableMetadata, table_name: str):
        """(lat_column, lon_column) de la tabla espacial."""
        registered = self.catalog.spatial_index_for(table_name, "")
        if registered is not None:
            implementation = registered.implementation
            return implementation.lat_column, implementation.lon_column

        # Sin índice: se deducen por el nombre de las columnas.
        columnas = {c.lower(): c for c in table.schema.col_names()}
        for lat_name, lon_names in (
            ("lat", ("lon", "lng", "long", "longitud")),
            ("latitud", ("longitud", "lon", "lng")),
            ("latitude", ("longitude", "lon", "lng")),
        ):
            if lat_name in columnas:
                for lon_name in lon_names:
                    if lon_name in columnas:
                        return columnas[lat_name], columnas[lon_name]
        raise CatalogError(
            f"'{table_name}' no tiene columnas espaciales reconocibles; "
            "usa nombres lat/lon o crea el índice con "
            "CREATE INDEX ... ON tabla (lat, lon) USING RTREE"
        )

    def table_info(self, name: str) -> Dict[str, Any]:
        return self._table_info(self.catalog.get_table(name))

    def catalog_manifest(self) -> Dict[str, Any]:
        return {
            "path": str(self.catalog_path),
            "tables": [
                definition
                for definition in self.catalog.describe_tables()
                if definition["name"] not in self.DEMO_TABLES
            ],
        }

    # -------------------------------------------------------- persistencia

    def _save_catalog(self) -> None:
        if not self._ready:
            return

        payload = {
            "tables": [
                definition
                for definition in self.catalog.describe_tables()
                if definition["name"] not in self.DEMO_TABLES
            ]
        }

        try:
            self.catalog_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            # La persistencia del catálogo no debe romper una sentencia DDL.
            pass

    def _load_catalog(self) -> List[str]:
        if not self.catalog_path.exists():
            return []

        try:
            payload = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

        restored: List[str] = []
        for definition in payload.get("tables", []):
            name = str(definition.get("name", "")).lower()
            if not name or self.catalog.has_table(name):
                continue
            try:
                self.catalog.restore_table(definition, data_dir=self.data_dir)
                restored.append(name)
            except Exception as exc:  # manifiesto corrupto o archivos movidos
                print(f"[catalog] no se pudo restaurar '{name}': {exc}")

        return restored

    # -------------------------------------------------------------- interno

    @staticmethod
    def _count(storage: Any) -> int:
        return sum(1 for _ in storage.scan())

    @staticmethod
    def _storage_files(storage: Any) -> List[Tuple[str, str]]:
        if hasattr(storage, "path"):                       # HeapFile
            return [("datos", storage.path)]
        return [("principal", storage.main_path), ("auxiliar", storage.aux_path)]

    def _table_info(self, table: TableMetadata) -> Dict[str, Any]:
        files = []
        for label, path in self._storage_files(table.storage):
            size = os.path.getsize(path) if os.path.exists(path) else 0
            files.append({"label": label, "path": path, "size_bytes": size})
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
        }

    def _seed(self) -> None:
        """Carga los datos de demostración solo en las tablas que están vacías.

        Se revisa tabla por tabla: si el usuario borró (DROP/CREATE) o vació solo
        una de ellas, el API debe arrancar igual y sembrar únicamente esa.
        """
        pendientes = {
            name: storage
            for name, storage in (
                ("users", self.users),
                ("employees", self.employees),
                ("departments", self.departments),
            )
            if self._count(storage) == 0
        }
        if not pendientes:
            return

        for table, sql in SEED_SQL:
            if table not in pendientes:
                continue
            result = self.executor.execute(sql)
            if not result.success:
                raise RuntimeError(f"seed falló: {sql} -> {result.error}")


# Instancia única que usa el API (los archivos viven en backend/data/)
engine = DemoEngine()