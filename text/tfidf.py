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

Documentos y consultas se representan como vectores dispersos (issue #50) y se
comparan con la similitud del coseno (issue #51) para el ranking top-k (issue
#52).
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
    """Similitud del coseno entre dos vectores dispersos, en ``[-1, 1]``.

    La normalización por longitud evita que un documento gane solo por ser
    largo. Un vector vacío no tiene dirección y devuelve ``0.0``: una consulta
    sin términos conocidos es válida y simplemente no se parece a nada.
    """
    first_norm = _norm(first)
    second_norm = _norm(second)
    if first_norm == 0.0 or second_norm == 0.0:
        return 0.0

    # Solo los términos comunes aportan. Normalizar antes de multiplicar evita
    # overflow y underflow, igual que el coseno de vector/metrics.py.
    cosine = sum(
        (first[term] / first_norm) * (second[term] / second_norm)
        for term in first.keys() & second.keys()
    )
    # El redondeo puede dejar el resultado apenas fuera de [-1, 1].
    return max(-1.0, min(1.0, cosine))


def _norm(vector: Mapping[str, float]) -> float:
    norm = math.hypot(*vector.values())
    if not math.isfinite(norm):
        raise ValueError("vector weights must be finite")
    return norm


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


class TFIDFRanker:
    """Ordena documentos por similitud del coseno entre vectores TF-IDF.

    Tiene el mismo contrato que :class:`BM25Ranker` para poder compararlos.

    La norma de cada documento depende de todos sus términos, pero el producto
    punto solo de los de la consulta. Por eso las normas se calculan una vez y
    la búsqueda recorre únicamente los postings consultados, en lugar de
    reconstruir el vector de cada candidato. Como N cambia los IDF de toda la
    colección, cualquier modificación obliga a recalcular todas las normas.
    """

    def __init__(self, statistics: BM25Statistics) -> None:
        self.weighter = TFIDFWeighter(statistics)
        self.statistics = statistics
        self._norms: Dict[DocumentId, float] = {}
        self._norms_revision: Optional[int] = None

    def document_norms(self) -> Mapping[DocumentId, float]:
        """Devuelve ``doc_id -> norma``, recalculándolas si la colección cambió.

        La primera búsqueda las calcula sola. Llamarlo después de cargar la
        colección evita que ese costo caiga sobre esa consulta.
        """
        if self._norms_revision != self.statistics.revision:
            self._norms = {
                doc_id: _norm(self.weighter.document_vector(doc_id))
                for doc_id in self.statistics.document_ids
            }
            self._norms_revision = self.statistics.revision
        return self._norms

    def score(self, doc_id: DocumentId, query_terms: Iterable[str]) -> float:
        """Calcula la similitud entre un documento y una consulta.

        Lanza KeyError si el documento no está registrado.
        """
        return sparse_cosine_similarity(
            self.weighter.query_vector(query_terms),
            self.weighter.document_vector(doc_id),
        )

    def search(
        self, query_terms: Iterable[str], k: int = 10
    ) -> List[Tuple[DocumentId, float]]:
        """Retorna los ``k`` documentos más similares a la consulta.

        Ordena por score descendente; los empates se resuelven como en BM25.
        Los documentos sin similitud no se incluyen.
        """
        if not isinstance(k, int):
            raise TypeError("k must be an integer")

        query = self.weighter.query_vector(query_terms)
        if k <= 0 or not query:
            return []

        norms = self.document_norms()
        query_norm = _norm(query)
        scores: Dict[DocumentId, float] = {}

        # El vector de consulta ya descarta los términos presentes en toda la
        # colección, que obligarían a recorrerla completa.
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
            # El redondeo puede dejar el score apenas por encima de 1.
            ((doc_id, min(1.0, score)) for doc_id, score in scores.items()),
            key=lambda item: (-item[1], type(item[0]).__name__, repr(item[0])),
        )
