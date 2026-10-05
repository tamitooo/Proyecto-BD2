"""Ejecución de consultas espaciales sobre el R-Tree (Parte 2).

Se mantiene aparte de ``query/query_executor.py`` para que el ejecutor SQL no
crezca con la lógica espacial: el ejecutor detecta que la consulta es espacial,
resuelve el índice y **delega aquí**.

Los tres planes que produce el planner para datos espaciales:

* ``RTREE_RANGE_SCAN`` — ``distancia(col, POINT(...)) < radio``
* ``RTREE_KNN`` — ``ORDER BY distancia(col, POINT(...)) LIMIT k``
* ``RTREE_POLYGON`` — ``dentro_de(col, POLYGON((lat lon, ...)))``

En los tres casos el R-Tree aporta **candidatos** (poda por MBR) y la
comprobación exacta se hace sobre las coordenadas reales: el resultado es
exacto, no aproximado.
"""

import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from query.query_planner import DistanceExpression, OrderBy, Predicate, QuerySpec
from spatial.geo import haversine, point_in_polygon, polygon_to_mbr
from spatial.index import SpatialIndex


class SpatialQueryError(Exception):
    """Consulta espacial mal formada o sin índice utilizable."""


def find_spatial_predicate(query: QuerySpec):
    """Primer predicado espacial del WHERE, si lo hay.

    Devuelve tanto un predicado de ``distancia(...)`` (``Predicate`` con campo
    ``distance``) como uno de ``dentro_de(...)`` (``PolygonPredicate``).
    """
    for predicate in query.predicates:
        if getattr(predicate, "is_spatial", False):
            return predicate
    for group in query.or_groups:
        for predicate in group:
            if getattr(predicate, "is_spatial", False):
                return predicate
    return None


def find_distance_predicate(query: QuerySpec) -> Optional[Predicate]:
    """Sólo el predicado de rango por distancia (no el de polígono)."""
    for predicate in query.predicates:
        if getattr(predicate, "distance", None) is not None:
            return predicate
    return None


def find_polygon_predicate(query: QuerySpec):
    """Sólo el predicado de intersección con polígono."""
    for predicate in query.predicates:
        if predicate.__class__.__name__ == "PolygonPredicate":
            return predicate
    return None


def find_spatial_order_by(query: QuerySpec) -> Optional[OrderBy]:
    """ORDER BY espacial (k-NN), si lo hay."""
    for item in query.order_by:
        if getattr(item, "is_spatial", False):
            return item
    return None


def spatial_kind(query: QuerySpec) -> Optional[str]:
    """Clasifica la consulta: ``range``, ``knn``, ``polygon`` o ``None``."""
    if find_spatial_order_by(query) is not None:
        return "knn"
    if find_polygon_predicate(query) is not None:
        return "polygon"
    if find_distance_predicate(query) is not None:
        return "range"
    return None


