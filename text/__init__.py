"""Módulos de búsqueda textual (Parte 3)."""

from .bm25 import BM25Ranker
from .statistics import BM25Statistics
from .tfidf import TFIDFRanker, TFIDFWeighter, sparse_cosine_similarity
from .spimi import SPIMIBlock, SPIMIBlockBuilder
from .preprocessing import (
    DEFAULT_PREPROCESSOR,
    TextPreprocessor,
    tokenize,
)
from .spimi_storage import SPIMIBlockStore, iter_block_records
from .spimi_merge import SPIMIIndexPaths, merge_spimi_blocks
from .spimi_index import SPIMIInvertedIndex

__all__ = [
    "BM25Statistics",
    "BM25Ranker",
    "TFIDFRanker",
    "TFIDFWeighter",
    "sparse_cosine_similarity",
    "DEFAULT_PREPROCESSOR",
    "TextPreprocessor",
    "tokenize",

    # Issue #45: In-memory SPIMI
    "SPIMIBlock",
    "SPIMIBlockBuilder",

    # Issue #46: Disk-backed block storage
    "SPIMIBlockStore",
    "iter_block_records",

    # Issue #47: Block merging
    "SPIMIIndexPaths",
    "merge_spimi_blocks",

    # Issue #48: Inverted-index retrieval
    "SPIMIInvertedIndex",
]
