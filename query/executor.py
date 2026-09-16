"""
Ejecutor minimo de consultas relacionales (Parte 1, seccion 2.1.3).

Encadena las piezas ya implementadas por el equipo:

    SQL  ->  SQLParser  ->  QuerySpec  ->  QueryPlanner  ->  QueryPlan
                                                |
                                                v
                        acceso a storage (Heap File / Archivo Secuencial)
                        + indices (B+ agrupado / B+ no agrupado / Hash)
                        + External Sort  (ORDER BY)
                        + External Hashing (GROUP BY y JOIN)

Alcance (a proposito acotado, como pide el enunciado: "no es necesario
implementar todo el estandar SQL"):

- SELECT [cols | * | agregados] FROM tabla [JOIN ...] [WHERE ...]
  [GROUP BY ...] [ORDER BY ...]
- INSERT INTO tabla VALUES (...)
- DELETE FROM tabla [WHERE ...]

Fuera de alcance: CREATE TABLE (el catalogo se arma por codigo), LIMIT,
subconsultas y transacciones (issue aparte del equipo).
"""

import re
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from indexes.clustered_bplus import ClusteredBPlusIndex
from indexes.extendible_hash import ExtendibleHash
from indexes.unclustered_bplus import UnclusteredBPlusIndex
from operators.external_hashing import ExternalHashing
from operators.external_sort import ExternalSort
from query.query_planner import (
    EQUALITY_OPERATORS,
    IndexMetadata,
    Predicate,
    QueryPlan,
    QueryPlanner,
    QuerySpec,
)
from query.sql_parser import (
    DeleteStatement,
    InsertStatement,
    SelectStatement,
    SQLParser,
)
from storage.record import Schema


AGGREGATE_PATTERN = re.compile(
    r"^(COUNT|SUM|AVG|MIN|MAX)\s*\(\s*(\*|[A-Za-z0-9_]+)\s*\)$",
    re.IGNORECASE,
)

INDEX_LOOKUP_OPERATORS = {
    "HASH_INDEX_LOOKUP",
    "BPLUS_CLUSTERED_LOOKUP",
    "BPLUS_UNCLUSTERED_LOOKUP",
}

INDEX_RANGE_OPERATORS = {
    "BPLUS_CLUSTERED_RANGE_SCAN",
    "BPLUS_UNCLUSTERED_RANGE_SCAN",
}

INDEX_ORDER_OPERATORS = {
    "BPLUS_CLUSTERED_INDEX_SCAN",
    "BPLUS_UNCLUSTERED_INDEX_SCAN",
}


# ----------------------------------------------------------------------
# Catalogo
# ----------------------------------------------------------------------


@dataclass
class IndexHandle:
    """Relaciona una columna con el indice que la acelera."""

    column: str
    kind: str  # "hash" | "bplus_clustered" | "bplus_unclustered"
    index: Any
    factory: Optional[Callable[[], Any]] = None

    def rebuild(self):
        """Crea una instancia nueva y vacia del mismo tipo de indice."""
        if self.factory is None:
            raise ValueError(
                "IndexHandle sin factory: no se puede reconstruir el indice "
                f"de la columna '{self.column}'"
            )

        self.index = self.factory()
        return self.index

    @property
    def name(self):
        return f"idx_{self.kind}"


def hash_index(
    column: str,
    bucket_capacity: int = 64,
    unique: bool = False,
    hash_func: Optional[Callable[[Any], int]] = None,
) -> IndexHandle:
    """Indice Hash Extendible sobre `column` (valores = RID)."""

    def factory():
        return ExtendibleHash(
            bucket_capacity=bucket_capacity,
            unique=unique,
            hash_func=hash_func,
        )

    return IndexHandle(column, "hash", factory(), factory)


def clustered_index(
    column: str,
    order: int = 64,
    unique: bool = False,
) -> IndexHandle:
    """Indice B+ agrupado sobre `column` (las hojas guardan el registro)."""

    def factory():
        return ClusteredBPlusIndex(
            key_field=column,
            order=order,
            unique=unique,
        )

    return IndexHandle(column, "bplus_clustered", factory(), factory)


def unclustered_index(
    column: str,
    order: int = 64,
    unique: bool = False,
) -> IndexHandle:
    """Indice B+ no agrupado sobre `column` (las hojas guardan RIDs)."""

    def factory():
        return UnclusteredBPlusIndex(
            key_field=column,
            order=order,
            unique=unique,
        )

    return IndexHandle(column, "bplus_unclustered", factory(), factory)


