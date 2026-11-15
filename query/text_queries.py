"""Ejecución de ``MATCH(...)`` con TF-IDF o BM25 y ``SCORE()`` sobre un índice invertido SPIMI.

El índice se guarda en ``<data_dir>/indexes/<tabla>__<columna>__spimi/`` y se reutiliza
mientras el contenido de la columna no cambie (se compara una firma del contenido).
"""

from __future__ import annotations

import atexit
import hashlib
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from text.preprocessing import tokenize
from text.spimi_text_index import SPIMITextIndex


class TextQueryError(Exception):
    pass


_DEFAULT_RANKING = "bm25"
_RANKINGS = {"bm25", "tf_idf"}
_LOADED: Dict[str, SPIMITextIndex] = {}


def _safe(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in value.lower())


def spimi_index_dir(data_dir, table_name: str, column: str) -> Path:
    return Path(data_dir) / "indexes" / f"{_safe(table_name)}__{_safe(column)}__spimi"


def drop_spimi_indexes(data_dir, table_name: str) -> None:
    directory = Path(data_dir) / "indexes"
    if not directory.is_dir():
        return
    for path in directory.glob(f"{_safe(table_name)}__*__spimi"):
        _LOADED.pop(str(path), None)
        shutil.rmtree(path, ignore_errors=True)


_SCRATCH: Optional[Path] = None


def _scratch_dir() -> Path:
    """Carpeta temporal del proceso para catálogos sin ``data_dir``."""
    global _SCRATCH
    if _SCRATCH is None:
        _SCRATCH = Path(tempfile.mkdtemp(prefix="bd2-spimi-"))
        atexit.register(shutil.rmtree, _SCRATCH, True)
    return _SCRATCH


def _signature(texts) -> str:
    digest = hashlib.sha256()
    for text in texts:
        digest.update(b"\x00" if text is None else b"\x01" + str(text).encode("utf-8"))
        digest.update(b"\x1e")
    return digest.hexdigest()


class TextExecutor:
    """Ejecuta ``MATCH(columna, 'texto')`` sobre una tabla del motor."""

    def __init__(self, catalog):
        self.catalog = catalog

    def execute(self, table, spec, *, limit: Optional[int] = None, row_filter=None):
        column, terms, ranking = self._validate(table, spec)
        rows = [dict(raw) for _, raw in table.storage.scan()]
        if not rows:
            raise TextQueryError(f"la tabla '{table.name}' está vacía")
        allowed = None
        if row_filter is not None:
            allowed = {i for i, row in enumerate(rows) if row_filter(row)}
            if not allowed:
                raise TextQueryError("ninguna fila cumple el resto del WHERE")

        started = time.perf_counter()
        index, reused, index_path = self._load_or_build(table.name, column, [row.get(column) for row in rows])
        build_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        search = index.search_tfidf if ranking == "tf_idf" else index.search_bm25
        if allowed is None:
            results = search(terms, limit)
        else:
            results = [hit for hit in search(terms) if hit[0] in allowed]
            if limit is not None:
                results = results[:limit]
        search_ms = (time.perf_counter() - started) * 1000

        out: List[Dict[str, Any]] = []
        for doc_id, score in results:
            row = dict(rows[doc_id])
            row["_score"] = score
            row["_ranking"] = ranking
            out.append(row)
        k = limit if limit is not None else len(rows)
        details = {
            "reused": reused,
            "index_path": index_path,
            "blocks": index.block_count,
            "vocabulary": index.vocabulary_size,
            "build_ms": round(build_ms, 3),
        }
        filtered = len(allowed) if allowed is not None else len(rows)
        return out, self._plan(table, column, ranking, k, filtered, len(terms), search_ms, len(out), details)

    def plan(self, table, spec, *, limit: Optional[int] = None, row_filter=None):
        """Plan que usaría la consulta, sin ejecutar la búsqueda."""
        column, terms, ranking = self._validate(table, spec)
        documents = sum(1 for _, raw in table.storage.scan() if row_filter is None or row_filter(dict(raw)))
        if not documents:
            raise TextQueryError(f"la tabla '{table.name}' está vacía")
        k = limit if limit is not None else documents
        data_dir = getattr(self.catalog, "data_dir", None)
        details = {"index_path": str(spimi_index_dir(data_dir, table.name, column)) if data_dir else None}
        return self._plan(table, column, ranking, k, documents, len(terms), 0.0, 0, details)

    @staticmethod
    def _validate(table, spec):
        column = spec.predicate.column
        if column not in table.schema.col_names():
            raise TextQueryError(f"la columna '{column}' no existe en '{table.name}'")
        terms = tokenize(spec.predicate.query)
        if not terms:
            raise TextQueryError("MATCH requiere al menos un término de búsqueda")
        ranking = (spec.ranking or _DEFAULT_RANKING).lower()
        if ranking not in _RANKINGS:
            raise TextQueryError(f"modelo de ranking no soportado: {ranking}")
        return column, terms, ranking

    def _load_or_build(self, table_name, column, texts):
        signature = _signature(texts)
        data_dir = getattr(self.catalog, "data_dir", None)
        persisted = data_dir is not None
        if not persisted:
            data_dir = _scratch_dir() / str(id(self.catalog))

        directory = spimi_index_dir(data_dir, table_name, column)
        key = str(directory)
        index = _LOADED.get(key)
        if index is None and directory.is_dir():
            try:
                index = SPIMITextIndex.load(directory)
            except (OSError, ValueError, KeyError, TypeError):
                index = None
        if index is not None and index.signature == signature and index.document_count == len(texts):
            _LOADED[key] = index
            return index, True, key if persisted else None
        index = SPIMITextIndex.build(directory, texts, signature)
        _LOADED[key] = index
        return index, False, key if persisted else None

    @staticmethod
    def _plan(table, column, ranking, k, documents, terms, search_ms, rows_out, details):
        operator = "TEXT_TF_IDF" if ranking == "tf_idf" else "TEXT_BM25"
        return {
            "table": table.name,
            "planner_type": "text_index",
            "access_path": operator,
            "used_indexes": [column],
            "steps": [
                {
                    "operator": operator,
                    "table": table.name,
                    "index": column,
                    "reason": f"{ranking.upper()} sobre '{column}' leyendo postings del índice SPIMI",
                    "details": {"k": k, "terms": terms, "documents": documents,
                                "build_ms": details.get("build_ms", 0.0)},
                },
                {
                    "operator": "SPIMI_INDEX",
                    "table": table.name,
                    "index": column,
                    "reason": "índice invertido SPIMI en disco (bloques + merge)",
                    "details": details,
                },
            ],
            "runtime_steps": [
                {"operator": operator, "elapsed_ms": round(search_ms, 3), "rows_out": rows_out, "index": column}
            ],
        }
