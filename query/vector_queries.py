"""Ejecución de búsquedas vectoriales ``SIMILAR_TO`` (Parte 4).

Issues #87 y #88 (selección de índice y de métrica), #90 (integración con el
Query Executor) y #107 (extracción de características). El objetivo de la
consulta puede ser:

* un vector literal ``[0.1, 0.2, ...]``;
* un archivo multimedia ``'foto.jpg'`` / ``'audio.wav'``, que se convierte a
  vector con :class:`vector.extract_features.ExtractFeatures`;
* el nombre de una columna de la tabla, que no define una consulta y se
  rechaza con un mensaje claro.

Los vectores de la tabla se guardan en una columna ``VARCHAR`` con formato JSON
(``[0.1, 0.2]``) o separado por comas (``0.1,0.2``).
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from vector.extract_features import (
    ExtractFeatures,
    FeatureExtractionError,
    default_media_root,
    default_model_root,
    looks_like_media,
)
from vector.hnsw import HNSWIndex
from vector.ivf import IVFIndex
from vector.metrics import get_search_metric


class VectorQueryError(Exception):
    pass


@dataclass(frozen=True)
class QueryVector:
    """Vector de consulta y su procedencia, para el plan y las pruebas."""

    values: Tuple[float, ...]
    source: str = "literal"  # literal | file
    media_kind: Optional[str] = None
    media_path: Optional[str] = None
    extract_ms: float = 0.0
    feature_mode: Optional[str] = None
    n_words: Optional[int] = None
    descriptor_backend: Optional[str] = None


_VECTOR_COLUMN_NAMES = ("embedding", "vector", "vectors", "features", "descriptor", "histogram")
_DEFAULT_METRIC = "euclidean"


def parse_vector(value: Any) -> Tuple[float, ...]:
    """Convierte una lista, JSON (``[0.1, 0.2]``) o texto ``0.1,0.2`` en un vector de ``float``."""
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
    """Ejecuta ``SIMILAR_TO`` reutilizando los índices IVF y HNSW persistentes cuando corresponde.

    ``media_root`` es el directorio donde buscar ``'foto.jpg'`` cuando la ruta
    no es absoluta. El Query Executor lo deriva del ``data_dir`` del catálogo
    (``<data_dir>/media``), que es donde ``backend.media`` guarda las subidas
    del panel multimedia.
    """

    def __init__(self, catalog, *, media_root=None, model_root=None):
        self.catalog = catalog
        self.media_root = Path(media_root) if media_root is not None else default_media_root(catalog)
        self.model_root = Path(model_root) if model_root is not None else default_model_root(catalog)

    def execute(self, table, spec, *, limit: Optional[int] = None, row_filter=None):
        predicate = spec.predicate
        column = self._resolve_column(table, predicate.column)
        target = self._resolve_target(table, predicate, column)
        stored = self._stored_index(table, spec, column)
        if stored is not None:
            return self._execute_stored(table, stored, column, target, predicate.k, limit, row_filter)
        rows, vectors = self._load_vectors(table, column, row_filter)
        if not vectors:
            if row_filter is not None:
                raise VectorQueryError("ninguna fila cumple el resto del WHERE")
            raise VectorQueryError(f"la columna '{column}' de '{table.name}' no tiene vectores válidos")
        dimension = len(vectors[0][1])
        if len(target.values) != dimension:
            raise VectorQueryError(
                f"el vector de consulta tiene dimensión {len(target.values)} y la columna "
                f"'{column}' dimensión {dimension}"
            )
        kind = (spec.index_kind or "hnsw").lower()
        metric = (spec.metric or _DEFAULT_METRIC).lower()
        k = max(1, min(predicate.k, len(vectors)))
        if limit is not None:
            k = max(1, min(k, int(limit)))

        started = time.perf_counter()
        if kind == "hnsw":
            index, reused, index_path = self._load_or_build_hnsw(
                table.name, column, metric, vectors
            )
        else:
            index = self._build(kind, metric, vectors)
            reused = False
            index_path = None
        build_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        try:
            results = index.search_similar(target.values, k=k)
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
        return out, self._plan(
            table, column, kind, metric, k, dimension, len(vectors),
            build_ms, search_ms, len(out), target, reused=reused, index_path=index_path,
        )

    def plan(self, table, spec, row_filter=None):
        """Plan que usaría la consulta, sin construir el índice ni buscar."""
        predicate = spec.predicate
        column = self._resolve_column(table, predicate.column)
        target = self._resolve_target(table, predicate, column)
        stored = self._stored_index(table, spec, column)
        if stored is not None:
            index = stored.implementation
            self._check_dimension(target.values, index.dimension, column)
            k = max(1, min(predicate.k, len(index)))
            return self._plan(table, column, "ivf", index.metric_name, k, index.dimension, len(index), 0.0, 0.0, 0,
                              target, stored=stored)
        _, vectors = self._load_vectors(table, column, row_filter)
        if not vectors:
            if row_filter is not None:
                raise VectorQueryError("ninguna fila cumple el resto del WHERE")
            raise VectorQueryError(f"la columna '{column}' de '{table.name}' no tiene vectores válidos")
        dimension = len(vectors[0][1])
        if len(target.values) != dimension:
            raise VectorQueryError(
                f"el vector de consulta tiene dimensión {len(target.values)} y la columna "
                f"'{column}' dimensión {dimension}"
            )
        kind = (spec.index_kind or "hnsw").lower()
        metric = (spec.metric or _DEFAULT_METRIC).lower()
        if kind not in {"hnsw", "ivf"}:
            raise VectorQueryError(f"índice no soportado en SIMILAR_TO: {kind}; usa HNSW o IVF")
        k = max(1, min(predicate.k, len(vectors)))
        return self._plan(
            table, column, kind, metric, k, dimension, len(vectors), 0.0, 0.0, 0, target
        )

    def _stored_index(self, table, spec, column):
        """IVF creado con CREATE INDEX sobre la columna y con la misma métrica, si existe."""
        if (spec.index_kind or "").lower() != "ivf" or not hasattr(self.catalog, "vector_index_for"):
            return None
        metric = (spec.metric or _DEFAULT_METRIC).lower()
        stored = self.catalog.vector_index_for(table.name, column, metric)
        return stored if stored is not None and stored.implementation.is_trained else None

    @staticmethod
    def _check_dimension(target, dimension, column):
        if len(target) != dimension:
            raise VectorQueryError(
                f"el vector de consulta tiene dimensión {len(target)} y la columna "
                f"'{column}' dimensión {dimension}"
            )

    def _execute_stored(self, table, stored, column, target, k, limit, row_filter):
        index = stored.implementation
        self._check_dimension(target.values, index.dimension, column)
        n = len(index)
        k = max(1, min(k, n))
        if limit is not None:
            k = max(1, min(k, int(limit)))
        started = time.perf_counter()
        # Con más filtros en el WHERE se amplía la búsqueda hasta reunir k filas que los cumplan.
        wanted = k if row_filter is None else min(n, 4 * k)
        while True:
            try:
                results = index.search_similar(target.values, k=wanted)
            except ValueError as exc:
                raise VectorQueryError(str(exc)) from None
            out: List[Dict[str, Any]] = []
            for result in results:
                row = dict(table.read_rid(result.vector_id))
                if row_filter is not None and not row_filter(row):
                    continue
                row["_score"] = result.score
                row["_raw_metric"] = result.raw_metric
                row["_metric"] = result.metric
                out.append(row)
                if len(out) == k:
                    break
            if len(out) == k or wanted >= n:
                break
            wanted = min(n, 4 * wanted)
        search_ms = (time.perf_counter() - started) * 1000
        if row_filter is not None and not out:
            raise VectorQueryError("ninguna fila cumple el resto del WHERE")
        return out, self._plan(table, column, "ivf", index.metric_name, k, index.dimension, n, 0.0, search_ms,
                               len(out), target, stored=stored)

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

    def _resolve_target(self, table, predicate, column: str) -> QueryVector:
        target = predicate.target
        if isinstance(target, (list, tuple)):
            return QueryVector(parse_vector(target))

        if isinstance(target, str):
            if target in table.schema.col_names():
                raise VectorQueryError(
                    f"SIMILAR_TO({target}, ...) no define un vector de consulta; "
                    f"pasa un archivo ('foto.jpg') o un vector literal [0.1, 0.2, ...]"
                )
            if looks_like_media(target, media_root=self.media_root):
                started = time.perf_counter()
                try:
                    features = ExtractFeatures.extract(
                        target,
                        media_root=self.media_root,
                        model_root=self.model_root,
                    )
                except FeatureExtractionError as exc:
                    raise VectorQueryError(str(exc)) from None
                extract_ms = (time.perf_counter() - started) * 1000
                return QueryVector(
                    values=features.values,
                    source="file",
                    media_kind=features.kind,
                    media_path=features.source,
                    extract_ms=extract_ms,
                    feature_mode=features.mode,
                    n_words=features.n_words,
                    descriptor_backend=features.backend,
                )
            raise VectorQueryError(
                f"objetivo inválido en SIMILAR_TO: {target!r}; usa un archivo "
                f"(por ejemplo 'foto.jpg') o un vector literal [0.1, 0.2, ...]"
            )

        raise VectorQueryError(f"objetivo inválido en SIMILAR_TO: {target!r}")

    @staticmethod
    def _load_vectors(table, column: str, row_filter=None):
        rows: List[Dict[str, Any]] = []
        vectors: List[Tuple[int, Tuple[float, ...]]] = []
        for _, raw in table.storage.scan():
            row = dict(raw)
            if row_filter is not None and not row_filter(row):
                continue
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

    def _hnsw_path(self, table_name: str, column: str, metric: str) -> Optional[Path]:
        data_dir = getattr(self.catalog, "data_dir", None)
        if data_dir is None:
            return None
        directory = Path(data_dir) / "indexes"
        directory.mkdir(parents=True, exist_ok=True)
        safe = lambda value: "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in value.lower())
        return directory / f"{safe(table_name)}__{safe(column)}__hnsw__{safe(metric)}.idx"

    @staticmethod
    def _vectors_signature(vectors) -> str:
        """Firma del contenido para detectar un índice persistido obsoleto."""
        digest = hashlib.sha256()
        for vector_id, vector in vectors:
            digest.update(repr(vector_id).encode("utf-8"))
            digest.update(b"|")
            digest.update(repr(tuple(float(v) for v in vector)).encode("utf-8"))
            digest.update(b"\n")
        return digest.hexdigest()

    def _load_or_build_hnsw(self, table_name: str, column: str, metric: str, vectors):
        signature = self._vectors_signature(vectors)
        path = self._hnsw_path(table_name, column, metric)

        if path is not None and path.exists():
            try:
                index = HNSWIndex.load(path)
                if (
                    index.metric_name == metric
                    and index.source_signature == signature
                    and len(index) == len(vectors)
                    and (not vectors or index.dimension == len(vectors[0][1]))
                ):
                    return index, True, str(path)
            except (OSError, ValueError, KeyError, TypeError):
                # Snapshot corrupto/incompatible: se reconstruye una vez y se reemplaza.
                pass

        index = HNSWIndex(
            metric=get_search_metric(metric),
            metric_name=metric,
            random_seed=0,
            ef_search=50,
        )
        for vector_id, vector in vectors:
            index.insert(vector_id, vector)
        index.source_signature = signature
        if path is not None:
            index.save(path)
        return index, False, str(path) if path is not None else None

    @staticmethod
    def _build(kind: str, metric: str, vectors):
        n = len(vectors)
        if kind == "ivf":
            n_lists = max(1, min(n, max(1, int(math.sqrt(n)))))
            index = IVFIndex(n_lists=n_lists, metric_name=metric, random_seed=0)
            index.build(vectors)
            return index
        if kind == "hnsw":
            # La ruta normal usa _load_or_build_hnsw(). Se conserva este caso
            # para compatibilidad con tests/helpers que invoquen _build directamente.
            index = HNSWIndex(
                metric=get_search_metric(metric),
                metric_name=metric,
                random_seed=0,
                ef_search=50,
            )
            for vector_id, vector in vectors:
                index.insert(vector_id, vector)
            return index
        raise VectorQueryError(f"índice no soportado en SIMILAR_TO: {kind}; usa HNSW o IVF")

    @staticmethod
    def _plan(table, column, kind, metric, k, dimension, n_vectors, build_ms, search_ms, rows_out,
              target=None, stored=None, *, reused=False, index_path=None):
        operator = "HNSW_KNN" if kind == "hnsw" else "IVF_KNN"
        details = {"k": k, "metric": metric, "dimension": dimension, "vectors": n_vectors,
                   "build_ms": round(build_ms, 3)}
        index_name = column
        reason = f"{kind.upper()} con métrica {metric} sobre '{column}'"
        if kind == "hnsw":
            details.update({"persistent": bool(index_path), "reused": bool(reused), "index_path": index_path})
        if stored is not None:
            index_name = stored.metadata.name
            reason = f"índice IVF persistido '{index_name}' (métrica {metric}) sobre '{column}'"
            details.update({"persistent": True, "n_lists": stored.implementation.n_lists,
                            "n_probe": stored.implementation.n_probe})
        if target is not None:
            details["query_source"] = target.source
            if target.source == "file":
                details["media_kind"] = target.media_kind
                details["media_file"] = Path(target.media_path).name if target.media_path else None
                details["extract_ms"] = round(target.extract_ms, 3)
                details["feature_mode"] = target.feature_mode
                details["n_words"] = target.n_words
                details["sift_backend"] = target.descriptor_backend
        return {
            "table": table.name,
            "planner_type": "vector_index",
            "access_path": operator,
            "used_indexes": [index_name],
            "steps": [
                {
                    "operator": operator,
                    "table": table.name,
                    "index": index_name,
                    "reason": reason,
                    "details": details,
                }
            ],
            "runtime_steps": [
                {"operator": operator, "elapsed_ms": round(search_ms, 3), "rows_out": rows_out, "index": index_name}
            ],
        }
