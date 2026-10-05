import itertools
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from indexes.clustered_bplus import ClusteredBPlusIndex
from indexes.extendible_hash import ExtendibleHash
from indexes.unclustered_bplus import UnclusteredBPlusIndex
from operators.external_hashing import ExternalHashing
from operators.external_sort import ExternalSort
from query.catalog import Catalog, CatalogError, RegisteredIndex, TableMetadata
from query.query_planner import (
    EQUALITY_OPERATORS,
    OrderBy,
    Predicate,
    QueryPlanner,
    replace_candidate,
)
from query.query_result import QueryResult
from query.spatial_queries import (
    SpatialExecutor,
    SpatialQueryError,
    find_distance_predicate,
    find_polygon_predicate,
    find_spatial_order_by,
    find_spatial_predicate,
    spatial_kind,
)
from spatial.geo import euclidean, haversine
from query.sql_parser import (
    CreateIndexStatement,
    CreateTableStatement,
    DeleteStatement,
    DropIndexStatement,
    DropTableStatement,
    ExplainStatement,
    InsertStatement,
    SQLParser,
    SelectStatement,
    SetVariableStatement,
    TransactionStatement,
    UpdateStatement,
)
from transactions.lock_manager import LockManager


class QueryExecutionError(Exception):
    pass


class _CaseInsensitiveRow(dict):
    """Fila que resuelve sus columnas sin distinguir mayúsculas.

    Los nombres de tabla ya se normalizan en el catálogo, pero los de columna
    se comparaban literalmente: ``SELECT ID FROM alumnos`` fallaba mientras
    ``FROM ALUMNOS`` funcionaba. SQL es insensible a mayúsculas en
    identificadores, así que la fila mantiene las claves canónicas del esquema y
    acepta cualquier variante al consultarlas.
    """

    def __init__(self, mapping: Optional[Dict[str, Any]] = None):
        super().__init__(mapping or {})
        self._canonicas = {
            str(clave).lower(): clave for clave in dict.keys(self)
        }

    def _resolver(self, clave):
        if dict.__contains__(self, clave):
            return clave
        if isinstance(clave, str):
            return self._canonicas.get(clave.lower(), clave)
        return clave

    def __getitem__(self, clave):
        return dict.__getitem__(self, self._resolver(clave))

    def __contains__(self, clave):
        return dict.__contains__(self, self._resolver(clave))

    def get(self, clave, default=None):
        return dict.get(self, self._resolver(clave), default)

    def __setitem__(self, clave, valor):
        dict.__setitem__(self, clave, valor)
        if isinstance(clave, str):
            self._canonicas[clave.lower()] = clave

    def copy(self):
        return _CaseInsensitiveRow(self)

    def __reduce__(self):
        # Una subclase de dict con estado extra necesita un reductor explícito
        # para poder serializarse (p. ej. hacia los operadores externos).
        return (_CaseInsensitiveRow, (dict(self),))


@dataclass
class TransactionState:
    """Estado de una transacción agrupada con BEGIN TRANSACTION.

    ``snapshots`` guarda, por tabla y **una sola vez por transacción**, los
    registros que existían antes de la primera escritura. Revertir una fila
    completa es la forma más simple de garantizar que el ROLLBACK deja la tabla
    exactamente como estaba (incluidos los cambios de RID que provocan la
    reorganización del Archivo Secuencial y los rebuild de índices).
    """

    id: str
    active: bool = True
    statements: int = 0
    #: table name -> {"definition": {...}, "rows": [row, ...]}
    snapshots: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    #: tables eliminadas dentro de la transacción (snapshot con sus filas)
    dropped_tables: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    #: pasos DDL a revertir, en orden inverso al registro
    ddl_undo: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)
    #: tablas bloqueadas con PX por esta transacción
    locked_tables: List[str] = field(default_factory=list)


_AGGREGATE_RE = re.compile(
    r"^\s*(COUNT|SUM|AVG|MIN|MAX)\s*\(\s*(\*|[A-Za-z_][A-Za-z0-9_]*)\s*\)"
    r"(?:\s+AS\s+([A-Za-z_][A-Za-z0-9_]*))?\s*$",
    re.IGNORECASE,
)

#: Clave de agrupación cuando el SELECT tiene agregados pero no GROUP BY:
#: todas las filas forman un único grupo (COUNT(*) sobre toda la tabla).
_SINGLE_GROUP = "__todas_las_filas__"