class SpatialExecutor:
    """Ejecuta las consultas espaciales contra un ``SpatialIndex``."""

    def __init__(self, catalog):
        self.catalog = catalog

    # ------------------------------------------------------------------ rango

    def execute_range(
        self,
        table,
        predicate: Predicate,
        *,
        limit: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """``distancia(col, POINT(...)) < radio`` sobre el R-Tree."""
        expression = predicate.distance
        if expression is None:
            raise SpatialQueryError("el predicado no es espacial")

        registered = self._index_for(table, expression)
        index: SpatialIndex = registered.implementation
        radius = float(predicate.value)

        started = time.perf_counter()
        matches = index.range_search(expression.point, radius)
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        rows = self._materialize(table, index, matches, expression.point)
        if limit is not None:
            rows = rows[:limit]

        trace = self._trace(
            "RTREE_RANGE_SCAN",
            table,
            registered.metadata.name,
            elapsed_ms,
            rows_in=len(index),
            rows_out=len(rows),
            radius=radius,
            metric=expression.metric,
            point=list(expression.point),
            candidates=len(matches),
        )
        return rows, trace

    # -------------------------------------------------------------------- k-NN

    def execute_knn(
        self,
        table,
        order_by: OrderBy,
        k: int,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """``ORDER BY distancia(...) LIMIT k`` = los k vecinos más cercanos."""
        expression = order_by.distance
        if expression is None:
            raise SpatialQueryError("el ORDER BY no es espacial")
        if order_by.descending:
            raise SpatialQueryError(
                "ORDER BY distancia(...) DESC no tiene sentido para k-NN; "
                "usa ASC o quita DESC"
            )
        if k <= 0:
            raise SpatialQueryError("k-NN necesita LIMIT k con k >= 1")

        registered = self._index_for(table, expression)
        index: SpatialIndex = registered.implementation

        started = time.perf_counter()
        matches = index.knn(expression.point, k)
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        rows = self._materialize(table, index, matches, expression.point)

        trace = self._trace(
            "RTREE_KNN",
            table,
            registered.metadata.name,
            elapsed_ms,
            rows_in=len(index),
            rows_out=len(rows),
            k=k,
            metric=expression.metric,
            point=list(expression.point),
            candidates=len(matches),
            note=(
                "best-first search con MINDIST: la distancia real sólo se "
                "calculó con los puntos de las hojas visitadas"
            ),
        )
        return rows, trace

    # --------------------------------------------------------------- polígono

    def execute_polygon(
        self,
        table,
        expression,
        ring: Sequence[Tuple[float, float]],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """``dentro_de(col, POLYGON(...))``: intersección con un polígono."""
        registered = self._index_for(table, expression)
        index: SpatialIndex = registered.implementation

        started = time.perf_counter()
        matches = index.polygon_search(ring)
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        rows = []
        for rid, (lat, lon) in matches:
            row = self._row(table, rid)
            if row is None:
                continue
            row = dict(row)
            row["_lat"] = lat
            row["_lon"] = lon
            row["_distance"] = None
            rows.append(row)

        trace = self._trace(
            "RTREE_POLYGON",
            table,
            registered.metadata.name,
            elapsed_ms,
            rows_in=len(index),
            rows_out=len(rows),
            vertices=len(ring),
            polygon_mbr=list(polygon_to_mbr(ring)),
        )
        return rows, trace

    # ------------------------------------------------------------------ apoyo

    def _index_for(self, table, expression: DistanceExpression):
        """Busca el índice espacial que cubre la columna de la expresión."""
        registered = self.catalog.spatial_index_for(
            table.name, expression.column
        )
        if registered is None:
            raise SpatialQueryError(
                f"la columna espacial '{expression.column}' de "
                f"'{table.name}' no tiene índice R-Tree; créalo con "
                f"CREATE INDEX ... ON {table.name} (lat, lon) USING RTREE"
            )
        return registered

    @staticmethod
    def _row(table, rid):
        """Lee la fila de un RID, con el mismo criterio que el ejecutor.

        ``HeapFile`` lee por RID y ``SequentialFile`` por ``read_rid``: hay que
        mirar el tipo de almacenamiento, no la existencia del método (ambos lo
        tienen).
        """
        if getattr(table, "storage_kind", "heap") == "heap":
            return table.storage.read(rid)
        return table.storage.read_rid(rid)

    def _materialize(
        self,
        table,
        index: SpatialIndex,
        matches: Sequence[Tuple[Any, float]],
        origin: Tuple[float, float],
    ) -> List[Dict[str, Any]]:
        """Convierte ``(rid, distancia)`` en filas con la distancia añadida."""
        rows: List[Dict[str, Any]] = []
        for rid, distance in matches:
            row = self._row(table, rid)
            if row is None:
                continue
            row = dict(row)
            lat, lon = index.coordinates(rid)
            row["_lat"] = lat
            row["_lon"] = lon
            row["_distance"] = distance
            rows.append(row)
        return rows

    @staticmethod
    def _trace(
        operator: str,
        table,
        index_name: str,
        elapsed_ms: float,
        **details: Any,
    ) -> Dict[str, Any]:
        """Plan en el mismo formato que el resto del motor."""
        return {
            "table": table.name,
            "planner_type": "spatial_rtree",
            "access_path": operator,
            "used_indexes": [index_name],
            "steps": [
                {
                    "operator": operator,
                    "table": table.name,
                    "index": index_name,
                    "reason": details.pop("note", None)
                    or (
                        "búsqueda espacial con poda por MBR: el R-Tree aporta "
                        "candidatos y la distancia real se comprueba con las "
                        "coordenadas exactas"
                    ),
                    "details": {k: v for k, v in details.items()},
                }
            ],
            "runtime_steps": [
                {
                    "operator": operator,
                    "elapsed_ms": round(elapsed_ms, 6),
                    "rows_out": details.get("rows_out"),
                    "index": index_name,
                }
            ],
        }
