"""Contrato común de ranking para búsquedas vectoriales (issue #116).

HNSW navega internamente con una función de costo donde **menor = mejor**.
Esta capa traduce ese costo interno a un resultado público donde ``score``
siempre cumple **mayor = más similar**, que es el contrato que consumirá
``SIMILARITY_SCORE()`` en la integración SQL.

Persona B puede compartir las métricas con IVF usando estas convenciones:

* euclidean: ``search_distance = euclidean_distance``
* cosine: ``search_distance = 1 - cosine_similarity``
* dot_product: ``search_distance = -dot_product``

Así HNSW e IVF pueden navegar/minimizar un costo sin perder el valor semántico
original que se expone en ``raw_metric``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Hashable, Iterable, Literal

MetricName = Literal["euclidean", "cosine", "dot_product"]
_SUPPORTED = {"euclidean", "cosine", "dot_product"}


@dataclass(frozen=True)
class SearchResult:
    """Resultado público de una búsqueda vectorial.

    ``score`` siempre usa la convención **mayor = mejor**.
    ``raw_metric`` conserva el valor natural de la métrica:

    * Euclidiana: distancia (menor es mejor).
    * Coseno: similitud (mayor es mejor).
    * Producto punto: producto punto (mayor es mejor).
    """

    vector_id: Hashable
    score: float
    raw_metric: float
    metric: str


class SimilarityRanking:
    """Convierte distancias internas de búsqueda a resultados comparables."""

    def __init__(self, metric: str = "euclidean") -> None:
        normalized = str(metric).strip().lower().replace("-", "_")
        aliases = {
            "euclidean_distance": "euclidean",
            "l2": "euclidean",
            "cos": "cosine",
            "cosine_similarity": "cosine",
            "dot": "dot_product",
            "inner_product": "dot_product",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in _SUPPORTED:
            raise ValueError(
                "métrica no soportada para ranking: "
                f"{metric!r}; usa euclidean, cosine o dot_product"
            )
        self.metric = normalized

    def from_search_distance(self, vector_id: Hashable, distance: float) -> SearchResult:
        """Convierte el costo interno (menor=mejor) al contrato público."""
        distance = float(distance)
        if not math.isfinite(distance):
            raise ValueError("la distancia de búsqueda debe ser finita")

        if self.metric == "euclidean":
            if distance < 0:
                raise ValueError("la distancia euclidiana no puede ser negativa")
            raw = distance
            # Score acotado (0, 1], monotónico respecto de la distancia.
            score = 1.0 / (1.0 + distance)
        elif self.metric == "cosine":
            # Convención compartida: search_distance = 1 - cosine_similarity.
            raw = 1.0 - distance
            score = raw
        else:  # dot_product
            # Convención compartida: search_distance = -dot_product.
            raw = -distance
            score = raw

        if not math.isfinite(score) or not math.isfinite(raw):
            raise ValueError("score/raw_metric debe ser finito")
        return SearchResult(
            vector_id=vector_id,
            score=score,
            raw_metric=raw,
            metric=self.metric,
        )

    def rank(
        self,
        candidates: Iterable[tuple[Hashable, float]],
        *,
        k: int | None = None,
    ) -> list[SearchResult]:
        """Normaliza, ordena y opcionalmente limita candidatos.

        Los empates se resuelven por ``repr(vector_id)`` para que el resultado
        sea determinista aun cuando los IDs tengan tipos no comparables.
        """
        if k is not None and k <= 0:
            return []
        results = [self.from_search_distance(node_id, value) for node_id, value in candidates]
        results.sort(key=lambda item: (-item.score, repr(item.vector_id)))
        return results if k is None else results[:k]
