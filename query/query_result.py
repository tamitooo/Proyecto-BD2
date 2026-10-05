from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union


@dataclass
class QueryResult:
    """Stable response object returned by the SQL/backend integration layer.

    Rows are dictionaries so the result can be serialized directly by a future
    REST/GraphQL layer and rendered by the frontend without knowing anything
    about HeapFile, indexes, or physical RIDs.
    """

    success: bool
    statement: str
    columns: List[str] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    affected_rows: int = 0
    execution_time_ms: float = 0.0
    execution_plan: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    @classmethod
    def ok(
        cls,
        statement: str,
        *,
        columns: Sequence[str] = (),
        rows: Sequence[Dict[str, Any]] = (),
        affected_rows: int = 0,
        execution_time_ms: float = 0.0,
        execution_plan: Optional[Dict[str, Any]] = None,
    ) -> "QueryResult":
        return cls(
            success=True,
            statement=statement,
            columns=list(columns),
            rows=[dict(row) for row in rows],
            affected_rows=affected_rows,
            execution_time_ms=execution_time_ms,
            execution_plan=execution_plan,
        )

    @classmethod
    def fail(
        cls,
        statement: str,
        error: Union[Exception, str],
        *,
        execution_time_ms: float = 0.0,
    ) -> "QueryResult":
        return cls(
            success=False,
            statement=statement,
            execution_time_ms=execution_time_ms,
            error=str(error),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "statement": self.statement,
            "columns": list(self.columns),
            "rows": [dict(row) for row in self.rows],
            "affected_rows": self.affected_rows,
            "execution_time_ms": self.execution_time_ms,
            "execution_plan": self.execution_plan,
            "error": self.error,
        }
