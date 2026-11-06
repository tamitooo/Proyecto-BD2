"""In-memory SPIMI block construction from a stream of ``(doc_id, text)`` records."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Iterable, Iterator, Mapping

from .preprocessing import DEFAULT_PREPROCESSOR, TextPreprocessor
from .statistics import DocumentId


@dataclass(frozen=True, slots=True)
class SPIMIBlock:
    """One completed block; frequencies are per block, not per whole document."""

    block_id: int
    postings: dict[str, dict[DocumentId, int]]
    posting_count: int
    token_count: int
    estimated_bytes: int

    def __len__(self) -> int:
        """Number of distinct terms in the block."""
        return len(self.postings)

    def postings_for(self, term: str) -> Mapping[DocumentId, int]:
        """Lookup for an already-normalized term within this block."""
        return self.postings.get(term, {})


class SPIMIBlockBuilder:
    """One-pass SPIMI builder; ``max_memory_bytes`` is a heuristic budget, not a hard limit."""

    def __init__(
        self,
        *,
        max_postings: int = 50_000,
        max_memory_bytes: int | None = None,
        preprocessor: TextPreprocessor = DEFAULT_PREPROCESSOR,
    ) -> None:
        if type(max_postings) is not int or max_postings < 1:
            raise ValueError("max_postings must be a positive integer")
        if max_memory_bytes is not None and (
            type(max_memory_bytes) is not int or max_memory_bytes < 1
        ):
            raise ValueError("max_memory_bytes must be a positive integer")
        if not isinstance(preprocessor, TextPreprocessor):
            raise TypeError("preprocessor must be a TextPreprocessor")

        self.max_postings = max_postings
        self.max_memory_bytes = max_memory_bytes
        self.preprocessor = preprocessor

    @staticmethod
    def _entry_bytes(term: str, doc_id: DocumentId, new_term: bool) -> int:
        size = 80 + sys.getsizeof(doc_id)
        if new_term:
            size += 112 + sys.getsizeof(term)
        return size

    @staticmethod
    def _seal(
        block_id: int,
        postings: dict[str, dict[DocumentId, int]],
        posting_count: int,
        token_count: int,
        estimated_bytes: int,
    ) -> SPIMIBlock:
        # SPIMI sorts its dictionary once per completed block. Posting maps
        # are reused instead of copied to limit transient memory use.
        return SPIMIBlock(
            block_id=block_id,
            postings=dict(sorted(postings.items())),
            posting_count=posting_count,
            token_count=token_count,
            estimated_bytes=estimated_bytes,
        )

    def iter_blocks(
        self, documents: Iterable[tuple[DocumentId, object]],
    ) -> Iterator[SPIMIBlock]:
        """Yield blocks lazily; pairs repeated across blocks are merged later."""
        postings: dict[str, dict[DocumentId, int]] = {}
        posting_count = 0
        token_count = 0
        estimated_bytes = 0
        block_id = 0

        for doc_id, text in documents:
            try:
                hash(doc_id)
            except TypeError:
                raise TypeError("doc_id must be hashable") from None

            for term in self.preprocessor.iter_tokens(text):
                docs = postings.get(term)
                new_term = docs is None
                new_posting = new_term or doc_id not in docs

                if new_posting:
                    added_bytes = self._entry_bytes(term, doc_id, new_term)
                    at_capacity = posting_count >= self.max_postings
                    over_budget = (
                        self.max_memory_bytes is not None
                        and estimated_bytes + added_bytes > self.max_memory_bytes
                    )

                    # Flush *before* inserting a new posting. An existing pair
                    # can keep accumulating TF without growing the dictionary.
                    if posting_count and (at_capacity or over_budget):
                        completed = self._seal(
                            block_id, postings, posting_count,
                            token_count, estimated_bytes,
                        )
                        block_id += 1
                        postings = {}
                        posting_count = 0
                        token_count = 0
                        estimated_bytes = 0
                        docs = None
                        added_bytes = self._entry_bytes(term, doc_id, True)
                        yield completed

                    if docs is None:
                        docs = {}
                        postings[term] = docs
                    docs[doc_id] = 1
                    posting_count += 1
                    estimated_bytes += added_bytes
                else:
                    docs[doc_id] += 1

                token_count += 1

        if posting_count:
            yield self._seal(
                block_id, postings, posting_count, token_count, estimated_bytes,
            )
