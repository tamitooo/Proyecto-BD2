"""Ranking BM25 para la Parte 3 del proyecto."""

from __future__ import annotations

import heapq
import math
from typing import Iterable, List, Tuple

from .statistics import BM25Statistics, DocumentId


class BM25Ranker:
    """Calcula scores BM25 para documentos ya registrados en la colección."""

    def __init__(
        self,
        statistics: BM25Statistics,
        *,
        k1: float = 1.2,
        b: float = 0.75,
    ) -> None:
        if not isinstance(statistics, BM25Statistics):
            raise TypeError("statistics must be a BM25Statistics instance")
        if not math.isfinite(k1) or k1 <= 0:
            raise ValueError("k1 must be a finite number > 0")
        if not math.isfinite(b) or not 0.0 <= b <= 1.0:
            raise ValueError("b must be a finite number between 0 and 1")

        self.statistics = statistics
        self.k1 = float(k1)
        self.b = float(b)

    def inverse_document_frequency(self, term: str) -> float:
        """Devuelve el IDF estable usado por BM25."""
        n = self.statistics.document_count
        df = self.statistics.document_frequency(term)

        if n == 0 or df == 0:
            return 0.0

        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    idf = inverse_document_frequency

    def term_score(self, term: str, doc_id: DocumentId) -> float:
        """Calcula el aporte BM25 de ``term`` al documento ``doc_id``."""
        tf = self.statistics.term_frequency(term, doc_id)
        if tf <= 0:
            return 0.0

        doc_length = self.statistics.document_length(doc_id)
        avgdl = self.statistics.average_document_length
        if avgdl <= 0.0:
            return 0.0

        idf = self.inverse_document_frequency(term)
        normalization = 1.0 - self.b + self.b * (doc_length / avgdl)
        denominator = tf + self.k1 * normalization
        numerator = tf * (self.k1 + 1.0)
        return idf * (numerator / denominator)

    def score(self, doc_id: DocumentId, query_terms: Iterable[str]) -> float:
        """Calcula el score BM25 total de un documento para una consulta."""
        # Fuerza un error claro para documentos desconocidos incluso si la
        # consulta está vacía o todos sus términos están ausentes.
        self.statistics.document_length(doc_id)
        return sum(self.term_score(term, doc_id) for term in query_terms)

    def search(self, query_terms: Iterable[str], k: int = 10) -> List[Tuple[DocumentId, float]]:
        """Retorna los ``k`` documentos con mayor score BM25."""
        if not isinstance(k, int):
            raise TypeError("k must be an integer")
        if k <= 0:
            return []

        terms = list(query_terms)
        if not terms:
            return []

        candidates = self.statistics.candidate_documents(terms)
        if not candidates:
            return []

        scored = [(doc_id, self.score(doc_id, terms)) for doc_id in candidates]
        scored = [(doc_id, score) for doc_id, score in scored if score > 0.0]
        if not scored:
            return []

        # Para mantener compatibilidad con DocumentId hashable (int/str/etc.),
        # el desempate determinista se basa en (tipo, repr).
        def tie_key(doc_id: DocumentId):
            return (type(doc_id).__name__, repr(doc_id))

        best = heapq.nsmallest(
            min(k, len(scored)),
            scored,
            key=lambda item: (-item[1], tie_key(item[0])),
        )
        return sorted(best, key=lambda item: (-item[1], tie_key(item[0])))
