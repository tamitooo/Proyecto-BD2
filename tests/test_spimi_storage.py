"""Tests for SPIMI disk blocks (issues #46 and #72)."""

import json
from collections import Counter

import pytest

from text.spimi import SPIMIBlock, SPIMIBlockBuilder
from text.spimi_storage import (
    SPIMIBlockStore,
    document_id_sort_key,
    iter_block_records,
)


def test_roundtrip_preserves_unicode_frequencies_and_id_types(tmp_path):
    builder = SPIMIBlockBuilder()
    block, = builder.iter_blocks([
        (12, "Árbol base base"),
        (2, "árbol"),
        ("doc-A", "base niño"),
    ])
    store = SPIMIBlockStore(tmp_path)
    path = store.write_block(block)

    assert path.name == "block_000000.spimi.jsonl"
    assert path.read_bytes().endswith(b"\n")
    assert list(iter_block_records(path)) == [
        ("base", 12, 2),
        ("base", "doc-A", 1),
        ("niño", "doc-A", 1),
        ("árbol", 2, 1),
        ("árbol", 12, 1),
    ]


def test_record_format_is_json_lines_sorted_by_term_and_id(tmp_path):
    block, = SPIMIBlockBuilder().iter_blocks([
        (10, "zeta alpha"),
        (2, "alpha"),
        ("1", "alpha"),
    ])
    path = SPIMIBlockStore(tmp_path).write_block(block)
    objects = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    assert objects == [
        {"t": "alpha", "d": 2, "f": 1},
        {"t": "alpha", "d": 10, "f": 1},
        {"t": "alpha", "d": "1", "f": 1},
        {"t": "zeta", "d": 10, "f": 1},
    ]


def test_lazy_build_to_disk_pipeline(tmp_path):
    builder = SPIMIBlockBuilder(max_postings=2)
    source = ((doc_id, "a a b c") for doc_id in range(20))
    store = SPIMIBlockStore(tmp_path)
    paths = list(store.write_blocks(builder.iter_blocks(source)))
    assert len(paths) > 1
    assert [path.name for path in paths] == [
        f"block_{i:06d}.spimi.jsonl" for i in range(len(paths))
    ]

    counts = Counter()
    for path in paths:
        for term, doc_id, frequency in iter_block_records(path):
            counts[(term, doc_id)] += frequency
    for doc_id in range(20):
        assert counts[("a", doc_id)] == 2
        assert counts[("b", doc_id)] == 1
        assert counts[("c", doc_id)] == 1


def test_existing_file_is_not_overwritten(tmp_path):
    block, = SPIMIBlockBuilder().iter_blocks([(1, "base datos")])
    store = SPIMIBlockStore(tmp_path)
    path = store.write_block(block)
    before = path.read_bytes()

    with pytest.raises(FileExistsError):
        store.write_block(block)
    assert path.read_bytes() == before


def test_failed_serialization_leaves_no_partial_block_or_temp(tmp_path):
    bad = SPIMIBlock(
        block_id=0, postings={"term": {(1, 2): 1}},
        posting_count=1, token_count=1, estimated_bytes=100,
    )
    with pytest.raises(TypeError, match="int or str"):
        SPIMIBlockStore(tmp_path).write_block(bad)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("bad_frequency", [0, -1, True, 1.5])
def test_reject_invalid_frequency(tmp_path, bad_frequency):
    bad = SPIMIBlock(
        block_id=0, postings={"term": {1: bad_frequency}},
        posting_count=1, token_count=1, estimated_bytes=100,
    )
    with pytest.raises(ValueError, match="positive integer"):
        SPIMIBlockStore(tmp_path).write_block(bad)


@pytest.mark.parametrize("id_value", [None, True, 3.5, (1, 2)])
def test_reject_unsupported_disk_id(id_value):
    with pytest.raises(TypeError, match="int or str"):
        document_id_sort_key(id_value)


@pytest.mark.parametrize("invalid_lines", [
    ["not json"],
    ['{"t":"a","d":1,"f":1}', '{"t":"a","d":1,"f":2}'],
    ['{"t":"b","d":1,"f":1}', '{"t":"a","d":1,"f":1}'],
    ['{"t":"a","d":true,"f":1}'],
    ['{"term":"a","doc_id":1,"tf":1}'],
])
def test_corrupt_block_is_rejected(tmp_path, invalid_lines):
    path = tmp_path / "corrupt.spimi.jsonl"
    path.write_text("\n".join(invalid_lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid SPIMI block"):
        list(iter_block_records(path))


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        list(iter_block_records(tmp_path / "missing.spimi.jsonl"))


@pytest.mark.parametrize("bad_id", [-1, True, 1.2])
def test_invalid_block_identifier(tmp_path, bad_id):
    with pytest.raises(ValueError):
        SPIMIBlockStore(tmp_path).path_for(bad_id)
