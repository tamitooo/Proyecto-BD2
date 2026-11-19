"""Utilidades SQL mínimas para el recomendador.

El motor no admite parámetros vinculados, así que toda consulta se construye
con literales.  ``literal()`` escapa comillas simples por duplicación, que es
la forma que acepta ``query/sql_parser.py`` al deshacer el literal.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from query.query_result import QueryResult


class RecommenderError(RuntimeError):
    """Una consulta del recomendador falló o devolvió datos inválidos."""


def literal(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RecommenderError(f"valor no finito en SQL: {value!r}")
        return repr(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise RecommenderError(f"tipo no soportado en SQL: {type(value).__name__}")


def run(engine, sql: str, what: str) -> QueryResult:
    """Ejecuta ``sql`` y falla con contexto si el motor devuelve error."""
    try:
        result = engine.run(sql)
    except Exception as exc:  # el motor puede lanzar además de devolver fail
        raise RecommenderError(f"{what}: {exc}") from exc
    if not result.success:
        raise RecommenderError(f"{what}: {result.error} | SQL: {sql[:200]}")
    return result


def rows(engine, sql: str, what: str) -> List[Dict[str, Any]]:
    return run(engine, sql, what).rows


def one(engine, sql: str, what: str) -> Dict[str, Any] | None:
    result = rows(engine, sql, what)
    if len(result) > 1:
        raise RecommenderError(f"{what}: se esperaba una fila y llegaron {len(result)}")
    return result[0] if result else None
