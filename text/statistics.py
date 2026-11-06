"""Estadísticas de colección requeridas por BM25."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Hashable, Iterable, Mapping, Set

DocumentId = Hashable


@dataclass
class BM25Statistics:
    """Mantiene TF, DF, longitud por documento, N y avgdl."""

    _term_frequencies: Dict[DocumentId, Counter[str]] = field(default_factory=dict)
    _document_frequencies: Counter[str] = field(default_factory=Counter)
    _postings: Dict[str, Set[DocumentId]] = field(default_factory=dict)
    _document_lengths: Dict[DocumentId, int] = field(default_factory=dict)
    _total_document_length: int = 0
    revision: int = 0

    def __len__(self) -> int:
        return self.document_count

    @property
    def document_count(self) -> int:
        """Número total de documentos registrados (N)."""
        return len(self._document_lengths)

    @property
    def average_document_length(self) -> float:
        """Longitud promedio de documentos (avgdl)."""
        if not self._document_lengths:
            return 0.0
        return self._total_document_length / self.document_count

    @property
    def document_ids(self) -> frozenset[DocumentId]:
        """Identificadores de todos los documentos registrados."""
        return frozenset(self._document_lengths)

    def add_document(self, doc_id: DocumentId, tokens: Iterable[str]) -> None:
        """Registra un documento a partir de tokens ya preprocesados."""
        if doc_id in self._document_lengths:
            raise ValueError(f"document '{doc_id}' is already registered")

        token_list = list(tokens)
        frequencies = Counter(token_list)

        self._term_frequencies[doc_id] = frequencies
        self._document_lengths[doc_id] = len(token_list)
        self._total_document_length += len(token_list)
        self.revision += 1

        for term in frequencies:
            self._document_frequencies[term] += 1
            self._postings.setdefault(term, set()).add(doc_id)

    def remove_document(self, doc_id: DocumentId) -> bool:
        """Elimina las estadísticas de un documento y actualiza DF/avgdl."""
        if doc_id not in self._document_lengths:
            return False

        frequencies = self._term_frequencies.pop(doc_id)
        length = self._document_lengths.pop(doc_id)
        self._total_document_length -= length
        self.revision += 1

        for term in frequencies:
            self._document_frequencies[term] -= 1
            posting = self._postings.get(term)
            if posting is not None:
                posting.discard(doc_id)
                if not posting:
                    del self._postings[term]
            if self._document_frequencies[term] <= 0:
                del self._document_frequencies[term]

        return True

    def term_frequency(self, term: str, doc_id: DocumentId) -> int:
        """Devuelve tf(term, doc_id); 0 si no existe término o documento."""
        frequencies = self._term_frequencies.get(doc_id)
        if frequencies is None:
            return 0
        return frequencies.get(term, 0)

    def document_frequency(self, term: str) -> int:
        """Devuelve df(term); 0 si el término no aparece en la colección."""
        return self._document_frequencies.get(term, 0)

    def documents_for_term(self, term: str) -> frozenset[DocumentId]:
        """Documentos que contienen ``term`` sin recorrer toda la colección."""
        return frozenset(self._postings.get(term, ()))

    def candidate_documents(self, terms: Iterable[str]) -> set[DocumentId]:
        """Unión de postings para una consulta ya preprocesada."""
        candidates: set[DocumentId] = set()
        for term in terms:
            candidates.update(self._postings.get(term, ()))
        return candidates

    def document_length(self, doc_id: DocumentId) -> int:
        """Devuelve |d|. Lanza KeyError si el documento no está registrado."""
        if doc_id not in self._document_lengths:
            raise KeyError(f"unknown document: {doc_id}")
        return self._document_lengths[doc_id]

    def document_term_frequencies(self, doc_id: DocumentId) -> Mapping[str, int]:
        """Vista de las frecuencias de un documento para el ranker BM25."""
        if doc_id not in self._term_frequencies:
            raise KeyError(f"unknown document: {doc_id}")
        return dict(self._term_frequencies[doc_id])

    def clear(self) -> None:
        """Vacía todas las estadísticas."""
        self._term_frequencies.clear()
        self._document_frequencies.clear()
        self._postings.clear()
        self._document_lengths.clear()
        self._total_document_length = 0
        self.revision += 1

    @classmethod
    def from_documents(
        cls,
        documents: Mapping[DocumentId, Iterable[str]],
    ) -> "BM25Statistics":
        """Construye las estadísticas desde ``doc_id -> tokens``."""
        stats = cls()
        for doc_id, tokens in documents.items():
            stats.add_document(doc_id, tokens)
        return stats
