"""Issues #57 (selección del modelo de ranking), #58 (``SCORE()``) y #60
(integración con el Query Executor). El preprocesamiento viene de
:mod:`text.preprocessing` para que SQL y motor usen la misma tokenización.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from text.bm25 import BM25Ranker
from text.statistics import BM25Statistics
from text.tfidf import TFIDFRanker
from text.preprocessing import tokenize


class TextQueryError(Exception):
    pass


_DEFAULT_RANKING = "bm25"


class TextExecutor:
    """Ejecuta ``MATCH(columna, 'texto')`` sobre una tabla del motor."""

    def __init__(self, catalog):
        self.catalog = catalog

    def execute(self, table, spec, *, limit: Optional[int] = None):
        predicate = spec.predicate
        column = predicate.column
        if column not in table.schema.col_names():
            raise TextQueryError(f"la columna '{column}' no existe en '{table.name}'")
        rows: List[Dict[str, Any]] = []
        documents: Dict[int, List[str]] = {}
        for _, raw in table.storage.scan():
            row = dict(raw)
            documents[len(rows)] = tokenize(row.get(column))
            rows.append(row)
        if not rows:
            raise TextQueryError(f"la tabla '{table.name}' está vacía")
        query_terms = tokenize(predicate.query)
        if not query_terms:
            raise TextQueryError("MATCH requiere al menos un término de búsqueda")
        ranking = (spec.ranking or _DEFAULT_RANKING).lower()
        k = limit if limit is not None else len(rows)

        started = time.perf_counter()
        statistics = BM25Statistics.from_documents(documents)
        if ranking == "tf_idf":
            ranker = TFIDFRanker(statistics)
        elif ranking == "bm25":
            ranker = BM25Ranker(statistics)
        else:
            raise TextQueryError(f"modelo de ranking no soportado: {ranking}")
        build_ms = (time.perf_counter() - started) * 1000

        started = time.perf_counter()
        try:
            results = ranker.search(query_terms, k=k)
        except (KeyError, ValueError) as exc:
            raise TextQueryError(str(exc)) from None
        search_ms = (time.perf_counter() - started) * 1000

        out: List[Dict[str, Any]] = []
        for doc_id, score in results:
            row = dict(rows[doc_id])
            row["_score"] = score
            row["_ranking"] = ranking
            out.append(row)
        return out, self._plan(table, column, ranking, k, len(rows), len(query_terms), build_ms, search_ms, len(out))

    def plan(self, table, spec, *, limit: Optional[int] = None):
        """Plan que usaría la consulta, sin ejecutar la búsqueda."""
        column = spec.predicate.column
        if column not in table.schema.col_names():
            raise TextQueryError(f"la columna '{column}' no existe en '{table.name}'")
        documents = sum(1 for _ in table.storage.scan())
        if not documents:
            raise TextQueryError(f"la tabla '{table.name}' está vacía")
        terms = tokenize(spec.predicate.query)
        if not terms:
            raise TextQueryError("MATCH requiere al menos un término de búsqueda")
        ranking = (spec.ranking or _DEFAULT_RANKING).lower()
        if ranking not in {"bm25", "tf_idf"}:
            raise TextQueryError(f"modelo de ranking no soportado: {ranking}")
        k = limit if limit is not None else documents
        return self._plan(table, column, ranking, k, documents, len(terms), 0.0, 0.0, 0)

    @staticmethod
    def _plan(table, column, ranking, k, documents, terms, build_ms, search_ms, rows_out):
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
                    "reason": f"{ranking.upper()} sobre '{column}'",
                    "details": {
                        "k": k,
                        "terms": terms,
                        "documents": documents,
                        "build_ms": round(build_ms, 3),
                    },
                }
            ],
            "runtime_steps": [
                {"operator": operator, "elapsed_ms": round(search_ms, 3), "rows_out": rows_out, "index": column}
            ],
        }