@dataclass
class TableDefinition:
    name: str
    schema: Schema
    storage: Any
    storage_kind: str = "heap"
    indexes: Dict[str, IndexHandle] = field(default_factory=dict)

    def index_for(self, column: str) -> Optional[IndexHandle]:
        return self.indexes.get(column)

    def add_index(self, handle: IndexHandle):
        self.indexes[handle.column] = handle

    # ---------------------- mantenimiento de indices ----------------------
    def index_insert(self, record: dict, rid):
        for handle in self.indexes.values():
            if handle.kind == "bplus_clustered":
                # Las hojas del B+ agrupado guardan el registro completo.
                handle.index.insert(record)
            elif handle.kind == "bplus_unclustered":
                # El B+ no agrupado extrae la clave del propio registro.
                handle.index.insert(record, rid)
            else:
                # Hash Extendible: (clave, RID).
                handle.index.insert(record[handle.column], rid)

    def index_delete(self, record: dict, rid):
        for handle in self.indexes.values():
            if handle.kind == "bplus_clustered":
                handle.index.delete(record[handle.column], record)
            else:
                handle.index.delete(record[handle.column], rid)

    def rebuild_indexes(self) -> int:
        """
        Reconstruye todos los indices a partir del storage actual.

        Es obligatorio despues de `SequentialFile.reorganizar()`, porque la
        reorganizacion reescribe `.main` y **todos los RID cambian**.
        """
        rebuilt = 0

        for handle in self.indexes.values():
            handle.rebuild()
            rebuilt += 1

        for rid, record in self.scan():
            self.index_insert(record, rid)

        return rebuilt

    # ---------------------- acceso ----------------------
    def scan(self) -> Iterable[Tuple[Any, dict]]:
        return self.storage.scan()

    def read_rid(self, rid):
        if self.storage_kind == "sequential":
            return self.storage.read_rid(rid)
        return self.storage.read(rid)

    def insert(self, record: dict):
        rid = self.storage.insert(record)
        self.index_insert(record, rid)
        return rid

    def delete(self, record: dict, rid) -> bool:
        if self.storage_kind == "sequential":
            removed = self.storage.delete(record[self.schema.primary_key])
        else:
            removed = self.storage.delete(rid)

        if removed:
            self.index_delete(record, rid)

        return removed


class Catalog:
    """Catalogo en memoria: nombre de tabla -> TableDefinition."""
    def __init__(self):
        self.tables: Dict[str, TableDefinition] = {}

    def register(self, table: TableDefinition) -> TableDefinition:
        self.tables[table.name] = table
        return table

    def table(self, name: str) -> TableDefinition:
        try:
            return self.tables[name]
        except KeyError:
            raise KeyError(f"tabla desconocida: {name}") from None

    def index_metadata(self) -> List[IndexMetadata]:
        metadata = []

        for table in self.tables.values():
            for handle in table.indexes.values():
                metadata.append(
                    IndexMetadata(
                        name=f"{table.name}_{handle.column}_{handle.kind}",
                        table=table.name,
                        column=handle.column,
                        kind=handle.kind,
                        unique=bool(getattr(handle.index, "unique", False)),
                    )
                )

        return metadata

    def storage_map(self) -> Dict[str, str]:
        return {
            table.name: table.storage_kind for table in self.tables.values()
        }


# ----------------------------------------------------------------------
# Resultado
# ----------------------------------------------------------------------


@dataclass
class ExecutionResult:
    statement_kind: str
    rows: List[dict]
    plan: Optional[QueryPlan] = None
    affected: int = 0
    stats: Dict[str, Any] = field(default_factory=dict)

    def explain(self) -> str:
        if self.plan is None:
            return f"{self.statement_kind}: sin plan (operacion de escritura)"

        return self.plan.explain()


# ----------------------------------------------------------------------
# Ejecutor
# ----------------------------------------------------------------------


