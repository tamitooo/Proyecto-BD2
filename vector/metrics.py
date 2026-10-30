"""Métricas de similitud compartidas por HNSW e IVF (issues #110, #111 y #112).

Cada métrica se expone con su valor natural:

* ``euclidean_distance``: distancia (menor es mejor).
* ``dot_product``: producto punto (mayor es mejor).
* ``cosine_similarity``: similitud (mayor es mejor).

Los índices minimizan un costo, así que ``get_search_metric`` devuelve la
función con la convención de :mod:`vector.ranking`:

* euclidean: ``search_distance = euclidean_distance``
* cosine: ``search_distance = 1 - cosine_similarity``
* dot_product: ``search_distance = -dot_product``
"""

from __future__ import annotations

import math
from typing import Callable, Sequence

from .ranking import SimilarityRanking

SearchMetric = Callable[[Sequence[float], Sequence[float]], float]


def _validate_pair(first: Sequence[float], second: Sequence[float]) -> None:
    # len() en lugar de truthiness: un ndarray no tiene valor de verdad.
    if len(first) == 0 or len(second) == 0:
        raise ValueError("los vectores no pueden estar vacíos")
    if len(first) != len(second):
        raise ValueError("los vectores deben tener la misma dimensión")


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("la métrica debe devolver un valor finito")
    return value


def euclidean_distance(first: Sequence[float], second: Sequence[float]) -> float:
    """Distancia Euclidiana (issue #110)."""
    _validate_pair(first, second)
    return _finite(math.dist(first, second))


def dot_product(first: Sequence[float], second: Sequence[float]) -> float:
    """Producto punto (issue #111)."""
    _validate_pair(first, second)
    return _finite(sum(float(a) * float(b) for a, b in zip(first, second)))


def cosine_similarity(first: Sequence[float], second: Sequence[float]) -> float:
    """Similitud del coseno en ``[-1, 1]`` (issue #112).

    El coseno de un vector nulo no está definido. Se devuelve ``0.0`` (sin
    similitud) porque un histograma o documento vacío es un dato válido y no
    debe abortar una búsqueda completa.
    """
    _validate_pair(first, second)
    first_norm = _finite(math.hypot(*first))
    second_norm = _finite(math.hypot(*second))
    if first_norm == 0.0 or second_norm == 0.0:
        return 0.0
    # Normalizar antes de multiplicar evita overflow/underflow con vectores
    # de magnitud extrema: el coseno no depende de la escala.
    cosine = sum(
        (float(a) / first_norm) * (float(b) / second_norm)
        for a, b in zip(first, second)
    )
    # El redondeo puede dejar el resultado apenas fuera de [-1, 1].
    return max(-1.0, min(1.0, _finite(cosine)))


def cosine_distance(first: Sequence[float], second: Sequence[float]) -> float:
    """Costo de búsqueda para coseno: ``1 - cosine_similarity``."""
    return 1.0 - cosine_similarity(first, second)


def negative_dot_product(first: Sequence[float], second: Sequence[float]) -> float:
    """Costo de búsqueda para producto punto: ``-dot_product``."""
    return -dot_product(first, second)


_SEARCH_METRICS = {
    "euclidean": euclidean_distance,
    "cosine": cosine_distance,
    "dot_product": negative_dot_product,
}


def get_search_metric(metric: str) -> SearchMetric:
    """Devuelve la función de costo (menor = mejor) de una métrica.

    Acepta los mismos nombres y alias que :class:`SimilarityRanking`, por lo
    que el resultado se puede inyectar en ``HNSWIndex(metric=...)`` junto con
    ``metric_name`` sin perder la conversión a ``score``.
    """
    return _SEARCH_METRICS[SimilarityRanking(metric).metric]
