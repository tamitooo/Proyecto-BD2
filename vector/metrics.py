"""Métricas de similitud compartidas por HNSW e IVF (Parte 4)."""

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
    _validate_pair(first, second)
    return _finite(math.dist(first, second))


def dot_product(first: Sequence[float], second: Sequence[float]) -> float:
    _validate_pair(first, second)
    return _finite(sum(float(a) * float(b) for a, b in zip(first, second)))


def cosine_similarity(first: Sequence[float], second: Sequence[float]) -> float:
    _validate_pair(first, second)
    first_norm = _finite(math.hypot(*first))
    second_norm = _finite(math.hypot(*second))
    if first_norm == 0.0 or second_norm == 0.0:
        return 0.0
    # Normalizar antes de multiplicar evita overflow con vectores extremos.
    cosine = sum(
        (float(a) / first_norm) * (float(b) / second_norm)
        for a, b in zip(first, second)
    )
    return max(-1.0, min(1.0, _finite(cosine)))


def cosine_distance(first: Sequence[float], second: Sequence[float]) -> float:
    return 1.0 - cosine_similarity(first, second)


def negative_dot_product(first: Sequence[float], second: Sequence[float]) -> float:
    return -dot_product(first, second)


_SEARCH_METRICS = {
    "euclidean": euclidean_distance,
    "cosine": cosine_distance,
    "dot_product": negative_dot_product,
}


def get_search_metric(metric: str) -> SearchMetric:
    """Devuelve la función de costo (menor = mejor) de una métrica."""
    return _SEARCH_METRICS[SimilarityRanking(metric).metric]
