from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union


EQUALITY_OPERATORS = {"=", "=="}
RANGE_OPERATORS = {"<", "<=", ">", ">=", "between"}
SUPPORTED_PREDICATE_OPERATORS = EQUALITY_OPERATORS | RANGE_OPERATORS | {"!=", "<>"}


@dataclass(frozen=True)
class Predicate:
    column: str
    operator: str
    value: Any

    def normalized_operator(self) -> str:
        return self.operator.strip().lower()


@dataclass(frozen=True)
class OrderBy:
    column: str
    descending: bool = False


@dataclass(frozen=True)
class JoinSpec:
    table: str
    left_column: str
    right_column: str
    join_type: str = "inner"
    operator: str = "="


@dataclass(frozen=True)
class QuerySpec:
    table: str
    predicates: Tuple[Predicate, ...] = ()
    order_by: Tuple[OrderBy, ...] = ()
    group_by: Tuple[str, ...] = ()
    joins: Tuple[JoinSpec, ...] = ()


@dataclass(frozen=True)
class IndexMetadata:
    name: str
    table: str
    column: str
    kind: str
    unique: bool = False

    def __post_init__(self):
        allowed = {"hash", "bplus_clustered", "bplus_unclustered"}
        if self.kind not in allowed:
            raise ValueError(f"unsupported index kind: {self.kind}")


@dataclass
class PlanStep:
    operator: str
    table: Optional[str] = None
    index: Optional[str] = None
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return {
            "operator": self.operator,
            "table": self.table,
            "index": self.index,
            "reason": self.reason,
            "details": dict(self.details),
        }


@dataclass
class QueryPlan:
    table: str
    steps: List[PlanStep]
    access_path: str
    used_indexes: List[str] = field(default_factory=list)
    planner_type: str = "rule_based"

    def to_dict(self):
        return {
            "table": self.table,
            "planner_type": self.planner_type,
            "access_path": self.access_path,
            "used_indexes": list(self.used_indexes),
            "steps": [step.to_dict() for step in self.steps],
        }

    def explain(self) -> str:
        lines = [
            f"Planner: {self.planner_type}",
            f"Table: {self.table}",
            f"Access path: {self.access_path}",
        ]
        for position, step in enumerate(self.steps, start=1):
            line = f"{position}. {step.operator}"
            if step.table:
                line += f" [{step.table}]"
            if step.index:
                line += f" using {step.index}"
            if step.reason:
                line += f" - {step.reason}"
            if step.details:
                rendered = ", ".join(
                    f"{key}={value!r}" for key, value in step.details.items()
                )
                line += f" ({rendered})"
            lines.append(line)
        return "\n".join(lines)


@dataclass(frozen=True)
class _AccessCandidate:
    index: IndexMetadata
    predicate: Optional[Predicate]
    score: int
    operator: str
    preserves_order: bool
    reason: str


