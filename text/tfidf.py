"""Pesos TF-IDF para la Parte 3 del proyecto (issue #49).

El peso de un término en un documento combina dos señales::

    w(t, d) = tf_weight(t, d) * idf(t)
    tf_weight(t, d) = 1 + log10(tf(t, d))    si tf(t, d) > 0, si no 0
    idf(t) = log10(N / df(t))

La clase de la semana 07 muestra varias formas de calcular el TF. Esta es la que
usa su ejemplo de TF-IDF + coseno (diapositiva 68), que es lo que pide el proyecto.

Reutiliza :class:`BM25Statistics` en lugar de recontar: TF, DF y N son los mismos
que usa BM25, y compartirlos garantiza que ambos rankings vean la misma
colección. Tampoco tokeniza: los términos deben llegar ya normalizados.

Documentos y consultas se representan como vectores dispersos (issue #50). La
similitud del coseno corresponde al issue #51 y el ranking top-k al #52.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Dict, Iterable, Mapping

from .statistics import BM25Statistics, DocumentId

SparseVector = Dict[str, float]


class TFIDFWeighter:
    """Calcula pesos TF-IDF de términos ya registrados en la colección."""

    def __init__(self, statistics: BM25Statistics) -> None:
        if not isinstance(statistics, BM25Statistics):
            raise TypeError("statistics must be a BM25Statistics instance")
        self.statistics = statistics

    @staticmethod
    def term_frequency_weight(count: int) -> float:
        """Amortigua una frecuencia cruda: ``1 + log10(count)``.

        Recibe la frecuencia y no un documento para que el issue #50 también
        pueda aplicarla a los términos de una consulta. Aparecer 10 veces no
        hace a un término 10 veces más importante, sino 2 veces.
        """
        if count < 0:
            raise ValueError("count must be >= 0")
        if count == 0:
            return 0.0
        return 1.0 + math.log10(count)

    def inverse_document_frequency(self, term: str) -> float:
        """Devuelve ``log10(N / df(t))``.

        Es ``0.0`` para un término ausente, que no puede aportar a ningún
        documento, y también para uno presente en toda la colección, que no
        sirve para distinguir documentos.
        """
        n = self.statistics.document_count
        df = self.statistics.document_frequency(term)

        if n == 0 or df == 0:
            return 0.0

        return math.log10(n / df)

    # Alias corto, igual que en BM25Ranker.
    idf = inverse_document_frequency

    def weight(self, term: str, doc_id: DocumentId) -> float:
        """Calcula el peso TF-IDF de ``term`` en el documento ``doc_id``."""
        # Fuerza un error claro para documentos desconocidos: term_frequency
        # los confundiría con un documento que no contiene el término.
        self.statistics.document_length(doc_id)

        count = self.statistics.term_frequency(term, doc_id)
        return self.term_frequency_weight(count) * self.idf(term)

    def document_vector(self, doc_id: DocumentId) -> SparseVector:
        """Devuelve el vector TF-IDF de un documento como ``término -> peso``.

        Lanza KeyError si el documento no está registrado.
        """
        return self._vector(self.statistics.document_term_frequencies(doc_id))

    def query_vector(self, query_terms: Iterable[str]) -> SparseVector:
        """Devuelve el vector TF-IDF de una consulta ya preprocesada.

        Se pondera como un documento, contando los términos repetidos. Un
        término que no existe en la colección no aporta y queda fuera.
        """
        if isinstance(query_terms, str):
            # Iterar un str daría caracteres sueltos en lugar de términos.
            raise TypeError("query_terms must be an iterable of terms, not a str")
        return self._vector(Counter(query_terms))

    def _vector(self, frequencies: Mapping[str, int]) -> SparseVector:
        """Pondera ``término -> frecuencia``; los pesos en cero no se guardan.

        Con vocabularios grandes un documento solo tiene una fracción mínima
        de los términos, y un vector denso no cabría en memoria.
        """
        weights = {
            term: self.term_frequency_weight(count) * self.idf(term)
            for term, count in frequencies.items()
        }
        return {term: weight for term, weight in weights.items() if weight > 0.0}
