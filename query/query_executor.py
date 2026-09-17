import re
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from indexes.clustered_bplus import ClusteredBPlusIndex
from indexes.extendible_hash import ExtendibleHash
from indexes.unclustered_bplus import UnclusteredBPlusIndex
from operators.external_hashing import ExternalHashing
from operators.external_sort import ExternalSort
from query.catalog import Catalog, CatalogError, RegisteredIndex, TableMetadata
from query.query_planner import Predicate, QueryPlanner
from query.query_result import QueryResult
from query.sql_parser import (
    DeleteStatement,
    InsertStatement,
    SQLParser,
    SelectStatement,
)


class QueryExecutionError(Exception):
    pass


_AGGREGATE_RE = re.compile(
    r"^\s*(COUNT|SUM|AVG|MIN|MAX)\s*\(\s*(\*|[A-Za-z_][A-Za-z0-9_]*)\s*\)"
    r"(?:\s+AS\s+([A-Za-z_][A-Za-z0-9_]*))?\s*$",
    re.IGNORECASE,
)


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
    ):
        self.catalog = catalog
        self.parser = parser or SQLParser()
        self.external_sort = external_sort or ExternalSort()
        self.external_hashing = external_hashing or ExternalHashing()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        sql_or_statement: Union[str, SelectStatement, InsertStatement, DeleteStatement],
        *,
        raise_on_error: bool = False,
    ) -> QueryResult:
        started = time.perf_counter()
        statement_name = "UNKNOWN"

        try:
            statement = (
                self.parser.parse(sql_or_statement)
                if isinstance(sql_or_statement, str)
                else sql_or_statement
            )
            statement_name = self._statement_name(statement)

            if isinstance(statement, SelectStatement):
                result = self._execute_select(statement)
            elif isinstance(statement, InsertStatement):
                result = self._execute_insert(statement)
            elif isinstance(statement, DeleteStatement):
                result = self._execute_delete(statement)
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

    # ------------------------------------------------------------------
    # SELECT
    # ------------------------------------------------------------------

    def _execute_select(self, statement: SelectStatement) -> QueryResult:
        query = statement.query_spec
        table = self.catalog.get_table(query.table)
        self._validate_columns_for_select(statement, table)

        planner = self._planner()
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
        if query.predicates:
            filter_started = time.perf_counter()
            rows_in = len(rows)
            rows = [
                row for row in rows
                if self.matches_all(row, query.predicates)
            ]
            self._append_runtime(
                runtime_steps,
                "FILTER",
                filter_started,
                rows_in=rows_in,
                rows_out=len(rows),
                predicates=[self._predicate_dict(p) for p in query.predicates],
            )

        if query.joins:
            rows = self._execute_joins(rows, query.joins, runtime_steps)

        aggregate_specs = self._parse_aggregate_columns(statement.columns)
        if query.group_by:
            group_started = time.perf_counter()
            rows_in = len(rows)
            rows = self.external_hashing.group_by(
                rows,
                key=query.group_by[0]
                if len(query.group_by) == 1
                else tuple(query.group_by),
                aggregates=aggregate_specs,
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
        elif aggregate_specs:
            raise QueryExecutionError(
                "aggregate functions currently require GROUP BY"
            )

        if query.order_by and any(
            step.operator == "EXTERNAL_SORT" for step in plan.steps
        ):
            rows = self._execute_order_by(rows, query.order_by, runtime_steps)

        projected_rows, columns = self._project_rows(
            rows,
            statement.columns,
            grouped=bool(query.group_by),
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

        row = dict(zip(columns, statement.values))
        runtime_steps: List[Dict[str, Any]] = []
        started = time.perf_counter()
        rid = table.storage.insert(row)

        try:
            # SequentialFile may reorganize immediately and invalidate the RID
            # returned by insert(). Resolve the canonical RID again by PK.
            if table.storage_kind == "sequential":
                pk_value = row[table.schema.primary_key]
                rid, stored = table.storage.search(pk_value)
                if rid is None or stored is None:
                    raise QueryExecutionError(
                        "insert succeeded but record could not be resolved after reorganization"
                    )
                self.catalog.rebuild_indexes(table.name)
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
        table = self.catalog.get_table(statement.table)
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
            if self.matches_all(row, statement.predicates)
        ]
        if statement.predicates:
            self._append_runtime(
                runtime_steps,
                "FILTER",
                filter_started,
                rows_in=len(candidates),
                rows_out=len(matched),
                predicates=[self._predicate_dict(p) for p in statement.predicates],
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
            return [dict(row) for _, row in table.storage.scan()]

        if not step.index:
            raise QueryExecutionError(
                f"access path '{operator}' requires an index"
            )

        registered = self.catalog.get_index(table.name, step.index)
        index = registered.implementation
        predicate = self._predicate_from_step(step.details.get("predicate"))

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
                return [dict(row) for row in values]
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
                return [dict(row) for row in values]
            return self._materialize_rids(table, values)

        if operator in {
            "BPLUS_CLUSTERED_INDEX_SCAN",
            "BPLUS_UNCLUSTERED_INDEX_SCAN",
        }:
            values = index.scan()
            if isinstance(index, ClusteredBPlusIndex):
                return [dict(row) for row in values]
            return self._materialize_rids(table, values)

        raise QueryExecutionError(f"unsupported access path: {operator}")

    def _materialize_rids(self, table: TableMetadata, rids: Iterable[Any]):
        rows = []
        for rid in rids:
            row = table.read_rid(rid)
            if row is not None:
                rows.append(dict(row))
        return rows

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
            current = self.external_sort.sort(
                current,
                key=lambda row, col=item.column: row[
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

    def _execute_joins(self, rows, joins, runtime_steps):
        current = list(rows)

        for join in joins:
            right_table = self.catalog.get_table(join.table)
            right_rows = [dict(row) for _, row in right_table.storage.scan()]
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
            return [dict(row) for row in rows], ordered_columns

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
                output_columns.append(col)
                selectors.append(col)

        projected = []
        for row in rows:
            out = {}
            for output_name, selector in zip(output_columns, selectors):
                resolved = self._resolve_column_name(row, selector)
                if resolved not in row:
                    raise QueryExecutionError(
                        f"unknown selected column: {selector}"
                    )
                out[output_name] = row[resolved]
            projected.append(out)

        return projected, output_columns

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

        for expression in statement.columns:
            if expression == "*" or self._parse_aggregate_expression(expression):
                continue
            plain = expression.split(".")[-1].strip()
            if plain not in known:
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
        return {
            "column": predicate.column,
            "operator": predicate.operator,
            "value": predicate.value,
        }

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
