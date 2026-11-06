"""Ranking TF-IDF + coseno (Parte 3).

    w(t, d) = (1 + log10(tf(t, d))) * log10(N / df(t))

Usa la variante de TF de la diapositiva 68 de la semana 07.
"""

from __future__ import annotations

import heapq
import math
from collections import Counter
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .statistics import BM25Statistics, DocumentId

SparseVector = Dict[str, float]


def sparse_cosine_similarity(
    first: Mapping[str, float], second: Mapping[str, float]
) -> float:
    """Coseno entre vectores dispersos; ``0.0`` si alguno está vacío."""
    first_norm = _norm(first)
    second_norm = _norm(second)
    if first_norm == 0.0 or second_norm == 0.0:
        return 0.0

    cosine = sum(
        (first[term] / first_norm) * (second[term] / second_norm)
        for term in first.keys() & second.keys()
    )
    return max(-1.0, min(1.0, cosine))


def _norm(vector: Mapping[str, float]) -> float:
    norm = math.hypot(*vector.values())
    if not math.isfinite(norm):
        raise ValueError("vector weights must be finite")
    return norm


class TFIDFWeighter:
    def __init__(self, statistics: BM25Statistics) -> None:
        if not isinstance(statistics, BM25Statistics):
            raise TypeError("statistics must be a BM25Statistics instance")
        self.statistics = statistics

    @staticmethod
    def term_frequency_weight(count: int) -> float:
        """``1 + log10(count)``; ``0.0`` si ``count`` es 0."""
        if count < 0:
            raise ValueError("count must be >= 0")
        if count == 0:
            return 0.0
        return 1.0 + math.log10(count)

    def inverse_document_frequency(self, term: str) -> float:
        """``log10(N / df)``; ``0.0`` si el término no existe."""
        n = self.statistics.document_count
        df = self.statistics.document_frequency(term)

        if n == 0 or df == 0:
            return 0.0

        return math.log10(n / df)

    idf = inverse_document_frequency

    def weight(self, term: str, doc_id: DocumentId) -> float:
        # term_frequency devuelve 0 también para documentos desconocidos.
        self.statistics.document_length(doc_id)

        count = self.statistics.term_frequency(term, doc_id)
        return self.term_frequency_weight(count) * self.idf(term)

    def document_vector(self, doc_id: DocumentId) -> SparseVector:
        return self._vector(self.statistics.document_term_frequencies(doc_id))

    def query_vector(self, query_terms: Iterable[str]) -> SparseVector:
        if isinstance(query_terms, str):
            raise TypeError("query_terms must be an iterable of terms, not a str")
        return self._vector(Counter(query_terms))

    def _vector(self, frequencies: Mapping[str, int]) -> SparseVector:
        weights = {
            term: self.term_frequency_weight(count) * self.idf(term)
            for term, count in frequencies.items()
        }
        return {term: weight for term, weight in weights.items() if weight > 0.0}


class TFIDFRanker:
    """Ordena documentos por coseno; guarda sus normas hasta que cambie la colección."""

    def __init__(self, statistics: BM25Statistics) -> None:
        self.weighter = TFIDFWeighter(statistics)
        self.statistics = statistics
        self._norms: Dict[DocumentId, float] = {}
        self._norms_revision: Optional[int] = None

    def document_norms(self) -> Mapping[DocumentId, float]:
        if self._norms_revision != self.statistics.revision:
            self._norms = {
                doc_id: _norm(self.weighter.document_vector(doc_id))
                for doc_id in self.statistics.document_ids
            }
            self._norms_revision = self.statistics.revision
        return self._norms

    def score(self, doc_id: DocumentId, query_terms: Iterable[str]) -> float:
        return sparse_cosine_similarity(
            self.weighter.query_vector(query_terms),
            self.weighter.document_vector(doc_id),
        )

    def search(
        self, query_terms: Iterable[str], k: int = 10
    ) -> List[Tuple[DocumentId, float]]:
        if not isinstance(k, int):
            raise TypeError("k must be an integer")

        query = self.weighter.query_vector(query_terms)
        if k <= 0 or not query:
            return []

        norms = self.document_norms()
        query_norm = _norm(query)
        scores: Dict[DocumentId, float] = {}

        for term, query_weight in query.items():
            idf = self.weighter.idf(term)
            for doc_id in self.statistics.documents_for_term(term):
                count = self.statistics.term_frequency(term, doc_id)
                weight = self.weighter.term_frequency_weight(count) * idf
                scores[doc_id] = scores.get(doc_id, 0.0) + (
                    (query_weight / query_norm) * (weight / norms[doc_id])
                )

        return heapq.nsmallest(
            k,
            ((doc_id, min(1.0, score)) for doc_id, score in scores.items()),
            key=lambda item: (-item[1], type(item[0]).__name__, repr(item[0])),
        )
