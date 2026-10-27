"""Ranking BM25 para la Parte 3 del proyecto.

El ranker consume :class:`BM25Statistics`; no tokeniza documentos ni consultas.
Los términos deben llegar ya normalizados por el mismo pipeline que construye
SPIMI para mantener una única representación textual en todo el motor.
"""

from __future__ import annotations

import math
from typing import Iterable

from .statistics import BM25Statistics, DocumentId


class BM25Ranker:
    """Calcula scores BM25 para documentos ya registrados en la colección.

    Parámetros por defecto habituales:
    - ``k1=1.2`` controla la saturación de la frecuencia del término.
    - ``b=0.75`` controla la normalización por longitud de documento.

    Este issue implementa únicamente la función de scoring. La selección de
    candidatos y el ranking top-k pertenecen al issue #55.
    """

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
        """Devuelve el IDF estable usado por BM25.

        Fórmula::

            log(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

        Para una colección vacía o un término ausente retorna ``0.0``: un
        término sin postings no puede contribuir al score de ningún documento.
        """
        n = self.statistics.document_count
        df = self.statistics.document_frequency(term)

        if n == 0 or df == 0:
            return 0.0

        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    # Alias corto útil al integrar el ranker con otras capas.
    idf = inverse_document_frequency

    def term_score(self, term: str, doc_id: DocumentId) -> float:
        """Calcula el aporte BM25 de ``term`` al documento ``doc_id``."""
        tf = self.statistics.term_frequency(term, doc_id)
        if tf <= 0:
            # Si el documento no existe term_frequency también retorna 0. La
            # validación explícita de doc_id se hace en score/document_length.
            return 0.0

        doc_length = self.statistics.document_length(doc_id)
        avgdl = self.statistics.average_document_length
        if avgdl <= 0.0:
            # Solo puede ocurrir si todos los documentos de la colección son
            # vacíos; en ese caso tf necesariamente sería 0, pero mantenemos
            # la defensa para evitar división por cero ante estados inválidos.
            return 0.0

        idf = self.inverse_document_frequency(term)
        normalization = 1.0 - self.b + self.b * (doc_length / avgdl)
        denominator = tf + self.k1 * normalization
        numerator = tf * (self.k1 + 1.0)
        return idf * (numerator / denominator)

    def score(self, doc_id: DocumentId, query_terms: Iterable[str]) -> float:
        """Calcula el score BM25 total de un documento para una consulta.

        ``query_terms`` debe haber pasado por el mismo preprocesamiento que los
        documentos. Si un término se repite en la consulta, su aporte se suma
        nuevamente; esto conserva literalmente la multiplicidad de la consulta
        y mantiene este módulo independiente de decisiones de query parsing.
        """
        # Fuerza un error claro para documentos desconocidos incluso si la
        # consulta está vacía o todos sus términos están ausentes.
        self.statistics.document_length(doc_id)
        return sum(self.term_score(term, doc_id) for term in query_terms)
