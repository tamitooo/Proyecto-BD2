"""Visual/auditory bag-of-words histograms (issue #105)."""

from __future__ import annotations

import numpy as np


def word_histogram(
    word_ids: np.ndarray,
    vocabulary_size: int,
    *,
    normalization: str | None = "l1",
) -> np.ndarray:
    """Count word IDs into a fixed-length float32 vector, optionally L1/L2 normalized."""
    if type(vocabulary_size) is not int or vocabulary_size < 1:
        raise ValueError("vocabulary_size must be a positive integer")
    if normalization not in (None, "l1", "l2"):
        raise ValueError("normalization must be None, 'l1' or 'l2'")
    words = np.asarray(word_ids)
    if words.ndim != 1 or (words.size and not np.issubdtype(words.dtype, np.integer)):
        raise ValueError("word IDs must be a one-dimensional integer array")
    if words.size and (int(words.min()) < 0 or int(words.max()) >= vocabulary_size):
        raise ValueError("word ID outside vocabulary")
    histogram = np.bincount(words.astype(np.int64), minlength=vocabulary_size).astype(np.float32)
    if normalization is not None:
        norm = histogram.sum() if normalization == "l1" else np.linalg.norm(histogram)
        if norm > 0:
            histogram /= norm
    return histogram
