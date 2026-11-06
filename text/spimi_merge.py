"""Bounded fan-in external merging of SPIMI blocks (issue #47).

All input files contain sorted posting records from ``spimi_storage``. A
k-way merge combines repeated (term, doc_id) pairs by summing TF, including
the case where one long document was split across multiple memory blocks.
Intermediate passes limit open files to ``max_open_files``. The final index
and offset lexicon are published together by renaming a completed directory.
"""

from __future__ import annotations

import heapq
import json
import os
import shutil
import tempfile
from contextlib import nullcontext
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import Iterable, Iterator

from .spimi_storage import (
    PostingRecord,
    document_id_sort_key,
    iter_block_records,
)

POSTINGS_FILENAME = "inverted.spimi.jsonl"
LEXICON_FILENAME = "lexicon.spimi.jsonl"


@dataclass(frozen=True, slots=True)
class SPIMIIndexPaths:
    directory: Path
    postings_path: Path
    lexicon_path: Path
    term_count: int
    posting_count: int


def _record_key(record: PostingRecord):
    return (record[0], document_id_sort_key(record[1]))


def _merged_postings(paths: list[Path]) -> Iterator[PostingRecord]:
    """Merge sorted runs using O(number of inputs) heap memory."""
    sources = [iter_block_records(path) for path in paths]
    try:
        records = heapq.merge(*sources, key=_record_key)
        for _, group in groupby(records, key=_record_key):
            first = next(group)
            term, doc_id, frequency = first
            frequency += sum(record[2] for record in group)
            yield term, doc_id, frequency
    finally:
        for source in sources:
            source.close()


def _encode(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _write_run(
    paths: list[Path], output_path: Path, lexicon_path: Path | None = None,
) -> tuple[int, int]:
    """Stream a merged run, optionally emitting term-to-byte-offset entries."""
    term_count = posting_count = 0
    current_term: str | None = None
    term_offset = document_frequency = 0

    lexicon_context = (
        lexicon_path.open("wb") if lexicon_path is not None else nullcontext(None)
    )
    with output_path.open("wb") as output, lexicon_context as lexicon:
        for term, doc_id, frequency in _merged_postings(paths):
            if term != current_term:
                if lexicon is not None and current_term is not None:
                    lexicon.write(_encode({
                        "t": current_term, "o": term_offset, "df": document_frequency,
                    }))
                current_term = term
                term_offset = output.tell()
                document_frequency = 0
                term_count += 1

            output.write(_encode({"t": term, "d": doc_id, "f": frequency}))
            document_frequency += 1
            posting_count += 1

        if lexicon is not None and current_term is not None:
            lexicon.write(_encode({
                "t": current_term, "o": term_offset, "df": document_frequency,
            }))
        output.flush()
        os.fsync(output.fileno())
        if lexicon is not None:
            lexicon.flush()
            os.fsync(lexicon.fileno())
    return term_count, posting_count


def merge_spimi_blocks(
    block_paths: Iterable[str | Path],
    output_directory: str | Path,
    *,
    max_open_files: int = 32,
) -> SPIMIIndexPaths:
    """Merge all block files without accumulating posting lists in memory.

    Original blocks are never removed. ``output_directory`` must not exist,
    so a prior index cannot be silently overwritten. A completed directory
    contains a sorted postings file and a compact offset lexicon for #48.
    """
    if type(max_open_files) is not int or max_open_files < 2:
        raise ValueError("max_open_files must be an integer >= 2")

    inputs = [Path(path).resolve() for path in block_paths]
    if len(inputs) != len(set(inputs)):
        raise ValueError("block paths must not be repeated")
    for path in inputs:
        if not path.is_file():
            raise FileNotFoundError(path)

    destination = Path(output_directory)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(
        dir=destination.parent, prefix=f".{destination.name}.building-",
    ))

    try:
        run_directory = temporary / ".runs"
        run_directory.mkdir()
        runs = inputs
        pass_number = 0

        while len(runs) > max_open_files:
            next_runs = []
            for offset in range(0, len(runs), max_open_files):
                batch = runs[offset:offset + max_open_files]
                run_path = run_directory / (
                    f"pass_{pass_number:03d}_run_{offset // max_open_files:06d}.jsonl"
                )
                _write_run(batch, run_path)
                next_runs.append(run_path)

            # Delete only generated intermediate files, never input blocks.
            for path in runs:
                if path.parent == run_directory:
                    path.unlink()
            runs = next_runs
            pass_number += 1

        term_count, posting_count = _write_run(
            runs, temporary / POSTINGS_FILENAME, temporary / LEXICON_FILENAME,
        )
        shutil.rmtree(run_directory)
        if destination.exists():
            raise FileExistsError(destination)
        os.rename(temporary, destination)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise

    return SPIMIIndexPaths(
        directory=destination,
        postings_path=destination / POSTINGS_FILENAME,
        lexicon_path=destination / LEXICON_FILENAME,
        term_count=term_count,
        posting_count=posting_count,
    )
