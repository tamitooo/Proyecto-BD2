"""Ejecución de búsquedas vectoriales ``SIMILAR_TO`` (Parte 4).

Issues #87 y #88 (selección de índice y de métrica) y #90 (integración con el
Query Executor). Mientras la extracción de características (#107) no exista, el
vector de consulta se pasa como literal ``[0.1, 0.2, ...]`` y los vectores de la
tabla se guardan en una columna ``VARCHAR`` con formato JSON (``[0.1, 0.2]``) o
separado por comas (``0.1,0.2``).
"""

from __future__ import annotations

import json
import math
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from vector.hnsw import HNSWIndex
from vector.ivf import IVFIndex
from vector.metrics import get_search_metric


class VectorQueryError(Exception):
    pass


_VECTOR_COLUMN_NAMES = ("embedding", "vector", "vectors", "features", "descriptor", "histogram")
_DEFAULT_METRIC = "euclidean"


def parse_vector(value: Any) -> Tuple[float, ...]:
    """Convierte una celda o un literal en un vector de ``float``.

    Acepta listas/tuplas, JSON (``[0.1, 0.2]``) o texto separado por comas
    (``0.1,0.2``). Lanza :class:`VectorQueryError` con un mensaje claro.
    """
    if isinstance(value, (list, tuple)):
        raw: Sequence[Any] = list(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise VectorQueryError("el vector está vacío")
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            decoded = [part for part in (p.strip() for p in text.strip("[]").split(",")) if part]
        if isinstance(decoded, (int, float)) or not isinstance(decoded, list):
            raise VectorQueryError(f"vector inválido: {value!r}; usa [0.1, 0.2, ...]")
        raw = decoded
    else:
        raise VectorQueryError(f"vector inválido: {value!r}; usa [0.1, 0.2, ...]")
    try:
        vector = tuple(float(item) for item in raw)
    except (TypeError, ValueError):
        raise VectorQueryError(f"vector inválido: {value!r}; usa [0.1, 0.2, ...]") from None
    if not vector:
        raise VectorQueryError("el vector está vacío")
    return vector


class VectorExecutor:
    """Ejecuta ``SIMILAR_TO`` construyendo el índice elegido sobre la tabla."""

    def __init__(self, catalog):
        self.catalog = catalog

    def execute(self, table, spec, *, limit: Optional[int] = None):
        predicate = spec.predicate
        column = self._resolve_column(table, predicate.column)
        target = self._resolve_target(table, predicate, column)
        rows, vectors = self._load_vectors(table, column)
        if not vectors:
            raise VectorQueryError(f"la columna '{column}' de '{table.name}' no tiene vectores válidos")
        dimension = len(vectors[0][1])
        if len(target) != dimension:
            raise VectorQueryError(
                f"el vector de consulta tiene dimensión {len(target)} y la columna "
                f"'{column}' dimensión {dimension}"
            )
        kind = (spec.index_kind or "hnsw").lower()
        metric = (spec.metric or _DEFAULT_METRIC).lower()
        k = max(1, min(predicate.k, len(vectors)))
        if limit is not None:
            k = max(1, min(k, int(limit)))

        started = time.perf_counter()
        index = self._build(kind, metric, vectors)
        build_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        try:
            results = index.search_similar(target, k=k)
        except ValueError as exc:
            raise VectorQueryError(str(exc)) from None
        search_ms = (time.perf_counter() - started) * 1000

        out: List[Dict[str, Any]] = []
        for result in results:
            row = dict(rows[result.vector_id])
            row["_score"] = result.score
            row["_raw_metric"] = result.raw_metric
            row["_metric"] = result.metric
            out.append(row)
        return out, self._plan(table, column, kind, metric, k, dimension, len(vectors), build_ms, search_ms, len(out))

    def plan(self, table, spec):
        """Plan que usaría la consulta, sin construir el índice ni buscar."""
        predicate = spec.predicate
        column = self._resolve_column(table, predicate.column)
        target = self._resolve_target(table, predicate, column)
        _, vectors = self._load_vectors(table, column)
        if not vectors:
            raise VectorQueryError(f"la columna '{column}' de '{table.name}' no tiene vectores válidos")
        dimension = len(vectors[0][1])
        if len(target) != dimension:
            raise VectorQueryError(
                f"el vector de consulta tiene dimensión {len(target)} y la columna "
                f"'{column}' dimensión {dimension}"
            )
        kind = (spec.index_kind or "hnsw").lower()
        metric = (spec.metric or _DEFAULT_METRIC).lower()
        if kind not in {"hnsw", "ivf"}:
            raise VectorQueryError(f"índice no soportado en SIMILAR_TO: {kind}; usa HNSW o IVF")
        k = max(1, min(predicate.k, len(vectors)))
        return self._plan(table, column, kind, metric, k, dimension, len(vectors), 0.0, 0.0, 0)

    # ------------------------------------------------------------- resolución
    @staticmethod
    def _resolve_column(table, requested: Optional[str]) -> str:
        names = list(table.schema.col_names())
        if requested:
            if requested not in names:
                raise VectorQueryError(f"la columna '{requested}' no existe en '{table.name}'")
            return requested
        for name in names:
            if name.lower() in _VECTOR_COLUMN_NAMES:
                return name
        candidates = [name for name in names if VectorExecutor._column_has_vectors(table, name)]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise VectorQueryError(
                f"'{table.name}' no tiene una columna de vectores; crea una VARCHAR "
                f"(por ejemplo embedding) con vectores JSON como '[0.1, 0.2]'"
            )
        raise VectorQueryError(
            f"varias columnas parecen vectores ({', '.join(candidates)}); "
            f"usa SIMILAR_TO(columna, ...)"
        )

    @staticmethod
    def _column_has_vectors(table, column: str) -> bool:
        for _, raw in table.storage.scan():
            try:
                parse_vector(dict(raw).get(column))
                return True
            except VectorQueryError:
                continue
        return False

    @staticmethod
    def _resolve_target(table, predicate, column: str) -> Tuple[float, ...]:
        target = predicate.target
        if isinstance(target, (list, tuple)):
            return parse_vector(target)
        if isinstance(target, str):
            if target in table.schema.col_names():
                raise VectorQueryError(
                    f"SIMILAR_TO({target}, ...) no define un vector de consulta; "
                    f"pasa un vector literal [0.1, 0.2, ...]"
                )
            if "." in target or "/" in target or "\\" in target:
                raise VectorQueryError(
                    "buscar por archivo ('foto.jpg') requiere ExtractFeatures (#107); "
                    "mientras tanto usa un vector literal [0.1, 0.2, ...]"
                )
            raise VectorQueryError(f"objetivo inválido en SIMILAR_TO: {target!r}")
        raise VectorQueryError(f"objetivo inválido en SIMILAR_TO: {target!r}")

    @staticmethod
    def _load_vectors(table, column: str):
        rows: List[Dict[str, Any]] = []
        vectors: List[Tuple[int, Tuple[float, ...]]] = []
        for _, raw in table.storage.scan():
            row = dict(raw)
            try:
                vector = parse_vector(row.get(column))
            except VectorQueryError:
                continue
            if vectors and len(vector) != len(vectors[0][1]):
                raise VectorQueryError(
                    f"la columna '{column}' mezcla vectores de distinta dimensión"
                )
            vectors.append((len(rows), vector))
            rows.append(row)
        return rows, vectors

    # --------------------------------------------------------------- índices
    @staticmethod
    def _build(kind: str, metric: str, vectors):
        n = len(vectors)
        if kind == "ivf":
            n_lists = max(1, min(n, max(1, int(math.sqrt(n)))))
            index = IVFIndex(n_lists=n_lists, metric_name=metric, random_seed=0)
            index.build(vectors)
            return index
        if kind == "hnsw":
            index = HNSWIndex(
                metric=get_search_metric(metric),
                metric_name=metric,
                random_seed=0,
                ef_search=max(10, n),
            )
            for vector_id, vector in vectors:
                index.insert(vector_id, vector)
            return index
        raise VectorQueryError(f"índice no soportado en SIMILAR_TO: {kind}; usa HNSW o IVF")

    @staticmethod
    def _plan(table, column, kind, metric, k, dimension, n_vectors, build_ms, search_ms, rows_out):
        operator = "HNSW_KNN" if kind == "hnsw" else "IVF_KNN"
        return {
            "table": table.name,
            "planner_type": "vector_index",
            "access_path": operator,
            "used_indexes": [column],
            "steps": [
                {
                    "operator": operator,
                    "table": table.name,
                    "index": column,
                    "reason": f"{kind.upper()} con métrica {metric} sobre '{column}'",
                    "details": {
                        "k": k,
                        "metric": metric,
                        "dimension": dimension,
                        "vectors": n_vectors,
                        "build_ms": round(build_ms, 3),
                    },
                }
            ],
            "runtime_steps": [
                {"operator": operator, "elapsed_ms": round(search_ms, 3), "rows_out": rows_out, "index": column}
            ],
        }