class QueryPlanner:
    """
    Reglas:
      - Igualdad: Hash > B+ clustered > B+ unclustered.
      - Rango: B+ clustered > B+ unclustered.
      - ORDER BY: B+ puede evitar External Sort.
      - GROUP BY: External Hashing.
      - Equi-JOIN: External Hash Join.
      - Sin indice util: Heap/Sequential Scan.
    """

    def __init__(
        self,
        indexes: Optional[Iterable[IndexMetadata]] = None,
        storage_by_table: Optional[Mapping[str, str]] = None,
    ):
        self.indexes = list(indexes or [])
        self.storage_by_table = dict(storage_by_table or {})

    def register_index(self, index: IndexMetadata):
        self.indexes.append(index)

    def register_storage(self, table: str, storage_kind: str):
        kind = storage_kind.strip().lower()
        if kind not in {"heap", "sequential"}:
            raise ValueError("storage_kind must be 'heap' or 'sequential'")
        self.storage_by_table[table] = kind

    def plan(self, query: Union[QuerySpec, Mapping[str, Any]]) -> QueryPlan:
        query = self._coerce_query(query)
        self._validate_query(query)

        steps = []
        used_indexes = []
        candidate = self._choose_access_candidate(query)

        if candidate is None:
            access_step = self._fallback_scan(query.table)
            access_path = access_step.operator
            preserves_order = False
            consumed_predicate = None
        else:
            access_step = PlanStep(
                operator=candidate.operator,
                table=query.table,
                index=candidate.index.name,
                reason=candidate.reason,
                details=self._access_details(candidate),
            )
            access_path = candidate.operator
            preserves_order = candidate.preserves_order
            consumed_predicate = candidate.predicate
            used_indexes.append(candidate.index.name)

        steps.append(access_step)

        residual = self._residual_predicates(
            query.predicates,
            consumed_predicate,
        )
        if residual:
            steps.append(
                PlanStep(
                    operator="FILTER",
                    table=query.table,
                    reason="predicados no resueltos por el camino de acceso",
                    details={
                        "predicates": [
                            self._predicate_to_dict(p) for p in residual
                        ]
                    },
                )
            )

        for join in query.joins:
            if join.operator.strip().lower() in EQUALITY_OPERATORS:
                steps.append(
                    PlanStep(
                        operator="EXTERNAL_HASH_JOIN",
                        table=join.table,
                        reason="equi-join: Grace Hash Join",
                        details={
                            "join_type": join.join_type.lower(),
                            "left_column": join.left_column,
                            "right_column": join.right_column,
                            "operator": join.operator,
                        },
                    )
                )
            else:
                steps.append(
                    PlanStep(
                        operator="NESTED_LOOP_JOIN",
                        table=join.table,
                        reason="hash join solo aplica a igualdad",
                        details={
                            "join_type": join.join_type.lower(),
                            "left_column": join.left_column,
                            "right_column": join.right_column,
                            "operator": join.operator,
                        },
                    )
                )
            preserves_order = False

        if query.group_by:
            steps.append(
                PlanStep(
                    operator="EXTERNAL_HASH_GROUP_BY",
                    table=query.table,
                    reason="GROUP BY con particionado hash externo",
                    details={"columns": list(query.group_by)},
                )
            )
            preserves_order = False

        if query.order_by and not self._order_is_covered(
            query, candidate, preserves_order
        ):
            steps.append(
                PlanStep(
                    operator="EXTERNAL_SORT",
                    table=query.table,
                    reason="el camino de acceso no garantiza el ORDER BY",
                    details={
                        "columns": [
                            {
                                "column": item.column,
                                "direction": "DESC" if item.descending else "ASC",
                            }
                            for item in query.order_by
                        ]
                    },
                )
            )

        return QueryPlan(
            table=query.table,
            steps=steps,
            access_path=access_path,
            used_indexes=used_indexes,
        )

    def _choose_access_candidate(self, query):
        table_indexes = [i for i in self.indexes if i.table == query.table]
        candidates = []

        for predicate in query.predicates:
            op = predicate.normalized_operator()
            for index in table_indexes:
                if index.column != predicate.column:
                    continue
                candidate = self._candidate_for_predicate(
                    query, index, predicate, op
                )
                if candidate:
                    candidates.append(candidate)

        if query.order_by:
            first_order = query.order_by[0]

            # Los B+ actuales exponen recorrido ascendente; DESC requiere
            # External Sort mientras no exista reverse scan en el indice.
            if first_order.descending:
                first_order = None

            for index in table_indexes:
                if first_order is None or index.column != first_order.column:
                    continue
                if index.kind == "bplus_clustered":
                    candidates.append(
                        _AccessCandidate(
                            index, None, 70,
                            "BPLUS_CLUSTERED_INDEX_SCAN",
                            True,
                            "B+ clustered evita sort inicial",
                        )
                    )
                elif index.kind == "bplus_unclustered":
                    candidates.append(
                        _AccessCandidate(
                            index, None, 60,
                            "BPLUS_UNCLUSTERED_INDEX_SCAN",
                            True,
                            "B+ unclustered entrega RIDs ordenados",
                        )
                    )

        if not candidates:
            return None

        kind_priority = {
            "hash": 3,
            "bplus_clustered": 2,
            "bplus_unclustered": 1,
        }
        return max(
            candidates,
            key=lambda c: (c.score, kind_priority[c.index.kind]),
        )

    def _candidate_for_predicate(self, query, index, predicate, operator):
        bonus = self._order_bonus(query, index)

        if operator in EQUALITY_OPERATORS:
            if index.kind == "hash":
                return _AccessCandidate(
                    index, predicate, 110,
                    "HASH_INDEX_LOOKUP", False,
                    "Extendible Hashing es preferido para igualdad exacta",
                )
            if index.kind == "bplus_clustered":
                return _AccessCandidate(
                    index, predicate, 90 + bonus,
                    "BPLUS_CLUSTERED_LOOKUP", True,
                    "B+ clustered soporta lookup directo",
                )
            if index.kind == "bplus_unclustered":
                return _AccessCandidate(
                    index, predicate, 80 + bonus,
                    "BPLUS_UNCLUSTERED_LOOKUP", True,
                    "B+ unclustered soporta lookup mediante RIDs",
                )

        if operator in RANGE_OPERATORS:
            if index.kind == "bplus_clustered":
                return _AccessCandidate(
                    index, predicate, 95 + bonus,
                    "BPLUS_CLUSTERED_RANGE_SCAN", True,
                    "B+ clustered soporta range scan ordenado",
                )
            if index.kind == "bplus_unclustered":
                return _AccessCandidate(
                    index, predicate, 85 + bonus,
                    "BPLUS_UNCLUSTERED_RANGE_SCAN", True,
                    "B+ unclustered soporta range scan",
                )

        return None

    @staticmethod
    def _order_bonus(query, index):
        if (
            query.order_by
            and not query.order_by[0].descending
            and query.order_by[0].column == index.column
            and index.kind.startswith("bplus")
        ):
            return 15
        return 0

    @staticmethod
    def _order_is_covered(query, candidate, preserves_order):
        if not query.order_by:
            return True

        if candidate is None:
            return False

        if len(query.order_by) != 1:
            return False

        order_item = query.order_by[0]

        # Si el camino de acceso consume una igualdad sobre la misma
        # columna del ORDER BY, todas las filas devueltas tienen el mismo
        # valor para esa columna. No es necesario ordenar, incluso si el
        # acceso es mediante Hash.
        if (
            candidate.predicate is not None
            and candidate.predicate.normalized_operator() in EQUALITY_OPERATORS
            and candidate.predicate.column == order_item.column
        ):
            return True

        if not preserves_order:
            return False

        return (
            not order_item.descending
            and candidate.index.kind.startswith("bplus")
            and candidate.index.column == order_item.column
        )

    def _fallback_scan(self, table):
        storage_kind = self.storage_by_table.get(table, "heap").lower()
        if storage_kind == "sequential":
            return PlanStep(
                operator="SEQUENTIAL_SCAN",
                table=table,
                reason="no existe indice aplicable",
            )
        return PlanStep(
            operator="HEAP_SCAN",
            table=table,
            reason="no existe indice aplicable",
        )

    @staticmethod
    def _residual_predicates(predicates, consumed_predicate):
        if consumed_predicate is None:
            return list(predicates)

        removed = False
        residual = []
        for predicate in predicates:
            if not removed and predicate == consumed_predicate:
                removed = True
            else:
                residual.append(predicate)
        return residual

    @staticmethod
    def _access_details(candidate):
        details = {
            "index_kind": candidate.index.kind,
            "column": candidate.index.column,
            "unique": candidate.index.unique,
        }
        if candidate.predicate is not None:
            details["predicate"] = QueryPlanner._predicate_to_dict(
                candidate.predicate
            )
        return details

    @staticmethod
    def _predicate_to_dict(predicate):
        return {
            "column": predicate.column,
            "operator": predicate.operator,
            "value": predicate.value,
        }

    @staticmethod
    def _validate_query(query):
        if not query.table:
            raise ValueError("query.table is required")

        for predicate in query.predicates:
            op = predicate.normalized_operator()
            if op not in SUPPORTED_PREDICATE_OPERATORS:
                raise ValueError(
                    f"unsupported predicate operator: {predicate.operator}"
                )
            if (
                op == "between"
                and not (
                    isinstance(predicate.value, (tuple, list))
                    and len(predicate.value) == 2
                )
            ):
                raise ValueError(
                    "BETWEEN predicate requires a (low, high) value"
                )

        for join in query.joins:
            if join.join_type.strip().lower() not in {
                "inner", "left", "right", "full"
            }:
                raise ValueError(
                    f"unsupported join type: {join.join_type}"
                )

    @classmethod
    def _coerce_query(cls, query):
        if isinstance(query, QuerySpec):
            return query
        if not isinstance(query, Mapping):
            raise TypeError("query must be QuerySpec or mapping")

        predicates = tuple(
            cls._coerce_predicate(item)
            for item in query.get("predicates", ())
        )
        order_by = tuple(
            cls._coerce_order_by(item)
            for item in query.get("order_by", ())
        )
        joins = tuple(
            cls._coerce_join(item)
            for item in query.get("joins", ())
        )

        group_by_value = query.get("group_by", ())
        group_by = (
            (group_by_value,)
            if isinstance(group_by_value, str)
            else tuple(group_by_value)
        )

        return QuerySpec(
            table=query.get("table", ""),
            predicates=predicates,
            order_by=order_by,
            group_by=group_by,
            joins=joins,
        )

    @staticmethod
    def _coerce_predicate(item):
        if isinstance(item, Predicate):
            return item
        if isinstance(item, Mapping):
            return Predicate(
                item["column"],
                item["operator"],
                item.get("value"),
            )
        if isinstance(item, (tuple, list)) and len(item) == 3:
            return Predicate(item[0], item[1], item[2])
        raise TypeError(
            "predicate must be Predicate, mapping, or "
            "(column, operator, value)"
        )

    @staticmethod
    def _coerce_order_by(item):
        if isinstance(item, OrderBy):
            return item
        if isinstance(item, str):
            return OrderBy(item)
        if isinstance(item, Mapping):
            return OrderBy(
                item["column"],
                bool(item.get("descending", False)),
            )
        if isinstance(item, (tuple, list)):
            if len(item) == 1:
                return OrderBy(item[0])
            if len(item) == 2:
                direction = item[1]
                descending = (
                    direction.strip().lower() == "desc"
                    if isinstance(direction, str)
                    else bool(direction)
                )
                return OrderBy(item[0], descending)
        raise TypeError("invalid order_by item")

    @staticmethod
    def _coerce_join(item):
        if isinstance(item, JoinSpec):
            return item
        if isinstance(item, Mapping):
            return JoinSpec(
                table=item["table"],
                left_column=item["left_column"],
                right_column=item["right_column"],
                join_type=item.get("join_type", "inner"),
                operator=item.get("operator", "="),
            )
        raise TypeError("join must be JoinSpec or mapping")
