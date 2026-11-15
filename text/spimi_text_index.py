"""Índice invertido SPIMI en disco con el ranking TF-IDF + coseno y BM25 que usa ``MATCH``.

Construcción: SPIMI por bloques -> bloques en disco -> merge k-way -> léxico.
Junto al índice se guarda ``documents.json`` con N, la longitud y la norma TF-IDF
de cada documento, que es lo único que el ranking necesita fuera de las postings.
"""

from __future__ import annotations

import heapq
import json
import math
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

from .preprocessing import DEFAULT_PREPROCESSOR
from .spimi import SPIMIBlockBuilder
from .spimi_index import SPIMIInvertedIndex
from .spimi_merge import merge_spimi_blocks
from .spimi_storage import SPIMIBlockStore, iter_block_records, replace_with_retry

DOCUMENTS_FILENAME = "documents.json"
CURRENT_FILENAME = "CURRENT"
_INDEX_DIRNAME = "index"
_FORMAT = 1


def _tie_key(doc_id) -> tuple:
    return (type(doc_id).__name__, repr(doc_id))


class SPIMITextIndex:
    def __init__(self, directory: Path, inverted: SPIMIInvertedIndex, meta: dict) -> None:
        self.directory = directory
        self.inverted = inverted
        self.signature: str = meta["signature"]
        self.lengths: List[int] = meta["lengths"]
        self.norms: List[float] = meta["norms"]
        self.block_count: int = meta["blocks"]
        self.document_count = len(self.lengths)
        total = sum(self.lengths)
        self.average_length = total / self.document_count if self.document_count else 0.0

    @property
    def vocabulary_size(self) -> int:
        return self.inverted.vocabulary_size

    @classmethod
    def build(
        cls,
        directory: str | Path,
        texts: Sequence[object],
        signature: str,
        *,
        max_postings: int = 50_000,
    ) -> "SPIMITextIndex":
        """Construye el índice para ``texts`` (doc_id = posición) y lo deja como versión vigente.

        Cada construcción va a su propia subcarpeta y ``CURRENT`` apunta a la vigente; así no se
        renombran carpetas (en Windows/OneDrive eso falla de forma intermitente).
        """
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        building = Path(tempfile.mkdtemp(dir=directory, prefix="build-"))
        try:
            lengths = [0] * len(texts)

            def documents():
                for doc_id, text in enumerate(texts):
                    tokens = DEFAULT_PREPROCESSOR.tokenize(text)
                    lengths[doc_id] = len(tokens)
                    yield doc_id, " ".join(tokens)

            store = SPIMIBlockStore(building / "blocks")
            builder = SPIMIBlockBuilder(max_postings=max_postings)
            block_paths = list(store.write_blocks(builder.iter_blocks(documents())))

            norms = [0.0] * len(texts)
            if block_paths:
                paths = merge_spimi_blocks(block_paths, building / _INDEX_DIRNAME)
                cls._accumulate_norms(paths.postings_path, len(texts), norms)
            else:
                cls._write_empty_index(building / _INDEX_DIRNAME)
            shutil.rmtree(building / "blocks", ignore_errors=True)

            meta = {
                "format": _FORMAT,
                "signature": signature,
                "blocks": len(block_paths),
                "lengths": lengths,
                "norms": [math.sqrt(x) for x in norms],
            }
            (building / DOCUMENTS_FILENAME).write_text(json.dumps(meta), encoding="utf-8")
            pointer = directory / f".{CURRENT_FILENAME}.{building.name}"
            pointer.write_text(building.name, encoding="utf-8")
            replace_with_retry(pointer, directory / CURRENT_FILENAME)
        except BaseException:
            shutil.rmtree(building, ignore_errors=True)
            raise
        for old in directory.glob("build-*"):
            if old.name != building.name:
                shutil.rmtree(old, ignore_errors=True)
        return cls.load(directory)

    @staticmethod
    def _accumulate_norms(postings_path: Path, n: int, squares: List[float]) -> None:
        """Suma ``w(t, d)^2`` por documento recorriendo cada término una sola vez."""
        current, group = None, []

        def flush():
            idf = math.log10(n / len(group))
            for doc_id, frequency in group:
                weight = (1.0 + math.log10(frequency)) * idf
                squares[doc_id] += weight * weight

        for term, doc_id, frequency in iter_block_records(postings_path):
            if term != current and group:
                flush()
                group = []
            current = term
            group.append((doc_id, frequency))
        if group:
            flush()

    @staticmethod
    def _write_empty_index(directory: Path) -> None:
        directory.mkdir()
        for name in ("inverted.spimi.jsonl", "lexicon.spimi.jsonl"):
            (directory / name).touch()

    @classmethod
    def load(cls, directory: str | Path) -> "SPIMITextIndex":
        directory = Path(directory)
        current = directory / (directory / CURRENT_FILENAME).read_text(encoding="utf-8").strip()
        meta = json.loads((current / DOCUMENTS_FILENAME).read_text(encoding="utf-8"))
        if meta.get("format") != _FORMAT:
            raise ValueError("formato de índice SPIMI no soportado")
        return cls(current, SPIMIInvertedIndex(current / _INDEX_DIRNAME), meta)

    def _postings(self, terms: Iterable[str]) -> dict:
        return {term: self.inverted.search_term(term) for term in set(terms)}

    def search_bm25(
        self, terms: Sequence[str], k: Optional[int] = None, *, k1: float = 1.2, b: float = 0.75,
    ) -> List[Tuple[int, float]]:
        n, avgdl = self.document_count, self.average_length
        if not terms or n == 0 or avgdl <= 0.0:
            return []
        postings = self._postings(terms)
        scores: dict = {}
        for term in terms:
            docs = postings[term]
            if not docs:
                continue
            df = len(docs)
            idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
            for doc_id, tf in docs.items():
                norm = 1.0 - b + b * (self.lengths[doc_id] / avgdl)
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * (tf * (k1 + 1.0)) / (tf + k1 * norm)
        return self._top(((d, s) for d, s in scores.items() if s > 0.0), k)

    def search_tfidf(self, terms: Sequence[str], k: Optional[int] = None) -> List[Tuple[int, float]]:
        n = self.document_count
        if not terms or n == 0:
            return []
        postings = self._postings(terms)
        query = {}
        for term, count in Counter(terms).items():
            df = len(postings[term])
            if df:
                weight = (1.0 + math.log10(count)) * math.log10(n / df)
                if weight > 0.0:
                    query[term] = weight
        query_norm = math.sqrt(sum(w * w for w in query.values()))
        if query_norm == 0.0:
            return []
        scores: dict = {}
        for term, query_weight in query.items():
            idf = math.log10(n / len(postings[term]))
            for doc_id, tf in postings[term].items():
                weight = (1.0 + math.log10(tf)) * idf
                scores[doc_id] = scores.get(doc_id, 0.0) + (query_weight / query_norm) * (weight / self.norms[doc_id])
        return self._top(((d, min(1.0, s)) for d, s in scores.items()), k)

    @staticmethod
    def _top(scored, k: Optional[int]) -> List[Tuple[int, float]]:
        key = lambda item: (-item[1], _tie_key(item[0]))
        if k is None:
            return sorted(scored, key=key)
        return heapq.nsmallest(k, scored, key=key)