class QueryExecutor:
    """Executes the project's SQL AST against the existing storage modules.

    Supported integration path:
      SQLParser -> QueryPlanner -> physical storage/index/operator -> QueryResult

    The executor deliberately keeps the SQL surface small (as required by the
    project) while centralizing WHERE, INSERT, DELETE, GROUP BY and ORDER BY so
    those rules are not duplicated in the future frontend/API.
    """

    def __init__(
        self,
        catalog: Catalog,
        *,
        parser: Optional[SQLParser] = None,
        external_sort: Optional[ExternalSort] = None,
        external_hashing: Optional[ExternalHashing] = None,
        lock_manager: Optional[LockManager] = None,
    ):
        self.catalog = catalog
        self.parser = parser or SQLParser()
        #: Variables de sesión espaciales (``SET mi_ubicacion = POINT(...)``).
        #: Es el mismo diccionario que consulta el parser al leer
        #: ``distancia(ubicacion, mi_ubicacion)``.
        if not hasattr(self.parser, "variables"):
            self.parser.variables = {}
        self.variables: Dict[str, Tuple[float, float]] = self.parser.variables
        self.external_sort = external_sort or ExternalSort()
        self.external_hashing = external_hashing or ExternalHashing()
        # Manejador de bloqueos compartido por todas las transacciones del
        # proceso (la demo de concurrencia lo usa directamente).
        self.lock_manager = lock_manager or LockManager()
        self._transaction_counter = itertools.count(1)
        self._transaction: Optional[TransactionState] = None
        #: Último contador de reorganizaciones visto por tabla: permite saber si
        #: un INSERT en Archivo Secuencial invalidó los RID de los índices.
        self._sequential_reorgs: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        sql_or_statement: Union[
            str,
            SelectStatement,
            InsertStatement,
            DeleteStatement,
            UpdateStatement,
            CreateTableStatement,
            CreateIndexStatement,
            DropTableStatement,
            DropIndexStatement,
            TransactionStatement,
            ExplainStatement,
        ],
        *,
        raise_on_error: bool = False,
        variables: Optional[Dict[str, Any]] = None,
    ) -> QueryResult:
        started = time.perf_counter()
        statement_name = "UNKNOWN"

        try:
            if variables:
                self.set_variables(variables)
            statement = (
                self.parser.parse(sql_or_statement)
                if isinstance(sql_or_statement, str)
                else sql_or_statement
            )
            statement_name = self._statement_name(statement)

            if isinstance(statement, TransactionStatement):
                return self._execute_transaction(statement)

            if isinstance(statement, SetVariableStatement):
                self.variables[statement.name] = statement.point
                lat, lon = statement.point
                return QueryResult.ok(
                    "SET",
                    columns=["variable", "lat", "lon"],
                    rows=[{"variable": statement.name, "lat": lat, "lon": lon}],
                    affected_rows=1,
                    execution_time_ms=self._elapsed_ms(started),
                )

            if isinstance(statement, SelectStatement):
                result = self._execute_select(statement)
            elif isinstance(statement, InsertStatement):
                result = self._execute_insert(statement)
            elif isinstance(statement, DeleteStatement):
                result = self._execute_delete(statement)
            elif isinstance(statement, UpdateStatement):
                result = self._execute_update(statement)
            elif isinstance(statement, CreateTableStatement):
                result = self._execute_create_table(statement)
            elif isinstance(statement, CreateIndexStatement):
                result = self._execute_create_index(statement)
            elif isinstance(statement, DropTableStatement):
                result = self._execute_drop_table(statement)
            elif isinstance(statement, DropIndexStatement):
                result = self._execute_drop_index(statement)
            elif isinstance(statement, ExplainStatement):
                result = self._execute_explain(statement)
            else:
                raise QueryExecutionError(
                    f"unsupported statement object: {type(statement).__name__}"
                )

            result.execution_time_ms = self._elapsed_ms(started)
            if result.execution_plan is not None:
                result.execution_plan["total_execution_time_ms"] = (
                    result.execution_time_ms
                )
            return result

        except Exception as exc:
            if raise_on_error:
                raise
            return QueryResult.fail(
                statement_name,
                exc,
                execution_time_ms=self._elapsed_ms(started),
            )

    def set_variables(self, variables: Dict[str, Any]) -> None:
        """Define variables de sesión espaciales desde el API o el frontend.

        Acepta ``{"mi_ubicacion": [lat, lon]}`` o ``{"mi_ubicacion":
        {"lat": .., "lon": ..}}``. Es lo que usa el panel de mapa para que la
        consulta del enunciado ``ORDER BY distancia(ubicacion, mi_ubicacion)``
        funcione tal cual con el punto en el que el usuario hizo clic.
        """
        for name, value in (variables or {}).items():
            if isinstance(value, dict):
                lat, lon = value.get("lat"), value.get("lon")
            else:
                lat, lon = value
            lat, lon = float(lat), float(lon)
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                raise QueryExecutionError(
                    f"variable '{name}': coordenadas fuera de rango"
                )
            self.variables[str(name).lstrip("@").lower()] = (lat, lon)

    # ------------------------------------------------------------------
    # SELECT
    # ------------------------------------------------------------------

    def _execute_select(self, statement: SelectStatement) -> QueryResult:
        statement = self._resolve_select_names(statement)
        query = statement.query_spec
        table = self.catalog.get_table(query.table)
        self._validate_columns_for_select(statement, table)

        # --- Parte 2: consultas espaciales -------------------------------
        # Si el WHERE o el ORDER BY usan distancia(...) y la tabla tiene un
        # índice R-Tree, se resuelve con el índice en lugar de escanear.
        espacial = spatial_kind(query)
        if espacial is not None:
            resultado = self._execute_spatial(statement, table, espacial)
            if resultado is not None:
                return resultado

        planner = self._planner()
        # Con OR el planner intenta una unión de búsquedas por índice; si no
        # hay un índice común a todos los grupos, cae a un escaneo y el filtro
        # por grupos decide qué filas pasan.
        plan = planner.plan(query)
        runtime_steps: List[Dict[str, Any]] = []

        access_started = time.perf_counter()
        rows = self._execute_access_path(table, plan)
        self._append_runtime(
            runtime_steps,
            plan.steps[0].operator,
            access_started,
            rows_out=len(rows),
            table=table.name,
            index=plan.steps[0].index,
        )

        # Applying all predicates again is intentional: an index identifies
        # candidate rows, while this shared evaluator remains the final
        # correctness gate for SELECT and DELETE.
        # El planner puede haber fusionado varios predicados en un solo rango
        # (>= 19 AND <= 23 -> BETWEEN). El filtro final vuelve a los originales
        # para no cambiar el significado del WHERE.
        filter_predicates = self._filter_predicates_for(query)
        if filter_predicates:
            filter_started = time.perf_counter()
            rows_in = len(rows)
            detalles_espaciales = None

            # Con OR los predicados no son una conjunción: se evalúan los grupos
            # completos (una fila pasa si cumple CUALQUIER grupo).
            if query.or_groups:
                rows = [row for row in rows if self._matches_query(query, row)]
            else:
                # Los predicados espaciales no se pueden evaluar con un simple
                # comparador: se resuelven calculando la distancia real (camino
                # sin índice espacial), y los normales con el evaluador habitual.
                espaciales = [
                    p for p in filter_predicates
                    if getattr(p, "is_spatial", False)
                    and getattr(p, "distance", None) is not None
                ]
                if espaciales:
                    rows, detalles_espaciales = self._apply_spatial_predicates(
                        rows, espaciales
                    )
                normas = [
                    p for p in filter_predicates
                    if not (
                        getattr(p, "is_spatial", False)
                        and getattr(p, "distance", None) is not None
                    )
                ]
                if normas:
                    rows = [row for row in rows if self.matches_all(row, normas)]

            self._append_runtime(
                runtime_steps,
                "FILTER",
                filter_started,
                rows_in=rows_in,
                rows_out=len(rows),
                predicates=[
                    self._predicate_dict(p) for p in filter_predicates
                ],
                disjunction=bool(query.or_groups),
                spatial_details=detalles_espaciales,
            )

        if query.joins:
            rows = self._execute_joins(rows, query.joins, runtime_steps)

        aggregate_specs = self._parse_aggregate_columns(statement.columns)
        aggregated_without_group = bool(aggregate_specs) and not query.group_by
        if query.group_by:
            group_started = time.perf_counter()
            rows_in = len(rows)
            group_key = (
                query.group_by[0]
                if len(query.group_by) == 1
                else tuple(query.group_by)
            )
            rows = self.external_hashing.group_by(
                rows,
                key=group_key,
                aggregates=aggregate_specs or None,
            )
            stats = self.external_hashing.last_stats
            self._append_runtime(
                runtime_steps,
                "EXTERNAL_HASH_GROUP_BY",
                group_started,
                rows_in=rows_in,
                rows_out=len(rows),
                partitions_created=stats.partitions_created,
                repartition_passes=stats.repartition_passes,
                temporary_files=stats.temporary_files,
            )
        elif aggregated_without_group:
            # Sin GROUP BY un agregado resume TODA la tabla: hay un único
            # grupo, así que no hace falta particionar en disco. Se calcula
            # directamente sobre las filas ya filtradas.
            group_started = time.perf_counter()
            rows = self._aggregate_all(rows, aggregate_specs)
            self._append_runtime(
                runtime_steps,
                "AGGREGATE_ALL_ROWS",
                group_started,
                rows_in=len(rows),
                rows_out=len(rows),
                aggregates=list(aggregate_specs),
            )

        if query.order_by and any(
            step.operator == "EXTERNAL_SORT" for step in plan.steps
        ):
            rows = self._execute_order_by(rows, query.order_by, runtime_steps)

        if aggregated_without_group:
            # La única fila resultante ya trae los agregados calculados.
            return QueryResult.ok(
                "SELECT",
                columns=list(aggregate_specs),
                rows=[self._row(row) for row in rows],
                affected_rows=len(rows),
                execution_plan={**plan.to_dict(), "runtime_steps": runtime_steps},
            )

        projected_rows, columns = self._project_rows(
            rows,
            statement.columns,
            grouped=bool(query.group_by),
        )

        if statement.limit is not None:
            limit_started = time.perf_counter()
            rows_in = len(projected_rows)
            projected_rows = projected_rows[: statement.limit]
            self._append_runtime(
                runtime_steps,
                "LIMIT",
                limit_started,
                rows_in=rows_in,
                rows_out=len(projected_rows),
                limit=statement.limit,
            )

        plan_payload = plan.to_dict()
        plan_payload["runtime_steps"] = runtime_steps

        return QueryResult.ok(
            "SELECT",
            columns=columns,
            rows=projected_rows,
            affected_rows=len(projected_rows),
            execution_plan=plan_payload,
        )

    @staticmethod
    def _apply_spatial_predicates(rows, predicates):
        """Filtra filas evaluando ``distancia(...)`` sobre cada una.

        Es el camino **sin índice espacial**: correcto pero ``O(n)``. Se usa
        cuando no hay R-Tree (o cuando la consulta no se pudo resolver con él),
        para no devolver resultados incorrectos. Incluye el nombre de las
        columnas en la traza para que el plan explique qué se hizo.
        """
        detalles = []
        filtradas = list(rows)

        for predicate in predicates:
            expression = getattr(predicate, "distance", None)
            if expression is None:
                continue

            columnas = [
                clave for clave in (filtradas[0].keys() if filtradas else ())
            ]
            lat_column = QueryExecutor._match_spatial_column(
                columnas, expression.column
            )
            lon_column = QueryExecutor._match_lon_column(columnas, lat_column)

            detalles.append(
                {
                    "column": expression.column,
                    "lat_column": lat_column,
                    "lon_column": lon_column,
                    "operator": predicate.operator,
                    "value": predicate.value,
                    "metric": expression.metric,
                }
            )

            if lat_column is None or lon_column is None:
                # No se pueden resolver las coordenadas: no se puede evaluar la
                # distancia. Se devuelve vacío en lugar de dejar pasar todo.
                return [], detalles

            umbral = float(predicate.value)
            operador = predicate.operator
            conservadas = []
            for row in filtradas:
                try:
                    lat = float(row[lat_column])
                    lon = float(row[lon_column])
                except (TypeError, ValueError):
                    continue
                if expression.metric == "euclidean":
                    distancia = euclidean(expression.point, (lat, lon))
                else:
                    distancia = haversine(expression.point, (lat, lon))

                if operador == "<":
                    pasa = distancia < umbral
                elif operador == "<=":
                    pasa = distancia <= umbral
                elif operador == ">":
                    pasa = distancia > umbral
                else:
                    pasa = distancia >= umbral

                if pasa:
                    row = dict(row)
                    row["_distance"] = distancia
                    row["_lat"] = lat
                    row["_lon"] = lon
                    conservadas.append(row)

            filtradas = conservadas

        return filtradas, detalles

    @staticmethod
    def _match_spatial_column(columnas, buscada: str) -> Optional[str]:
        """Encuentra la columna de latitud a partir de la columna del índice."""
        objetivo = (buscada or "").strip().lower()
        for columna in columnas:
            if str(columna).lower() == objetivo:
                return columna
        # El índice puede estar declarado sobre la longitud: se deduce la latitud.
        if objetivo in {"lon", "lng", "long", "longitud"}:
            for candidata in ("lat", "latitud", "latitude", "y"):
                for columna in columnas:
                    if str(columna).lower() == candidata:
                        return columna
        return None

    @staticmethod
    def _match_lon_column(columnas, lat_column: Optional[str]) -> Optional[str]:
        """Deduce la columna de longitud a partir de la de latitud."""
        if lat_column is None:
            return None
        nombre = str(lat_column).lower()
        pares = {
            "lat": ("lon", "lng", "long", "longitud"),
            "latitud": ("longitud", "lon", "lng", "long"),
            "latitude": ("longitude", "lon", "lng", "long"),
            "y": ("x", "lon", "lng"),
        }
        for candidata in pares.get(nombre, ("lon", "lng", "long", "longitud")):
            for columna in columnas:
                if str(columna).lower() == candidata:
                    return columna
        return None

    def _resolve_select_names(self, statement: SelectStatement) -> SelectStatement:
        """Normaliza a los nombres del esquema las columnas de un SELECT.

        Se hace antes de planificar porque el planner compara el nombre de la
        columna del índice con el del predicado: si no coinciden en mayúsculas,
        el índice no se usaría aunque exista.
        """
        if not self.catalog.has_table(statement.query_spec.table):
            return statement

        table = self.catalog.get_table(statement.query_spec.table)

        def normalizar(predicate: Predicate) -> Predicate:
            canonica = self._canonical_column_in(table, predicate.column)
            if canonica is None or canonica == predicate.column:
                # Se conserva el predicado tal cual (incluido su campo
                # ``distance`` si es un predicado espacial).
                return predicate
            return Predicate(
                canonica,
                predicate.operator,
                predicate.value,
                distance=getattr(predicate, "distance", None),
            )

        query = statement.query_spec
        spec = replace(
            query,
            predicates=tuple(normalizar(p) for p in query.predicates),
            or_groups=tuple(
                tuple(normalizar(p) for p in group)
                for group in query.or_groups
            ),
            order_by=tuple(
                OrderBy(
                    self._canonical_column_in(table, item.column) or item.column,
                    item.descending,
                    distance=getattr(item, "distance", None),
                )
                for item in query.order_by
            ),
            group_by=tuple(
                self._canonical_column_in(table, column) or column
                for column in query.group_by
            ),
        )

        def canonica_proyeccion(expression: str) -> str:
            if expression == "*" or self._parse_aggregate_expression(expression):
                return expression
            if "." in expression:
                # Sólo se normaliza si el calificador es la tabla principal: una
                # columna calificada de la tabla unida (employees.name) no debe
                # confundirse con la homónima de la tabla de la izquierda.
                calificador, plain = expression.rsplit(".", 1)
                if calificador.strip().lower() != table.name.lower():
                    return expression
                return self._canonical_column_in(table, plain) or expression
            return self._canonical_column_in(table, expression) or expression

        columns = tuple(canonica_proyeccion(e) for e in statement.columns)

        spec = self._resolve_spatial_aliases(spec, table)

        if spec == query and columns == statement.columns:
            return statement
        return replace(statement, columns=columns, query_spec=spec)

    # ------------------------------------------------------------------
    # Columna espacial virtual: ``ubicacion`` = (lat, lon)  (Parte 2)
    # ------------------------------------------------------------------

    _LAT_NAMES = ("lat", "latitud", "latitude", "y")
    _LON_NAMES = ("lon", "lng", "long", "longitud", "longitude", "x")

    def _spatial_column_for(self, table: TableMetadata, column: str) -> str:
        """Traduce el primer argumento de ``distancia(...)``/``dentro_de(...)``.

        El enunciado escribe ``distancia(ubicacion, POINT(...))``: ``ubicacion``
        no es una columna física sino el **punto** formado por (lat, lon). Se
        resuelve así, en este orden:

        1. Si es una columna de la tabla, se usa tal cual (``distancia(lat, ...)``).
        2. Si es el **nombre de un índice R-Tree**, se usa su par (lat, lon).
        3. Si la tabla tiene **un solo** índice R-Tree, ``ubicacion`` (o
           cualquier nombre que no sea columna) es su punto.
        4. Sin índice espacial: se busca un par de columnas lat/lon por nombre
           (``lat``/``lon``, ``latitud``/``longitud``...) y se resuelve con
           escaneo + distancia exacta.

        Devuelve la columna de **latitud**, que es la que identifica al índice.
        """
        canonica = self._canonical_column_in(table, column)
        if canonica is not None:
            return canonica

        objetivo = column.strip().lower()
        rtrees = [
            r for r in table.indexes.values() if r.metadata.kind == "rtree"
        ]
        for registered in rtrees:
            if registered.metadata.name.lower() == objetivo:
                return registered.implementation.lat_column
        if len(rtrees) == 1:
            return rtrees[0].implementation.lat_column
        if len(rtrees) > 1:
            nombres = ", ".join(r.metadata.name for r in rtrees)
            raise QueryExecutionError(
                f"'{column}' es ambiguo: '{table.name}' tiene varios índices "
                f"R-Tree ({nombres}); usa el nombre del índice o la columna de "
                "latitud como primer argumento de distancia(...)"
            )

        columnas = {c.lower(): c for c in table.schema.col_names()}
        for lat_name in self._LAT_NAMES:
            if lat_name in columnas and any(
                lon_name in columnas for lon_name in self._LON_NAMES
            ):
                return columnas[lat_name]

        raise QueryExecutionError(
            f"'{column}' no es una columna de '{table.name}' ni hay un índice "
            "espacial que la defina. Crea el índice con CREATE INDEX "
            f"idx_{table.name}_ubicacion ON {table.name} (lat, lon) USING RTREE"
        )

    def _resolve_spatial_aliases(self, spec, table: TableMetadata):
        """Reescribe ``ubicacion`` a la columna de latitud del índice espacial."""

        def predicado(p):
            if not getattr(p, "is_spatial", False):
                return p
            real = self._spatial_column_for(table, p.column)
            if real == p.column:
                return p
            if p.distance is not None:
                return replace(
                    p, column=real, distance=replace(p.distance, column=real)
                )
            return replace(p, column=real)  # PolygonPredicate

        def orden(item):
            if not getattr(item, "is_spatial", False):
                return item
            real = self._spatial_column_for(table, item.distance.column)
            if real == item.column and real == item.distance.column:
                return item
            return replace(
                item, column=real, distance=replace(item.distance, column=real)
            )

        return replace(
            spec,
            predicates=tuple(predicado(p) for p in spec.predicates),
            or_groups=tuple(
                tuple(predicado(p) for p in group) for group in spec.or_groups
            ),
            order_by=tuple(orden(item) for item in spec.order_by),
        )

    def _resolve_dml_names(self, statement):
        """Normaliza a los nombres del esquema las columnas de UPDATE/DELETE."""
        if not self.catalog.has_table(statement.table):
            return statement

        table = self.catalog.get_table(statement.table)

        def normalizar(predicate: Predicate) -> Predicate:
            canonica = self._canonical_column_in(table, predicate.column)
            if canonica is None or canonica == predicate.column:
                # Se conserva el predicado tal cual (incluido su campo
                # ``distance`` si es un predicado espacial).
                return predicate
            return Predicate(
                canonica,
                predicate.operator,
                predicate.value,
                distance=getattr(predicate, "distance", None),
            )

        cambios = {
            "predicates": tuple(
                normalizar(p) for p in getattr(statement, "predicates", ())
            ),
            "or_groups": tuple(
                tuple(normalizar(p) for p in group)
                for group in getattr(statement, "or_groups", ())
            ),
        }
        if hasattr(statement, "assignments"):
            cambios["assignments"] = tuple(
                (
                    self._canonical_column_in(table, column) or column,
                    value,
                )
                for column, value in statement.assignments
            )

        return replace(statement, **cambios)

    # ------------------------------------------------------------------
    # SELECT espacial (Parte 2)
    # ------------------------------------------------------------------

    def _execute_spatial(
        self,
        statement: SelectStatement,
        table: TableMetadata,
        kind: str,
    ) -> Optional[QueryResult]:
        """Ejecuta una consulta espacial con el R-Tree.

        Devuelve ``None`` si la tabla no tiene índice espacial para esa columna:
        en ese caso la consulta sigue por el camino normal (escaneo + filtro),
        que es correcto aunque más lento, y el plan lo refleja.
        """
        query = statement.query_spec
        spatial = SpatialExecutor(self.catalog)

        try:
            if kind == "knn":
                order_by = find_spatial_order_by(query)
                if order_by is None:
                    return None
                k = statement.limit
                if k is None:
                    raise SpatialQueryError(
                        "ORDER BY distancia(...) necesita LIMIT k para ser una "
                        "búsqueda de k vecinos más cercanos"
                    )
                rows, plan = spatial.execute_knn(table, order_by, k)

            elif kind == "range":
                predicate = find_distance_predicate(query)
                if predicate is None:
                    return None
                rows, plan = spatial.execute_range(
                    table, predicate, limit=statement.limit
                )
                # El resto de predicados (no espaciales) se aplican aquí.
                otras = [
                    p for p in query.predicates
                    if not getattr(p, "is_spatial", False)
                ]
                if otras:
                    rows = [
                        row for row in rows
                        if self.matches_all(row, otras)
                    ]
                    plan["steps"].append(
                        {
                            "operator": "FILTER",
                            "table": table.name,
                            "index": None,
                            "reason": "predicados no espaciales del WHERE",
                            "details": {
                                "predicates": [
                                    self._predicate_dict(p) for p in otras
                                ]
                            },
                        }
                    )
            elif kind == "polygon":
                polygon = find_polygon_predicate(query)
                if polygon is None:
                    return None
                registered = self.catalog.spatial_index_for(
                    table.name, polygon.column
                )
                if registered is None:
                    return None
                index = registered.implementation
                # La expresión espacial del polígono lleva su propia columna.
                from query.query_planner import DistanceExpression

                rows, plan = spatial.execute_polygon(
                    table,
                    DistanceExpression(
                        polygon.column,
                        (polygon.ring[0][0], polygon.ring[0][1]),
                    ),
                    polygon.ring,
                )
            else:
                return None

        except SpatialQueryError as exc:
            # Sin índice espacial (o consulta mal formada): se devuelve el error
            # como resultado legible, igual que el resto del motor.
            if "no tiene índice R-Tree" in str(exc):
                return None
            raise QueryExecutionError(str(exc))

        projected, columns = self._project_rows(
            rows, statement.columns, grouped=False
        )
        return QueryResult.ok(
            "SELECT",
            columns=columns,
            rows=projected,
            affected_rows=len(projected),
            execution_plan={**plan, "spatial": True, "kind": kind},
        )

    # ------------------------------------------------------------------
    # INSERT
    # ------------------------------------------------------------------

    def _execute_insert(self, statement: InsertStatement) -> QueryResult:
        table = self.catalog.get_table(statement.table)
        columns = table.schema.col_names()

        if len(statement.values) != len(columns):
            raise QueryExecutionError(
                f"INSERT expected {len(columns)} values for table "
                f"'{table.name}', got {len(statement.values)}"
            )

        self._snapshot_for_write(table)
        row = dict(zip(columns, statement.values))
        runtime_steps: List[Dict[str, Any]] = []
        started = time.perf_counter()
        rid = table.storage.insert(row)

        try:
            # SequentialFile may reorganize immediately and invalidate the RID
            # returned by insert(). Rebuild only when a reorganization actually
            # happened: rebuilding on every row makes bulk CSV loads O(n^2).
            if table.storage_kind == "sequential":
                reorganizaciones = getattr(table.storage, "n_reorganizaciones", 0)
                if reorganizaciones != self._sequential_reorgs.get(table.name):
                    self._sequential_reorgs[table.name] = reorganizaciones
                    pk_value = row[table.schema.primary_key]
                    rid, stored = table.storage.search(pk_value)
                    if rid is None or stored is None:
                        raise QueryExecutionError(
                            "insert succeeded but record could not be resolved "
                            "after reorganization"
                        )
                    self.catalog.rebuild_indexes(table.name)
                else:
                    self._index_insert(table, row, rid)
            else:
                self._index_insert(table, row, rid)
        except Exception:
            # Keep storage and indexes atomic enough for this educational
            # engine: if an index rejects the row, undo the physical insert.
            if table.storage_kind == "heap":
                table.storage.delete(rid)
            else:
                table.storage.delete(row[table.schema.primary_key])
                if table.indexes:
                    self.catalog.rebuild_indexes(table.name)
            raise

        self._register_transaction_statement()

        self._append_runtime(
            runtime_steps,
            "INSERT",
            started,
            rows_in=1,
            rows_out=1,
            table=table.name,
            rid=repr(rid),
        )

        return QueryResult.ok(
            "INSERT",
            affected_rows=1,
            execution_plan={
                "table": table.name,
                "planner_type": "direct_write",
                "access_path": "INSERT",
                "used_indexes": list(table.indexes),
                "steps": [
                    {
                        "operator": "INSERT",
                        "table": table.name,
                        "index": None,
                        "reason": "direct storage insert",
                        "details": {},
                    }
                ],
                "runtime_steps": runtime_steps,
            },
        )

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------

    def _execute_delete(self, statement: DeleteStatement) -> QueryResult:
        statement = self._resolve_dml_names(statement)
        table = self.catalog.get_table(statement.table)
        self._snapshot_for_write(table)
        runtime_steps: List[Dict[str, Any]] = []

        scan_started = time.perf_counter()
        candidates = list(table.storage.scan())
        self._append_runtime(
            runtime_steps,
            "SEQUENTIAL_SCAN" if table.storage_kind == "sequential" else "HEAP_SCAN",
            scan_started,
            rows_out=len(candidates),
            table=table.name,
        )

        filter_started = time.perf_counter()
        matched = [
            (rid, row)
            for rid, row in candidates
            if self.matches_query(row, statement)
        ]
        filter_predicates = (
            [p for group in statement.or_groups for p in group]
            if statement.or_groups
            else list(statement.predicates)
        )
        if filter_predicates:
            self._append_runtime(
                runtime_steps,
                "FILTER",
                filter_started,
                rows_in=len(candidates),
                rows_out=len(matched),
                predicates=[
                    self._predicate_dict(p) for p in filter_predicates
                ],
                disjunction=bool(statement.or_groups),
            )

        delete_started = time.perf_counter()
        deleted = 0

        if table.storage_kind == "sequential":
            # Delete by stable PK instead of RID: a reorganization can move
            # remaining records while the DELETE is still running.
            primary_key = table.schema.primary_key
            for _, row in matched:
                if table.storage.delete(row[primary_key]):
                    deleted += 1
            if table.indexes:
                self.catalog.rebuild_indexes(table.name)
        else:
            for rid, row in matched:
                if table.storage.delete(rid):
                    deleted += 1
                    self._index_delete(table, row, rid)

        self._append_runtime(
            runtime_steps,
            "DELETE",
            delete_started,
            rows_in=len(matched),
            rows_out=deleted,
            table=table.name,
        )
        self._register_transaction_statement()

        return QueryResult.ok(
            "DELETE",
            affected_rows=deleted,
            execution_plan={
                "table": table.name,
                "planner_type": "direct_write",
                "access_path": (
                    "SEQUENTIAL_SCAN"
                    if table.storage_kind == "sequential"
                    else "HEAP_SCAN"
                ),
                "used_indexes": [],
                "steps": [],
                "runtime_steps": runtime_steps,
            },
        )

    # ------------------------------------------------------------------
    # UPDATE
    # ------------------------------------------------------------------

    def _execute_update(self, statement: UpdateStatement) -> QueryResult:
        statement = self._resolve_dml_names(statement)
        table = self.catalog.get_table(statement.table)
        self._snapshot_for_write(table)
        runtime_steps: List[Dict[str, Any]] = []
        known = set(table.schema.col_names())

        for column, _value in statement.assignments:
            if column not in known:
                raise QueryExecutionError(
                    f"unknown column '{column}' in UPDATE of '{table.name}'"
                )

        filter_predicates = (
            [p for group in statement.or_groups for p in group]
            if statement.or_groups
            else list(statement.predicates)
        )
        for predicate in filter_predicates:
            if predicate.column not in known:
                raise QueryExecutionError(
                    f"unknown column '{predicate.column}' in WHERE"
                )

        scan_started = time.perf_counter()
        candidates = list(table.storage.scan())
        self._append_runtime(
            runtime_steps,
            (
                "SEQUENTIAL_SCAN"
                if table.storage_kind == "sequential"
                else "HEAP_SCAN"
            ),
            scan_started,
            rows_out=len(candidates),
            table=table.name,
        )

        filter_started = time.perf_counter()
        matched = [
            (rid, row)
            for rid, row in candidates
            if self.matches_query(row, statement)
        ]
        if filter_predicates:
            self._append_runtime(
                runtime_steps,
                "FILTER",
                filter_started,
                rows_in=len(candidates),
                rows_out=len(matched),
                predicates=[
                    self._predicate_dict(p) for p in filter_predicates
                ],
                disjunction=bool(statement.or_groups),
            )

        update_started = time.perf_counter()
        assignments = dict(statement.assignments)
        updated = 0

        if table.storage_kind == "sequential":
            primary_key = table.schema.primary_key
            for _rid, row in matched:
                new_row = {**row, **assignments}
                if table.storage.delete(row[primary_key]):
                    table.storage.insert(new_row)
                    updated += 1
            if table.indexes and updated:
                self.catalog.rebuild_indexes(table.name)
        else:
            for rid, row in matched:
                new_row = {**row, **assignments}
                if table.storage.update(rid, new_row):
                    updated += 1
            if table.indexes and updated:
                # Reconstruir es lo más simple y correcto cuando la
                # actualización toca columnas indexadas (incluida la PK).
                self.catalog.rebuild_indexes(table.name)

        self._append_runtime(
            runtime_steps,
            "UPDATE",
            update_started,
            rows_in=len(matched),
            rows_out=updated,
            table=table.name,
        )
        self._register_transaction_statement()

        return QueryResult.ok(
            "UPDATE",
            affected_rows=updated,
            execution_plan={
                "table": table.name,
                "planner_type": "direct_write",
                "access_path": (
                    "SEQUENTIAL_SCAN"
                    if table.storage_kind == "sequential"
                    else "HEAP_SCAN"
                ),
                "used_indexes": list(table.indexes),
                "steps": [
                    {
                        "operator": "UPDATE",
                        "table": table.name,
                        "index": None,
                        "reason": (
                            "actualización in situ (Heap File) o "
                            "borrado + inserción (Archivo Secuencial)"
                        ),
                        "details": {
                            "assignments": [
                                {"column": column, "value": value}
                                for column, value in statement.assignments
                            ]
                        },
                    }
                ],
                "runtime_steps": runtime_steps,
            },
        )

    # ------------------------------------------------------------------
    # CREATE TABLE / DROP TABLE
    # ------------------------------------------------------------------

    def _execute_create_table(
        self,
        statement: CreateTableStatement,
    ) -> QueryResult:
        table = self.catalog.create_table(
            statement.table,
            statement.columns,
            statement.primary_key,
            storage_kind=statement.storage_kind,
            if_not_exists=statement.if_not_exists,
        )

        txn = self._transaction
        if txn is not None and txn.active:
            # La tabla no existía antes: revertir el CREATE es eliminarla.
            txn.snapshots.setdefault(
                table.name,
                {
                    "definition": {
                        "name": table.name,
                        "columns": [
                            tuple(col) for col in table.schema.to_dict()["columnas"]
                        ],
                        "primary_key": table.schema.primary_key,
                        "storage_kind": table.storage_kind,
                        "indexes": [
                            {
                                "name": registered.metadata.name,
                                "column": registered.metadata.column,
                                "kind": registered.metadata.kind,
                                "unique": registered.metadata.unique,
                            }
                            for registered in table.indexes.values()
                        ],
                    },
                    "rows": [],
                },
            )
            txn.ddl_undo.append(("create_table", {"table": table.name}))
        self._register_transaction_statement()

        return QueryResult.ok(
            "CREATE TABLE",
            columns=["table", "storage", "primary_key", "columns", "indexes"],
            rows=[
                {
                    "table": table.name,
                    "storage": table.storage_kind,
                    "primary_key": table.schema.primary_key,
                    "columns": ", ".join(
                        f"{field.name} {field.tipo}"
                        for field in table.schema.fields
                    ),
                    "indexes": ", ".join(table.indexes) or "-",
                }
            ],
            affected_rows=0,
            execution_plan={
                "table": table.name,
                "planner_type": "ddl",
                "access_path": "CREATE_TABLE",
                "used_indexes": list(table.indexes),
                "steps": [
                    {
                        "operator": "CREATE_TABLE",
                        "table": table.name,
                        "index": None,
                        "reason": (
                            "se crean los archivos físicos; la PRIMARY KEY "
                            "genera un índice Hash único"
                        ),
                        "details": {
                            "storage_kind": table.storage_kind,
                            "primary_key": table.schema.primary_key,
                            "columns": [
                                [field.name, field.tipo]
                                for field in table.schema.fields
                            ],
                        },
                    }
                ],
                "runtime_steps": [],
            },
        )

    def _execute_drop_table(self, statement: DropTableStatement) -> QueryResult:
        if self.catalog.has_table(statement.table):
            self._snapshot_table_for_drop(
                self.catalog.get_table(statement.table)
            )

        removed = self.catalog.drop_table(
            statement.table,
            if_exists=statement.if_exists,
        )
        self._register_transaction_statement()
        return QueryResult.ok(
            "DROP TABLE",
            columns=["table", "dropped"],
            rows=[
                {
                    "table": statement.table.strip().lower(),
                    "dropped": removed,
                }
            ],
            affected_rows=1 if removed else 0,
            execution_plan={
                "table": statement.table.strip().lower(),
                "planner_type": "ddl",
                "access_path": "DROP_TABLE",
                "used_indexes": [],
                "steps": [
                    {
                        "operator": "DROP_TABLE",
                        "table": statement.table.strip().lower(),
                        "index": None,
                        "reason": "se eliminan la tabla y sus archivos físicos",
                        "details": {"dropped": removed},
                    }
                ],
                "runtime_steps": [],
            },
        )

    # ------------------------------------------------------------------
    # BEGIN / END TRANSACTION
    # ------------------------------------------------------------------

    @property
    def transaction(self) -> Optional[TransactionState]:
        """Transacción activa (None si no hay BEGIN pendiente)."""
        return self._transaction

    def _execute_transaction(self, statement: TransactionStatement) -> QueryResult:
        action = statement.action

        if action == "begin":
            if self._transaction is not None and self._transaction.active:
                raise QueryExecutionError(
                    f"ya hay una transacción activa ({self._transaction.id}); "
                    "usa COMMIT o ROLLBACK antes de iniciar otra"
                )

            self._transaction = TransactionState(
                id=f"T{next(self._transaction_counter)}"
            )
            txn = self._transaction
            runtime_steps: List[Dict[str, Any]] = []
            started = time.perf_counter()
            self._append_runtime(
                runtime_steps, "BEGIN_TRANSACTION", started, transaction=txn.id
            )

            return QueryResult.ok(
                "BEGIN TRANSACTION",
                columns=["transaction", "estado", "sentencias", "tablas_bloqueadas"],
                rows=[
                    {
                        "transaction": txn.id,
                        "estado": "activa",
                        "sentencias": 0,
                        "tablas_bloqueadas": "-",
                    }
                ],
                affected_rows=0,
                execution_plan=self._transaction_plan(
                    "BEGIN_TRANSACTION",
                    "BEGIN_TRANSACTION",
                    txn,
                    runtime_steps,
                    [
                        "se abre la transacción; en la primera escritura se "
                        "guarda el estado previo de la tabla y se toma su bloqueo",
                        "el estado previo es lo que restaura ROLLBACK",
                    ],
                ),
            )

        txn = self._transaction
        if txn is None or not txn.active:
            raise QueryExecutionError(
                f"{action.upper()}: no hay una transacción activa "
                "(ejecuta BEGIN TRANSACTION primero)"
            )

        if action == "commit":
            return self._commit_transaction(txn)

        return self._rollback_transaction(txn)

    def _commit_transaction(self, txn: TransactionState) -> QueryResult:
        started = time.perf_counter()
        runtime_steps: List[Dict[str, Any]] = []
        self._append_runtime(
            runtime_steps, "COMMIT", started, transaction=txn.id
        )

        tables = sorted(txn.snapshots)
        rows = [
            {"tabla": name, "filas_previas": len(txn.snapshots[name]["rows"])}
            for name in tables
        ]
        self._release_transaction(txn)

        return QueryResult.ok(
            "END TRANSACTION",
            columns=["transaction", "estado", "sentencias", "tablas_modificadas"],
            rows=[
                {
                    "transaction": txn.id,
                    "estado": "confirmada (COMMIT)",
                    "sentencias": txn.statements,
                    "tablas_modificadas": ", ".join(tables) or "-",
                }
            ],
            affected_rows=len(tables),
            execution_plan=self._transaction_plan(
                "COMMIT",
                "COMMIT",
                txn,
                runtime_steps,
                [
                    "los cambios quedan confirmados y se liberan los bloqueos",
                    *(f"{name}: {len(txn.snapshots[name]['rows'])} filas "
                      f"antes de la transacción" for name in tables),
                ],
            ),
        )

    def _rollback_transaction(self, txn: TransactionState) -> QueryResult:
        started = time.perf_counter()
        runtime_steps: List[Dict[str, Any]] = []
        restored: List[str] = []

        # 1. Deshacer DDL en orden inverso.
        for operation, payload in reversed(txn.ddl_undo):
            if operation == "create_table":
                if self.catalog.has_table(payload["table"]):
                    self.catalog.drop_table(payload["table"])
            elif operation == "create_index":
                self.catalog.drop_index(
                    payload["index"], table=payload["table"], if_exists=True
                )
            elif operation == "drop_index":
                self.catalog.create_index(
                    payload["table"],
                    payload["column"],
                    kind=payload["kind"],
                    unique=payload.get("unique", False),
                    name=payload["index"],
                    if_not_exists=True,
                )

        # 2. Restaurar las tablas eliminadas dentro de la transacción.
        for name, snapshot in txn.dropped_tables.items():
            if not self.catalog.has_table(name):
                table = self.catalog.restore_table(
                    snapshot["definition"], data_dir=self.catalog.data_dir
                )
                table.storage.replace_all(snapshot["rows"])
                self.catalog.rebuild_indexes(name)
            restored.append(name)

        # 3. Restaurar el contenido previo de cada tabla modificada.
        for name, snapshot in txn.snapshots.items():
            if self.catalog.has_table(name):
                table = self.catalog.get_table(name)
                table.storage.replace_all(snapshot["rows"])
                self.catalog.rebuild_indexes(name)
                restored.append(name)

        self._append_runtime(
            runtime_steps,
            "ROLLBACK",
            started,
            transaction=txn.id,
            tablas_restauradas=restored,
        )
        self._release_transaction(txn)

        return QueryResult.ok(
            "ROLLBACK",
            columns=["transaction", "estado", "sentencias", "tablas_restauradas"],
            rows=[
                {
                    "transaction": txn.id,
                    "estado": "revertida (ROLLBACK)",
                    "sentencias": txn.statements,
                    "tablas_restauradas": ", ".join(sorted(set(restored))) or "-",
                }
            ],
            affected_rows=len(set(restored)),
            execution_plan=self._transaction_plan(
                "ROLLBACK",
                "ROLLBACK",
                txn,
                runtime_steps,
                [
                    "se restauran los registros previos y se reconstruyen los índices",
                    *(
                        f"{name}: {len(snapshot['rows'])} filas restauradas"
                        for name, snapshot in txn.snapshots.items()
                    ),
                ],
            ),
        )

    def _release_transaction(self, txn: TransactionState) -> None:
        txn.active = False
        try:
            self.lock_manager.release_all(txn.id)
        except Exception:  # la liberación nunca debe tapar el resultado
            pass
        self._transaction = None

    def _transaction_plan(
        self,
        operator: str,
        access_path: str,
        txn: TransactionState,
        runtime_steps: List[Dict[str, Any]],
        reasons: Sequence[str],
    ) -> Dict[str, Any]:
        return {
            "table": None,
            "planner_type": "transaction",
            "access_path": access_path,
            "used_indexes": [],
            "transaction": txn.id,
            "steps": [
                {
                    "operator": operator,
                    "table": None,
                    "index": None,
                    "reason": reason,
                    "details": {"transaction": txn.id},
                }
                for reason in reasons
            ],
            "runtime_steps": runtime_steps,
        }

    # ---------------------------------------------------- apoyo a escrituras

    def _snapshot_for_write(self, table: TableMetadata) -> None:
        """Guarda el estado previo de la tabla la primera vez que se escribe.

        También toma el bloqueo exclusivo de la tabla, de modo que dos
        transacciones sobre la misma tabla no puedan pisarse (2PL estricto: el
        bloqueo se mantiene hasta COMMIT o ROLLBACK).
        """
        txn = self._transaction
        if txn is None or not txn.active:
            return

        if table.name not in txn.locked_tables:
            self.lock_manager.acquire_exclusive(txn.id, table.name)
            txn.locked_tables.append(table.name)

        if table.name in txn.snapshots:
            return

        txn.snapshots[table.name] = {
            "definition": {
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
                    }
                    for registered in table.indexes.values()
                ],
            },
            "rows": [self._row(row) for _, row in table.storage.scan()],
        }

    def _register_transaction_statement(self) -> None:
        if self._transaction is not None and self._transaction.active:
            self._transaction.statements += 1

    def _snapshot_table_for_drop(self, table: TableMetadata) -> None:
        """Antes de un DROP TABLE dentro de una transacción, guarda todo."""
        txn = self._transaction
        if txn is None or not txn.active:
            return
        self._snapshot_for_write(table)
        txn.dropped_tables[table.name] = txn.snapshots[table.name]

    # ------------------------------------------------------------------
    # CREATE INDEX / DROP INDEX
    # ------------------------------------------------------------------

    _INDEX_KIND_LABEL = {
        "hash": "Hash Extendible (igualdad exacta)",
        "bplus_clustered": "B+ agrupado (rango y orden)",
        "bplus_unclustered": "B+ no agrupado (rango por RID)",
    }

    def _execute_create_index(
        self,
        statement: CreateIndexStatement,
    ) -> QueryResult:
        table = self.catalog.get_table(statement.table)
        self._snapshot_for_write(table)

        started = time.perf_counter()
        registered = self.catalog.create_index(
            statement.table,
            statement.column,
            kind=statement.kind,
            unique=statement.unique,
            name=statement.name,
            if_not_exists=statement.if_not_exists,
            lon_column=getattr(statement, "column2", None),
        )
        build_ms = self._elapsed_ms(started)

        txn = self._transaction
        if txn is not None and txn.active:
            txn.ddl_undo.append(
                ("create_index", {"index": registered.metadata.name,
                                  "table": table.name})
            )
        self._register_transaction_statement()

        runtime_steps: List[Dict[str, Any]] = []
        self._append_runtime(
            runtime_steps,
            "CREATE_INDEX",
            started,
            table=table.name,
            index=registered.metadata.name,
            rows_indexed=self._row_count(table),
        )

        return QueryResult.ok(
            "CREATE INDEX",
            columns=["indice", "tabla", "columna", "tecnica", "unico", "filas"],
            rows=[
                {
                    "indice": registered.metadata.name,
                    "tabla": table.name,
                    "columna": registered.metadata.column,
                    "tecnica": self._INDEX_KIND_LABEL.get(
                        registered.metadata.kind, registered.metadata.kind
                    ),
                    "unico": registered.metadata.unique,
                    "filas": self._row_count(table),
                }
            ],
            affected_rows=1,
            execution_plan={
                "table": table.name,
                "planner_type": "ddl",
                "access_path": "CREATE_INDEX",
                "used_indexes": [registered.metadata.name],
                "index_build_time_ms": build_ms,
                "steps": [
                    {
                        "operator": "CREATE_INDEX",
                        "table": table.name,
                        "index": registered.metadata.name,
                        "reason": (
                            "se construye el índice recorriendo la tabla "
                            "(sirve también para datos ya cargados)"
                        ),
                        "details": {
                            "column": registered.metadata.column,
                            "kind": registered.metadata.kind,
                            "unique": registered.metadata.unique,
                            "rows_indexed": self._row_count(table),
                        },
                    }
                ],
                "runtime_steps": runtime_steps,
            },
        )

    def _execute_drop_index(self, statement: DropIndexStatement) -> QueryResult:
        table_name = statement.table
        if table_name is not None:
            self._snapshot_for_write(self.catalog.get_table(table_name))
        else:
            for name in self.catalog.table_names():
                if statement.name.lower() in [
                    index.lower()
                    for index in self.catalog.index_names(name)
                ]:
                    table_name = name
                    self._snapshot_for_write(self.catalog.get_table(name))
                    break

        registered = None
        if table_name is not None:
            try:
                registered = self.catalog.get_index(table_name, statement.name)
            except CatalogError:
                registered = None

        txn = self._transaction
        if registered is not None and txn is not None and txn.active:
            txn.ddl_undo.append(
                (
                    "drop_index",
                    {
                        "table": table_name,
                        "index": registered.metadata.name,
                        "column": registered.metadata.column,
                        "kind": registered.metadata.kind,
                        "unique": registered.metadata.unique,
                    },
                )
            )

        started = time.perf_counter()
        removed = self.catalog.drop_index(
            statement.name,
            table=statement.table,
            if_exists=statement.if_exists,
        )
        self._register_transaction_statement()

        runtime_steps: List[Dict[str, Any]] = []
        self._append_runtime(
            runtime_steps,
            "DROP_INDEX",
            started,
            index=statement.name.strip().lower(),
            removed=removed,
        )

        return QueryResult.ok(
            "DROP INDEX",
            columns=["indice", "tabla", "eliminado"],
            rows=[
                {
                    "indice": statement.name.strip().lower(),
                    "tabla": table_name or "-",
                    "eliminado": removed,
                }
            ],
            affected_rows=1 if removed else 0,
            execution_plan={
                "table": table_name,
                "planner_type": "ddl",
                "access_path": "DROP_INDEX",
                "used_indexes": [],
                "steps": [
                    {
                        "operator": "DROP_INDEX",
                        "table": table_name,
                        "index": statement.name.strip().lower(),
                        "reason": (
                            "se elimina el índice del catálogo; las tablas "
                            "siguen consultándose con otro camino de acceso"
                        ),
                        "details": {"removed": removed},
                    }
                ],
                "runtime_steps": runtime_steps,
            },
        )

    @staticmethod
    def _row_count(table: TableMetadata) -> int:
        return sum(1 for _ in table.storage.scan())

    # ------------------------------------------------------------------
    # EXPLAIN / EXPLAIN ANALYZE
    # ------------------------------------------------------------------

    def _execute_explain(self, statement: ExplainStatement) -> QueryResult:
        inner = statement.statement

        if isinstance(inner, SelectStatement):
            inner = self._resolve_select_names(inner)
            query = inner.query_spec
            table = self.catalog.get_table(query.table)
            self._validate_columns_for_select(inner, table)

            # Parte 2: si la consulta es espacial y hay índice R-Tree, el plan es
            # el del R-Tree (con su estimación de candidatos), no un escaneo.
            payload = self._spatial_explain(inner, table)
            if payload is None:
                plan = self._planner().plan(query)
                payload = plan.to_dict()
            payload["runtime_steps"] = []

            if statement.analyze:
                analyze_started = time.perf_counter()
                executed = self._execute_select(inner)
                payload = executed.execution_plan or payload
                payload["analyze"] = {
                    "rows": len(executed.rows),
                    "execution_time_ms": self._elapsed_ms(analyze_started),
                }

            return QueryResult.ok(
                "EXPLAIN",
                columns=["plan"],
                rows=[{"plan": self._render_plan(payload)}],
                execution_plan=payload,
            )

        name = self._statement_name(inner)
        operator = name.replace(" ", "_")
        payload: Dict[str, Any] = {
            "table": getattr(inner, "table", None),
            "planner_type": "direct_write",
            "access_path": operator,
            "used_indexes": [],
            "steps": [
                {
                    "operator": operator,
                    "table": getattr(inner, "table", None),
                    "index": None,
                    "reason": "sentencia de escritura o DDL",
                    "details": {},
                }
            ],
            "runtime_steps": [],
        }

        if statement.analyze:
            executed = self.execute(inner)
            if not executed.success:
                raise QueryExecutionError(
                    executed.error or "EXPLAIN ANALYZE no pudo ejecutar"
                )
            payload["analyze"] = {
                "rows": len(executed.rows),
                "affected_rows": executed.affected_rows,
                "execution_time_ms": executed.execution_time_ms,
            }
            if executed.execution_plan:
                payload["runtime_steps"] = executed.execution_plan.get(
                    "runtime_steps", []
                )

        return QueryResult.ok(
            "EXPLAIN",
            columns=["plan"],
            rows=[{"plan": self._render_plan(payload)}],
            execution_plan=payload,
        )

    def _spatial_explain(
        self,
        statement: SelectStatement,
        table: TableMetadata,
    ) -> Optional[Dict[str, Any]]:
        """Plan lógico de una consulta espacial, sin ejecutarla.

        Devuelve ``None`` si la consulta no es espacial o si la tabla no tiene
        índice R-Tree (en ese caso el plan correcto es un escaneo con filtro).
        """
        query = statement.query_spec
        kind = spatial_kind(query)
        if kind is None:
            return None

        if kind == "knn":
            order_by = find_spatial_order_by(query)
            if order_by is None or order_by.distance is None:
                return None
            expression = order_by.distance
            registered = self.catalog.spatial_index_for(table.name, expression.column)
            if registered is None:
                return None
            index = registered.implementation
            operator = "RTREE_KNN"
            details = {
                "k": statement.limit,
                "metric": expression.metric,
                "point": list(expression.point),
                "column": expression.column,
                "points_indexed": len(index),
                "height": index.tree.height,
                "indexed_columns": [index.lat_column, index.lon_column],
            }
            reason = (
                "k-NN por best-first search: se ordena la cola de nodos con "
                "MINDIST (cota inferior) y sólo se calcula la distancia real "
                "con los puntos de las hojas visitadas"
            )
        else:
            predicate = find_spatial_predicate(query)
            if predicate is None or predicate.distance is None:
                return None
            expression = predicate.distance
            registered = self.catalog.spatial_index_for(table.name, expression.column)
            if registered is None:
                return None
            index = registered.implementation
            operator = "RTREE_RANGE_SCAN"
            details = {
                "radius": predicate.value,
                "metric": expression.metric,
                "point": list(expression.point),
                "column": expression.column,
                "points_indexed": len(index),
                "height": index.tree.height,
                "indexed_columns": [index.lat_column, index.lon_column],
            }
            reason = (
                "búsqueda por rango: el MBR del círculo poda el R-Tree y la "
                "distancia real se comprueba con las coordenadas exactas"
            )

        return {
            "table": table.name,
            "planner_type": "spatial_rtree",
            "access_path": operator,
            "used_indexes": [registered.metadata.name],
            "spatial": True,
            "kind": kind,
            "steps": [
                {
                    "operator": operator,
                    "table": table.name,
                    "index": registered.metadata.name,
                    "reason": reason,
                    "details": details,
                }
            ],
            "runtime_steps": [],
        }

    @staticmethod
    def _render_plan(payload: Dict[str, Any]) -> str:
        lines = [
            f"Tabla          : {payload.get('table')}",
            f"Optimizador    : {payload.get('planner_type')}",
            f"Ruta de acceso : {payload.get('access_path')}",
            "Índices usados : "
            + (", ".join(payload.get("used_indexes") or []) or "-"),
            "Plan lógico:",
        ]

        for position, step in enumerate(payload.get("steps") or [], start=1):
            line = (
                f"  {position}. {step.get('operator')} "
                f"[{step.get('table') or '-'}]"
            )
            if step.get("index"):
                line += f" usando {step['index']}"
            if step.get("reason"):
                line += f" - {step['reason']}"
            lines.append(line)

        runtime = payload.get("runtime_steps") or []
        if runtime:
            lines.append("Ejecución real:")
            for position, step in enumerate(runtime, start=1):
                lines.append(
                    f"  {position}. {step.get('operator')} "
                    f"{step.get('elapsed_ms')} ms "
                    f"in={step.get('rows_in', '-')} "
                    f"out={step.get('rows_out', '-')}"
                )

        analyze = payload.get("analyze")
        if analyze:
            lines.append(
                "Resumen: "
                + ", ".join(f"{key}={value}" for key, value in analyze.items())
            )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Physical access paths
    # ------------------------------------------------------------------

    def _execute_access_path(
        self,
        table: TableMetadata,
        plan,
    ) -> List[Dict[str, Any]]:
        step = plan.steps[0]
        operator = step.operator

        if operator in {"HEAP_SCAN", "SEQUENTIAL_SCAN"}:
            return [self._row(row) for _, row in table.storage.scan()]

        if not step.index:
            raise QueryExecutionError(
                f"access path '{operator}' requires an index"
            )

        registered = self.catalog.get_index(table.name, step.index)
        index = registered.implementation
        predicate = self._predicate_from_step(step.details.get("predicate"))

        if operator in {"HASH_INDEX_UNION", "BPLUS_INDEX_UNION"}:
            return self._execute_index_union(table, index, step)

        if operator == "HASH_INDEX_LOOKUP":
            if predicate is None:
                raise QueryExecutionError("hash lookup missing predicate")
            rids = index.search(predicate.value)
            return self._materialize_rids(table, rids)

        if operator in {
            "BPLUS_CLUSTERED_LOOKUP",
            "BPLUS_UNCLUSTERED_LOOKUP",
        }:
            if predicate is None:
                raise QueryExecutionError("B+ lookup missing predicate")
            values = index.search(predicate.value)
            if isinstance(index, ClusteredBPlusIndex):
                return [self._row(row) for row in values]
            return self._materialize_rids(table, values)

        if operator in {
            "BPLUS_CLUSTERED_RANGE_SCAN",
            "BPLUS_UNCLUSTERED_RANGE_SCAN",
        }:
            if predicate is None:
                raise QueryExecutionError("B+ range scan missing predicate")
            start, end, include_start, include_end = self._range_bounds(predicate)
            values = index.range_search(
                start=start,
                end=end,
                include_start=include_start,
                include_end=include_end,
            )
            if isinstance(index, ClusteredBPlusIndex):
                return [self._row(row) for row in values]
            return self._materialize_rids(table, values)

        if operator in {
            "BPLUS_CLUSTERED_INDEX_SCAN",
            "BPLUS_UNCLUSTERED_INDEX_SCAN",
        }:
            values = index.scan()
            if isinstance(index, ClusteredBPlusIndex):
                return [self._row(row) for row in values]
            return self._materialize_rids(table, values)

        raise QueryExecutionError(f"unsupported access path: {operator}")

    def _execute_index_union(
        self,
        table: TableMetadata,
        index,
        step,
    ) -> List[Dict[str, Any]]:
        """Une los resultados de varias búsquedas por índice (WHERE ... OR ...).

        Cada miembro del OR se busca por separado; la unión elimina duplicados
        por RID (o por contenido, en el B+ agrupado) y el FILTER posterior
        confirma los grupos.
        """
        predicates = []
        if step.details.get("predicate"):
            predicates.append(self._predicate_from_step(step.details["predicate"]))
        for raw in step.details.get("predicates_extra") or []:
            predicates.append(self._predicate_from_step(raw))

        if not predicates:
            raise QueryExecutionError("index union without predicates")

        clustered = isinstance(index, ClusteredBPlusIndex)
        rows: List[Dict[str, Any]] = []
        seen = set()

        for predicate in predicates:
            operator = predicate.normalized_operator()

            if operator in EQUALITY_OPERATORS:
                values = index.search(predicate.value)
            else:
                start, end, include_start, include_end = self._range_bounds(
                    predicate
                )
                values = index.range_search(
                    start=start,
                    end=end,
                    include_start=include_start,
                    include_end=include_end,
                )

            if clustered:
                for row in values:
                    key = tuple(sorted(self._row(row).items(), key=lambda kv: kv[0]))
                    if key not in seen:
                        seen.add(key)
                        rows.append(self._row(row))
            else:
                for rid in values:
                    token = repr(rid)
                    if token not in seen:
                        seen.add(token)
                        row = table.read_rid(rid)
                        if row is not None:
                            rows.append(self._row(row))

        return rows

    def _materialize_rids(self, table: TableMetadata, rids: Iterable[Any]):
        rows = []
        for rid in rids:
            row = table.read_rid(rid)
            if row is not None:
                rows.append(self._row(row))
        return rows

    @staticmethod
    def _row(values: Dict[str, Any]) -> "_CaseInsensitiveRow":
        """Envuelve un registro para que sus columnas no distingan mayúsculas."""
        if isinstance(values, _CaseInsensitiveRow):
            return values
        return _CaseInsensitiveRow(values)

    # ------------------------------------------------------------------
    # WHERE / predicates
    # ------------------------------------------------------------------

    @classmethod
    def matches_all(
        cls,
        row: Dict[str, Any],
        predicates: Sequence[Predicate],
    ) -> bool:
        return all(cls.evaluate_predicate(row, p) for p in predicates)

    @classmethod
    def matches_query(cls, row: Dict[str, Any], query) -> bool:
        """Evalúa el WHERE completo: AND simple o grupos unidos por OR."""
        if query.or_groups:
            return any(
                cls.matches_all(row, group) for group in query.or_groups
            )
        return cls.matches_all(row, query.predicates)

    def _matches_query(self, query, row: Dict[str, Any]) -> bool:
        return self.matches_query(row, query)

    @staticmethod
    def evaluate_predicate(row: Dict[str, Any], predicate: Predicate) -> bool:
        column = QueryExecutor._resolve_column_name(row, predicate.column)
        if column not in row:
            raise QueryExecutionError(
                f"unknown column in WHERE: {predicate.column}"
            )

        lhs = row[column]
        rhs = predicate.value
        op = predicate.normalized_operator()

        if op in {"=", "=="}:
            return lhs == rhs
        if op in {"!=", "<>"}:
            return lhs != rhs
        if op == "<":
            return lhs < rhs
        if op == "<=":
            return lhs <= rhs
        if op == ">":
            return lhs > rhs
        if op == ">=":
            return lhs >= rhs
        if op == "between":
            low, high = rhs
            return low <= lhs <= high

        raise QueryExecutionError(
            f"unsupported WHERE operator: {predicate.operator}"
        )

    # ------------------------------------------------------------------
    # GROUP BY / ORDER BY / JOIN
    # ------------------------------------------------------------------

    def _execute_order_by(self, rows, order_by, runtime_steps):
        # ExternalSort accepts one direction flag for the complete key. Stable
        # passes from last to first preserve SQL mixed-direction ordering.
        current = list(rows)
        total_started = time.perf_counter()
        aggregate_stats = []

        for item in reversed(order_by):
            if getattr(item, "is_spatial", False):
                # ORDER BY distancia(...) sin índice R-Tree: se calcula la
                # distancia real por fila y el External Sort ordena por ella.
                # (Antes se ordenaba por la columna de latitud, que NO es el
                # orden por cercanía.)
                current = self._attach_distance(current, item.distance)
                column = "_distance"
            else:
                column = self._canonical_column(current, item.column)
            current = self.external_sort.sort(
                current,
                key=lambda row, col=column: row[
                    self._resolve_column_name(row, col)
                ],
                descending=item.descending,
            )
            stats = self.external_sort.last_stats
            aggregate_stats.append(
                {
                    "column": item.column,
                    "direction": "DESC" if item.descending else "ASC",
                    "initial_runs": stats.initial_runs,
                    "merge_passes": stats.merge_passes,
                    "temporary_files": stats.temporary_files,
                }
            )

        self._append_runtime(
            runtime_steps,
            "EXTERNAL_SORT",
            total_started,
            rows_in=len(rows),
            rows_out=len(current),
            passes=aggregate_stats,
        )
        return current

    @staticmethod
    def _attach_distance(rows, expression):
        """Añade ``_distance``, ``_lat`` y ``_lon`` a cada fila (camino sin índice)."""
        rows = list(rows)
        if not rows:
            return rows
        columnas = list(rows[0].keys())
        lat_column = QueryExecutor._match_spatial_column(columnas, expression.column)
        lon_column = QueryExecutor._match_lon_column(columnas, lat_column)
        if lat_column is None or lon_column is None:
            raise QueryExecutionError(
                f"no se encontraron las columnas de latitud/longitud para "
                f"distancia({expression.column}, ...)"
            )
        medir = euclidean if expression.metric == "euclidean" else haversine
        resultado = []
        for row in rows:
            lat, lon = float(row[lat_column]), float(row[lon_column])
            row = dict(row)
            row["_lat"], row["_lon"] = lat, lon
            row["_distance"] = medir(expression.point, (lat, lon))
            resultado.append(row)
        return resultado

    def _execute_joins(self, rows, joins, runtime_steps):
        current = list(rows)

        for join in joins:
            right_table = self.catalog.get_table(join.table)
            right_rows = [self._row(row) for _, row in right_table.storage.scan()]
            started = time.perf_counter()
            rows_in = len(current) + len(right_rows)

            if join.operator.strip() in {"=", "=="}:
                current = self.external_hashing.hash_join(
                    current,
                    right_rows,
                    left_key=join.left_column,
                    right_key=join.right_column,
                    join_type=join.join_type,
                    merge=lambda left, right, name=right_table.name: self._merge_join_rows(
                        left, right, name
                    ),
                )
                stats = self.external_hashing.last_stats
                self._append_runtime(
                    runtime_steps,
                    "EXTERNAL_HASH_JOIN",
                    started,
                    rows_in=rows_in,
                    rows_out=len(current),
                    table=right_table.name,
                    partitions_created=stats.partitions_created,
                    repartition_passes=stats.repartition_passes,
                )
            else:
                current = self._nested_loop_join(current, right_rows, join)
                self._append_runtime(
                    runtime_steps,
                    "NESTED_LOOP_JOIN",
                    started,
                    rows_in=rows_in,
                    rows_out=len(current),
                    table=right_table.name,
                )

        return current

    @staticmethod
    def _nested_loop_join(left_rows, right_rows, join):
        output = []
        for left in left_rows:
            for right in right_rows:
                if left[join.left_column] == right[join.right_column]:
                    output.append(
                        QueryExecutor._merge_join_rows(
                            left, right, join.table
                        )
                    )
        return output

    @staticmethod
    def _merge_join_rows(left, right, right_table):
        if left is None:
            left = {}
        if right is None:
            return dict(left)

        merged = dict(left)
        for key, value in right.items():
            if key not in merged:
                merged[key] = value
            else:
                merged[f"{right_table}.{key}"] = value
        return merged

    # ------------------------------------------------------------------
    # Projection / aggregate parsing
    # ------------------------------------------------------------------

    def _project_rows(self, rows, columns, *, grouped=False):
        if columns == ("*",):
            if not rows:
                return [], []
            ordered_columns = list(rows[0].keys())
            return [self._row(row) for row in rows], ordered_columns

        output_columns = []
        selectors = []

        for expression in columns:
            aggregate = self._parse_aggregate_expression(expression)
            if aggregate:
                output_name, _, _ = aggregate
                output_columns.append(output_name)
                selectors.append(output_name)
            else:
                col = expression.strip()
                # Una columna calificada que existe como tal en la fila (la de
                # la tabla unida cuando el nombre se repite: employees.name) se
                # conserva calificada para no pisar a la de la izquierda.
                sample = rows[0] if rows else {}
                if "." in col and col in sample:
                    output_columns.append(col)
                    selectors.append(col)
                    continue
                # Se respeta el nombre real de la columna en el esquema
                # (SELECT ID -> columna 'id'), igual que en ORDER BY/WHERE.
                resolved = self._canonical_column(rows, col.split(".")[-1])
                if resolved in output_columns and "." in col:
                    resolved = col
                output_columns.append(resolved)
                selectors.append(resolved)

        projected = []
        for row in rows:
            out = _CaseInsensitiveRow()
            for output_name, selector in zip(output_columns, selectors):
                resolved = self._resolve_column_name(row, selector)
                if resolved not in row:
                    raise QueryExecutionError(
                        f"unknown selected column: {selector}"
                    )
                out[output_name] = row[resolved]
            projected.append(out)

        return projected, output_columns

    @staticmethod
    def _aggregate_all(rows, aggregate_specs):
        """Calcula agregados sobre TODAS las filas (sin GROUP BY).

        Devuelve una lista con una sola fila: ``SELECT COUNT(*) FROM t`` es el
        agregado de un único grupo que contiene toda la tabla.
        """
        rows = list(rows)
        output: Dict[str, Any] = {}

        for name, spec in aggregate_specs.items():
            if spec == "count":
                output[name] = len(rows)
                continue

            operation, source = spec
            values = [
                row[source]
                for row in rows
                if row.get(source) is not None
            ]

            if operation == "count":
                output[name] = len(values)
            elif not values:
                output[name] = 0 if operation == "sum" else None
            elif operation == "sum":
                output[name] = sum(values)
            elif operation == "avg":
                output[name] = sum(values) / len(values)
            elif operation == "min":
                output[name] = min(values)
            elif operation == "max":
                output[name] = max(values)
            else:
                raise QueryExecutionError(
                    f"unsupported aggregate operation: {operation}"
                )

        return [output]

    def _parse_aggregate_columns(self, columns):
        aggregates = {}
        for expression in columns:
            parsed = self._parse_aggregate_expression(expression)
            if not parsed:
                continue
            output_name, operation, source = parsed
            aggregates[output_name] = (
                "count"
                if operation == "count" and source == "*"
                else (operation, source)
            )
        return aggregates

    @staticmethod
    def _parse_aggregate_expression(expression):
        match = _AGGREGATE_RE.match(expression)
        if not match:
            return None
        operation, source, alias = match.groups()
        operation = operation.lower()
        output_name = alias or (
            f"{operation}_{'all' if source == '*' else source}"
        )
        return output_name, operation, source

    # ------------------------------------------------------------------
    # Index maintenance
    # ------------------------------------------------------------------

    @staticmethod
    def _index_insert(table: TableMetadata, row: Dict[str, Any], rid: Any):
        inserted: List[RegisteredIndex] = []
        try:
            for registered in table.indexes.values():
                meta = registered.metadata
                index = registered.implementation
                if meta.kind == "bplus_clustered":
                    index.insert(row)
                elif meta.kind == "bplus_unclustered":
                    index.insert(row, rid)
                elif meta.kind == "hash":
                    index.insert(row[meta.column], rid)
                elif meta.kind == "rtree":
                    # Parte 2: el R-Tree también se mantiene en cada INSERT
                    # (antes se omitía y la fila nueva no aparecía en las
                    # búsquedas espaciales hasta reiniciar).
                    index.insert(row, rid)
                inserted.append(registered)
        except Exception:
            for registered in reversed(inserted):
                meta = registered.metadata
                index = registered.implementation
                try:
                    if meta.kind == "bplus_clustered":
                        index.delete(row[meta.column], row)
                    elif meta.kind == "bplus_unclustered":
                        index.delete_record(row, rid)
                    elif meta.kind == "hash":
                        index.delete(row[meta.column], rid)
                    elif meta.kind == "rtree":
                        index.delete(rid)
                except Exception:
                    pass
            raise

    @staticmethod
    def _index_delete(table: TableMetadata, row: Dict[str, Any], rid: Any):
        for registered in table.indexes.values():
            meta = registered.metadata
            index = registered.implementation
            if meta.kind == "bplus_clustered":
                index.delete(row[meta.column], row)
            elif meta.kind == "bplus_unclustered":
                index.delete_record(row, rid)
            elif meta.kind == "hash":
                index.delete(row[meta.column], rid)
            elif meta.kind == "rtree":
                index.delete(rid)

    # ------------------------------------------------------------------
    # Validation / helpers
    # ------------------------------------------------------------------

    def _planner(self) -> QueryPlanner:
        return QueryPlanner(
            indexes=self.catalog.planner_indexes(),
            storage_by_table=self.catalog.planner_storage(),
        )

    def _validate_columns_for_select(
        self,
        statement: SelectStatement,
        table: TableMetadata,
    ):
        known = set(table.schema.col_names())
        query = statement.query_spec

        for predicate in query.predicates:
            if predicate.column not in known:
                raise QueryExecutionError(
                    f"unknown column '{predicate.column}' in table '{table.name}'"
                )
        for group in query.or_groups:
            for predicate in group:
                if predicate.column not in known:
                    raise QueryExecutionError(
                        f"unknown column '{predicate.column}' in table '{table.name}'"
                    )
        for order in query.order_by:
            # aggregate aliases are valid after GROUP BY and are checked later
            if order.column not in known and not query.group_by:
                raise QueryExecutionError(
                    f"unknown ORDER BY column '{order.column}'"
                )
        for group_col in query.group_by:
            if group_col not in known:
                raise QueryExecutionError(
                    f"unknown GROUP BY column '{group_col}'"
                )

        # Con JOIN, las columnas de las tablas unidas también son válidas en la
        # proyección (``SELECT users.name, employees.salary ... JOIN ...``).
        columnas_por_tabla = {table.name.lower(): known}
        for join in query.joins:
            if self.catalog.has_table(join.table):
                joined = self.catalog.get_table(join.table)
                columnas_por_tabla[joined.name.lower()] = set(
                    joined.schema.col_names()
                )
        todas = set().union(*columnas_por_tabla.values())

        for expression in statement.columns:
            if expression == "*" or self._parse_aggregate_expression(expression):
                continue
            if "." in expression:
                calificador, plain = (x.strip() for x in expression.rsplit(".", 1))
                columnas = columnas_por_tabla.get(calificador.lower())
                if columnas is None or plain not in columnas:
                    raise QueryExecutionError(
                        f"unknown selected column '{expression}'"
                    )
                continue
            if expression.strip() not in todas:
                raise QueryExecutionError(
                    f"unknown selected column '{expression}'"
                )

    @staticmethod
    def _range_bounds(predicate: Predicate):
        op = predicate.normalized_operator()
        if op == "between":
            low, high = predicate.value
            return low, high, True, True
        if op == ">":
            return predicate.value, None, False, True
        if op == ">=":
            return predicate.value, None, True, True
        if op == "<":
            return None, predicate.value, True, False
        if op == "<=":
            return None, predicate.value, True, True
        raise QueryExecutionError(
            f"operator does not define a range: {predicate.operator}"
        )

    @staticmethod
    def _expand_bounded_range(predicate: Predicate) -> List[Predicate]:
        """Convierte un BETWEEN combinado por el planner en dos predicados.

        El planner fusiona ``>= 19 AND <= 23`` en un solo BETWEEN para pedir un
        único ``range_search``. El filtro final debe seguir evaluando los
        predicados originales, así que aquí se reconstruyen.
        """
        if predicate.normalized_operator() != "between":
            return [predicate]
        low, high = predicate.value
        return [
            Predicate(predicate.column, ">=", low),
            Predicate(predicate.column, "<=", high),
        ]

    @staticmethod
    def _predicate_from_step(data):
        if not data:
            return None
        return Predicate(
            data["column"],
            data["operator"],
            data["value"],
        )

    @staticmethod
    def _predicate_dict(predicate):
        datos = {
            "column": predicate.column,
            "operator": predicate.operator,
            "value": predicate.value,
        }
        distance = getattr(predicate, "distance", None)
        if distance is not None:
            datos["distance"] = {
                "column": distance.column,
                "point": list(distance.point),
                "metric": distance.metric,
            }
        return datos

    @staticmethod
    def _canonical_column(rows, requested: str) -> str:
        """Devuelve el nombre real de la columna, sin distinguir mayúsculas."""
        for row in rows:
            if requested in row:
                for clave in row:
                    if str(clave).lower() == requested.lower():
                        return clave
        return requested

    @staticmethod
    def _canonical_column_in(table: TableMetadata, requested: str) -> Optional[str]:
        """Nombre real de la columna en el esquema, o None si no existe.

        SQL no distingue mayúsculas en identificadores: ``NOTA``, ``nota`` y
        ``NoTa`` son la misma columna.
        """
        for name in table.schema.col_names():
            if name.lower() == str(requested).strip().lower():
                return name
        return None

    @staticmethod
    def _filter_predicates_for(query) -> List[Predicate]:
        """Predicados que la traza del FILTER debe reportar."""
        if query.or_groups:
            return [p for group in query.or_groups for p in group]
        return list(query.predicates)

    @staticmethod
    def _resolve_column_name(row: Dict[str, Any], requested: str) -> str:
        if requested in row:
            return requested
        plain = requested.split(".")[-1]
        if plain in row:
            return plain
        return requested

    @staticmethod
    def _statement_name(statement) -> str:
        if isinstance(statement, SelectStatement):
            return "SELECT"
        if isinstance(statement, InsertStatement):
            return "INSERT"
        if isinstance(statement, DeleteStatement):
            return "DELETE"
        if isinstance(statement, UpdateStatement):
            return "UPDATE"
        if isinstance(statement, CreateTableStatement):
            return "CREATE TABLE"
        if isinstance(statement, CreateIndexStatement):
            return "CREATE INDEX"
        if isinstance(statement, DropTableStatement):
            return "DROP TABLE"
        if isinstance(statement, DropIndexStatement):
            return "DROP INDEX"
        if isinstance(statement, TransactionStatement):
            return {
                "begin": "BEGIN TRANSACTION",
                "commit": "END TRANSACTION",
                "rollback": "ROLLBACK",
            }.get(statement.action, "TRANSACTION")
        if isinstance(statement, ExplainStatement):
            return "EXPLAIN"
        if isinstance(statement, SetVariableStatement):
            return "SET"
        return type(statement).__name__.upper()

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return round((time.perf_counter() - started) * 1000.0, 6)

    @staticmethod
    def _append_runtime(runtime_steps, operator, started, **details):
        runtime_steps.append(
            {
                "operator": operator,
                "elapsed_ms": QueryExecutor._elapsed_ms(started),
                **details,
            }
        )
