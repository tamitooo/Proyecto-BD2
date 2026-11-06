"""TF-IDF weighting for fixed-length visual/audio histograms (issue #106).

Uses smooth IDF ``log((1 + N) / (1 + df)) + 1`` and L2-normalized vectors
for cosine search with the project's IVF/HNSW indices. Fit a *separate*
weighter on each modality's training corpus to avoid mixing statistics.
"""

from __future__ import annotations

import numpy as np


def _histogram_matrix(values: np.ndarray) -> tuple[np.ndarray, bool]:
    matrix = np.asarray(values, dtype=np.float64)
    one = matrix.ndim == 1
    if one:
        matrix = matrix[None, :]
    if matrix.ndim != 2 or matrix.shape[1] < 1:
        raise ValueError("histograms must have shape (N, vocabulary_size)")
    if not np.isfinite(matrix).all() or np.any(matrix < 0):
        raise ValueError("histograms must be finite and nonnegative")
    return matrix, one


class HistogramTFIDF:
    """Corpus-fitted TF-IDF model; never fit independently on query objects."""

    def __init__(self) -> None:
        self.idf_: np.ndarray | None = None
        self.document_count_: int = 0

    def fit(self, histograms: np.ndarray) -> "HistogramTFIDF":
        matrix, one = _histogram_matrix(histograms)
        if one or len(matrix) == 0:
            raise ValueError("fit requires a nonempty (documents, words) matrix")
        self.document_count_ = matrix.shape[0]
        df = np.count_nonzero(matrix > 0, axis=0)
        self.idf_ = np.log((1.0 + len(matrix)) / (1.0 + df)) + 1.0
        return self

    def transform(self, histograms: np.ndarray) -> np.ndarray:
        if self.idf_ is None:
            raise RuntimeError("TF-IDF must be fitted before transformation")
        matrix, one = _histogram_matrix(histograms)
        if matrix.shape[1] != len(self.idf_):
            raise ValueError("histogram vocabulary does not match fitted TF-IDF")
        tf = matrix / np.maximum(matrix.sum(axis=1, keepdims=True), 1e-30)
        weighted = tf * self.idf_
        weighted /= np.maximum(np.linalg.norm(weighted, axis=1, keepdims=True), 1e-30)
        result = weighted.astype(np.float32)
        return result[0] if one else result

    def fit_transform(self, histograms: np.ndarray) -> np.ndarray:
        return self.fit(histograms).transform(histograms)
