"""Persistent, streaming SPIMI block files (issue #46).

Each block is a UTF-8 JSON Lines file with one posting per line::

    {"t":"base","d":1,"f":2}

Records are sorted by ``(term, document_id)``. This format deliberately does
not put an entire posting list on one line: a subsequent k-way external merge
can read and combine records without loading large posting lists into RAM.
Only integer and string document IDs are persistable; pickle is not used.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Iterator, TypeAlias

from .spimi import SPIMIBlock

DiskDocumentId: TypeAlias = int | str
PostingRecord: TypeAlias = tuple[str, DiskDocumentId, int]


def document_id_sort_key(doc_id: DiskDocumentId) -> tuple[int, int | str]:
    """A stable total order even when IDs mix integers and strings."""
    if type(doc_id) is int:
        return (0, doc_id)
    if type(doc_id) is str:
        return (1, doc_id)
    raise TypeError("persistent SPIMI document IDs must be int or str")


def _validate_record(term: object, doc_id: object, frequency: object) -> None:
    if not isinstance(term, str) or not term:
        raise ValueError("posting term must be a nonempty string")
    document_id_sort_key(doc_id)
    if type(frequency) is not int or frequency < 1:
        raise ValueError("posting frequency must be a positive integer")


def iter_block_records(path: str | Path) -> Iterator[PostingRecord]:
    """Stream validated postings from an already-written SPIMI block.

    Detects malformed records, duplicate pairs and unexpected ordering, so
    the external merge never silently incorporates a corrupted block.
    """
    previous_key: tuple[str, tuple[int, int | str]] | None = None
    with Path(path).open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                item = json.loads(line)
                if not isinstance(item, dict) or set(item) != {"t", "d", "f"}:
                    raise ValueError("expected keys t, d, f")
                term, doc_id, frequency = item["t"], item["d"], item["f"]
                _validate_record(term, doc_id, frequency)
                key = (term, document_id_sort_key(doc_id))
                if previous_key is not None and key <= previous_key:
                    raise ValueError("records must be strictly sorted")
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"invalid SPIMI block {path!s} at line {line_number}: {exc}"
                ) from exc
            previous_key = key
            yield term, doc_id, frequency


class SPIMIBlockStore:
    """Write SPIMI blocks atomically, with one block file per identifier.

    The caller should consume :meth:`write_blocks` incrementally; keeping a
    list of every block in memory would defeat the SPIMI memory budget.
    Existing block files are not intentionally overwritten.
    """

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, block_id: int) -> Path:
        if type(block_id) is not int or block_id < 0:
            raise ValueError("block_id must be a nonnegative integer")
        return self.directory / f"block_{block_id:06d}.spimi.jsonl"

    def write_block(self, block: SPIMIBlock) -> Path:
        """Write a sorted block through a temporary file, then publish it.

        ``flush`` and ``fsync`` complete before the final rename, avoiding a
        partially written destination if serialization fails. This assumes a
        single writer per directory; it does not coordinate processes.
        """
        if not isinstance(block, SPIMIBlock):
            raise TypeError("block must be a SPIMIBlock")
        destination = self.path_for(block.block_id)
        if destination.exists():
            raise FileExistsError(destination)

        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", delete=False,
                prefix=".spimi-", suffix=".tmp", dir=self.directory,
            ) as stream:
                temporary = Path(stream.name)
                for term in sorted(block.postings):
                    for doc_id, frequency in sorted(
                        block.postings[term].items(),
                        key=lambda pair: document_id_sort_key(pair[0]),
                    ):
                        _validate_record(term, doc_id, frequency)
                        stream.write(json.dumps(
                            {"t": term, "d": doc_id, "f": frequency},
                            ensure_ascii=False, separators=(",", ":"),
                        ))
                        stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())

            # Guard against an existing file in normal single-writer usage.
            if destination.exists():
                raise FileExistsError(destination)
            os.replace(temporary, destination)
            temporary = None
            return destination
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def write_blocks(self, blocks: Iterable[SPIMIBlock]) -> Iterator[Path]:
        """Persist blocks lazily; yield each resulting filename."""
        for block in blocks:
            yield self.write_block(block)
