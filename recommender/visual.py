"""Fuente visual del recomendador (Persona 3: issues g y h).

Dos modos, ambos devuelven ``Recommendation`` con ``score`` mayor-es-mejor y
nunca incluyen el producto de consulta:

* ``recommend_by_visual(engine, producto_id)``: toma el embedding ya guardado
  del producto X y busca sus vecinos con ``SIMILAR_TO ... USING IVF``.
* ``search_by_image(engine, imagen)``: extrae el vector de una imagen nueva con
  ``EXTRACT_FEATURES`` y busca los productos visualmente más parecidos.

El embedding de los productos se calcula una sola vez en la carga
(``tools/seed_tienda.py``) con el mismo vocabulario BoVW. El índice IVF se crea
con::

    CREATE INDEX idx_productos_embedding
    ON productos (embedding) USING IVF WITH METRIC=cosine;

``SIMILAR_TO`` reutiliza ese índice persistente; si no existe, construye uno
temporal para la consulta.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .sql import RecommenderError, literal, rows
from .types import Recommendation
from vector.extract_features import ExtractFeatures, FeatureExtractionError

DEFAULT_METRIC = "cosine"
_VALID_METRICS = {"euclidean", "cosine", "dot_product"}
SOURCE = "visual"


def product_embedding(engine, producto_id: int) -> Optional[Tuple[float, ...]]:
    """Embedding guardado de un producto, o ``None`` si no existe/no es válido."""
    try:
        identifier = int(producto_id)
    except (TypeError, ValueError):
        return None
    result = rows(
        engine,
        f"SELECT embedding FROM productos WHERE id = {literal(identifier)}",
        f"embedding del producto {identifier}",
    )
    if not result:
        return None
    raw = result[0].get("embedding")
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = [part.strip() for part in text.strip("[]").split(",") if part.strip()]
    if not isinstance(decoded, list) or not decoded:
        return None
    try:
        vector = tuple(float(value) for value in decoded)
    except (TypeError, ValueError):
        return None
    if not vector or not all(math.isfinite(value) for value in vector):
        return None
    return vector


def _vector_literal(vector: Sequence[float]) -> str:
    return "[" + ", ".join(repr(float(value)) for value in vector) + "]"


def _validate_metric(metric: str) -> str:
    normalized = (metric or DEFAULT_METRIC).lower()
    if normalized not in _VALID_METRICS:
        raise ValueError(
            f"métrica no soportada: {metric!r}; usa euclidean, cosine o dot_product"
        )
    return normalized


def _normalized_score(raw_score: float, metric: str) -> float:
    """Lleva el score del motor a un valor comparable y mayor-es-mejor.

    El coseno queda en ``[0, 1]``; la Euclidiana del motor ya devuelve
    ``1 / (1 + distancia)``. El producto punto se deja como está porque la
    fusión lo normaliza por consulta.
    """
    value = float(raw_score)
    if not math.isfinite(value):
        return 0.0
    if metric == "cosine":
        return max(0.0, min(1.0, (value + 1.0) / 2.0))
    if metric == "euclidean":
        return max(0.0, min(1.0, value))
    return value


def _similar_rows(
    engine,
    vector: Sequence[float],
    *,
    k: int,
    metric: str,
    exclude_id: Optional[int] = None,
    what: str = "búsqueda visual",
) -> List[Dict[str, Any]]:
    request_k = max(1, int(k) + (1 if exclude_id is not None else 0))
    sql = (
        "SELECT id, SIMILARITY_SCORE() AS score FROM productos "
        f"WHERE SIMILAR_TO({_vector_literal(vector)}, k={request_k}) "
        f"USING IVF WITH METRIC={metric}"
    )
    result = rows(engine, sql, what)
    out: List[Dict[str, Any]] = []
    for row in result:
        try:
            product_id = int(row["id"])
            raw_score = float(row["score"])
        except (KeyError, TypeError, ValueError):
            continue
        if exclude_id is not None and product_id == exclude_id:
            continue
        out.append({"id": product_id, "raw": raw_score})
        if len(out) >= k:
            break
    return out


def recommend_by_visual(
    engine,
    producto_id: int,
    k: int = 10,
    *,
    metric: str = DEFAULT_METRIC,
) -> List[Recommendation]:
    """Productos visualmente similares a X, sin incluir X."""
    if int(k) < 1:
        return []
    metric = _validate_metric(metric)
    try:
        identifier = int(producto_id)
    except (TypeError, ValueError):
        return []
    vector = product_embedding(engine, identifier)
    if vector is None:
        return []
    found = _similar_rows(
        engine,
        vector,
        k=int(k),
        metric=metric,
        exclude_id=identifier,
        what=f"recomendación visual del producto {identifier}",
    )
    return [
        Recommendation(
            producto_id=item["id"],
            score=_normalized_score(item["raw"], metric),
            fuente=SOURCE,
            evidencia={
                "modo": "producto",
                "producto_referencia": identifier,
                "metrica": metric,
                "score_motor": round(item["raw"], 6),
            },
        )
        for item in found
    ]


def search_by_image(
    engine,
    imagen,
    k: int = 10,
    *,
    metric: str = DEFAULT_METRIC,
    media_root=None,
    model_root=None,
) -> List[Recommendation]:
    """Productos visualmente similares a una imagen nueva.

    ``imagen`` puede ser una ruta (resuelta contra ``media_root``) o bytes. La
    imagen se convierte a vector con el vocabulario BoVW y luego se busca con
    ``SIMILAR_TO``. No hay producto X que excluir.
    """
    if int(k) < 1:
        return []
    metric = _validate_metric(metric)
    try:
        features = ExtractFeatures.extract(
            imagen,
            kind="image",
            media_root=media_root,
            model_root=model_root,
        )
    except FeatureExtractionError as exc:
        raise RecommenderError(f"no se pudo extraer la imagen de consulta: {exc}") from exc
    found = _similar_rows(
        engine,
        features.values,
        k=int(k),
        metric=metric,
        what="búsqueda de productos por imagen",
    )
    return [
        Recommendation(
            producto_id=item["id"],
            score=_normalized_score(item["raw"], metric),
            fuente=SOURCE,
            evidencia={
                "modo": "imagen",
                "archivo": features.source,
                "metrica": metric,
                "score_motor": round(item["raw"], 6),
            },
        )
        for item in found
    ]


__all__ = [
    "DEFAULT_METRIC",
    "SOURCE",
    "product_embedding",
    "recommend_by_visual",
    "search_by_image",
]