class QueryExecutor:
    def __init__(
        self,
        catalog: Catalog,
        planner: Optional[QueryPlanner] = None,
        sorter: Optional[ExternalSort] = None,
        hasher: Optional[ExternalHashing] = None,
        memory_limit_records: int = 64,
        temp_dir: Optional[str] = None,
    ):
        self.catalog = catalog
        self.parser = SQLParser()
        self.planner = planner or QueryPlanner(
            indexes=catalog.index_metadata(),
            storage_by_table=catalog.storage_map(),
        )
        self.sorter = sorter or ExternalSort(
            memory_limit_records=memory_limit_records,
            temp_dir=temp_dir,
        )
        self.hasher = hasher or ExternalHashing(
            memory_limit_records=memory_limit_records,
            temp_dir=temp_dir,
        )

    # ---------------------- API publica ----------------------
    def execute_sql(self, sql: str) -> ExecutionResult:
        return self.execute(self.parser.parse(sql))

    def execute(self, statement) -> ExecutionResult:
        if isinstance(statement, SelectStatement):
            return self._execute_select(statement)
        if isinstance(statement, InsertStatement):
            return self._execute_insert(statement)
        if isinstance(statement, DeleteStatement):
            return self._execute_delete(statement)

        raise TypeError(f"sentencia no soportada: {type(statement).__name__}")

    def explain_sql(self, sql: str) -> str:
        statement = self.parser.parse(sql)

        if not isinstance(statement, SelectStatement):
            return f"{type(statement).__name__}: operacion de escritura"

        return self.planner.plan(statement.query_spec).explain()

    # ---------------------- SELECT ----------------------
    def _execute_select(self, statement: SelectStatement) -> ExecutionResult:
        spec = statement.query_spec
        table = self.catalog.table(spec.table)
        plan = self.planner.plan(spec)

        rows = self._access_rows(table, spec, plan)
        rows = self._apply_predicates(rows, spec.predicates)

        stats: Dict[str, Any] = {"access_path": plan.access_path}

        for join in spec.joins:
            right = self.catalog.table(join.table)
            right_rows = [record for _rid, record in right.scan()]
            rows = self.hasher.hash_join(
                rows,
                right_rows,
                left_key=join.left_column,
                right_key=join.right_column,
                join_type=join.join_type,
                merge=lambda left, right_record: {**left, **right_record},
            )
            stats["join"] = {
                "table": join.table,
                "left": self.hasher.last_stats.left_records,
                "right": self.hasher.last_stats.right_records,
                "output": self.hasher.last_stats.output_records,
            }

        aggregates = self._parse_aggregates(statement.columns)

        if spec.group_by or aggregates:
            rows = self._group_rows(rows, spec, aggregates, statement.columns)
            stats["group_by"] = self.hasher.last_stats.operation

        if self._needs_sort(spec, plan):
            rows = self._sort_rows(rows, spec)

        rows = self._project(rows, statement.columns, aggregates)

        return ExecutionResult(
            statement_kind="SELECT",
            rows=rows,
            plan=plan,
            stats=stats,
        )

    def _access_rows(self, table: TableDefinition, spec: QuerySpec, plan: QueryPlan):
        step = plan.steps[0] if plan.steps else None

        if step is None or not step.index:
            return [record for _rid, record in table.scan()]

        handle = table.index_for(step.details.get("column"))
        if handle is None:
            return [record for _rid, record in table.scan()]

        predicate = step.details.get("predicate")

        if step.operator in INDEX_LOOKUP_OPERATORS and predicate:
            return self._lookup(table, handle, predicate["value"])

        if step.operator in INDEX_RANGE_OPERATORS and predicate:
            return self._range_scan(table, handle, predicate)

        if step.operator in INDEX_ORDER_OPERATORS:
            return self._ordered_scan(table, handle)

        return [record for _rid, record in table.scan()]

    def _lookup(self, table: TableDefinition, handle: IndexHandle, value):
        if handle.kind == "bplus_clustered":
            return list(handle.index.search(value))

        return self._materialize(table, handle.index.search(value))

    def _range_scan(self, table: TableDefinition, handle: IndexHandle, predicate):
        operator = str(predicate["operator"]).lower()
        start = end = None
        include_start = include_end = True

        if operator == "between":
            low, high = predicate["value"]
            start, end = low, high
        elif operator in (">", ">="):
            start = predicate["value"]
            include_start = operator == ">="
        else:  # "<", "<="
            end = predicate["value"]
            include_end = operator == "<="

        if handle.kind == "bplus_clustered":
            return list(
                handle.index.range_search(
                    start=start,
                    end=end,
                    include_start=include_start,
                    include_end=include_end,
                )
            )

        rids = handle.index.range_search(
            start=start,
            end=end,
            include_start=include_start,
            include_end=include_end,
        )
        return self._materialize(table, rids)

    def _ordered_scan(self, table: TableDefinition, handle: IndexHandle):
        if handle.kind == "bplus_clustered":
            return list(handle.index.scan())

        return self._materialize(table, handle.index.scan())

    def _materialize(self, table: TableDefinition, rids: Sequence[Any]):
        records = []

        for rid in rids:
            record = table.read_rid(rid)
            if record is not None:
                records.append(record)

        return records

    # ---------------------- filtros, grupo, orden, proyeccion ----------------------
    @staticmethod
    def _apply_predicates(rows: Sequence[dict], predicates: Sequence[Predicate]):
        if not predicates:
            return list(rows)

        return [
            record
            for record in rows
            if all(_matches(record, predicate) for predicate in predicates)
        ]

    def _group_rows(
        self,
        rows: Sequence[dict],
        spec: QuerySpec,
        aggregates: Mapping[str, Any],
        columns: Sequence[str],
    ):
        key: Union[str, Tuple[str, ...]]

        if len(spec.group_by) == 1:
            key = spec.group_by[0]
        elif spec.group_by:
            key = tuple(spec.group_by)
        else:
            # Sin GROUP BY explicito pero con agregados: una sola fila global.
            key = lambda _record: 0  # noqa: E731

        if not aggregates:
            aggregates = {"count": "count"}

        return self.hasher.group_by(
            rows,
            key=key,
            aggregates=dict(aggregates),
        )

    def _sort_rows(self, rows: Sequence[dict], spec: QuerySpec):
        ordered = list(rows)

        # Orden estable aplicado de derecha a izquierda: respeta la
        # direccion (ASC/DESC) de cada columna del ORDER BY.
        for item in reversed(spec.order_by):
            ordered = self.sorter.sort(
                ordered,
                key=item.column,
                descending=item.descending,
            )

        return ordered

    @staticmethod
    def _needs_sort(spec: QuerySpec, plan: QueryPlan) -> bool:
        if not spec.order_by:
            return False

        return any(step.operator == "EXTERNAL_SORT" for step in plan.steps)

    @staticmethod
    def _parse_aggregates(columns: Sequence[str]) -> Dict[str, Any]:
        aggregates: Dict[str, Any] = {}

        for column in columns:
            match = AGGREGATE_PATTERN.match(column.strip())
            if not match:
                continue

            operation = match.group(1).lower()
            source = match.group(2)

            if source == "*":
                aggregates[column.strip()] = "count"
            elif operation == "count":
                aggregates[column.strip()] = ("count", source)
            else:
                aggregates[column.strip()] = (operation, source)

        return aggregates

    @staticmethod
    def _project(
        rows: Sequence[dict],
        columns: Sequence[str],
        aggregates: Mapping[str, Any],
    ):
        wanted = [column.strip() for column in columns]

        if wanted == ["*"]:
            return [dict(row) for row in rows]

        projected = []

        for row in rows:
            record = {}

            for column in wanted:
                if column in row:
                    record[column] = row[column]
                elif column in aggregates:
                    record[column] = row.get(column)

            projected.append(record)

        return projected

    # ---------------------- INSERT / DELETE ----------------------
    def _execute_insert(self, statement: InsertStatement) -> ExecutionResult:
        table = self.catalog.table(statement.table)
        values = statement.values

        if len(values) != len(table.schema.fields):
            raise ValueError(
                f"INSERT espera {len(table.schema.fields)} valores, "
                f"recibio {len(values)}"
            )

        record = {
            field.name: value
            for field, value in zip(table.schema.fields, values)
        }

        rid = table.insert(record)

        return ExecutionResult(
            statement_kind="INSERT",
            rows=[record],
            affected=1,
            stats={"rid": repr(rid)},
        )

    def _execute_delete(self, statement: DeleteStatement) -> ExecutionResult:
        table = self.catalog.table(statement.table)
        matches = [
            (rid, record)
            for rid, record in table.scan()
            if all(
                _matches(record, predicate)
                for predicate in statement.predicates
            )
        ]

        removed = 0
        for rid, record in matches:
            if table.delete(record, rid):
                removed += 1

        return ExecutionResult(
            statement_kind="DELETE",
            rows=[record for _rid, record in matches],
            affected=removed,
            stats={"matched": len(matches)},
        )


# ----------------------------------------------------------------------
# Evaluacion de predicados
# ----------------------------------------------------------------------


def _matches(record: dict, predicate: Predicate) -> bool:
    if predicate.column not in record:
        return False

    value = record[predicate.column]
    operator = predicate.normalized_operator()
    target = predicate.value

    if operator in EQUALITY_OPERATORS:
        return value == target
    if operator in ("!=", "<>"):
        return value != target
    if operator == "between":
        low, high = target
        return low <= value <= high

    try:
        if operator == "<":
            return value < target
        if operator == "<=":
            return value <= target
        if operator == ">":
            return value > target
        if operator == ">=":
            return value >= target
    except TypeError:
        return False

    raise ValueError(f"operador de predicado no soportado: {operator}")
