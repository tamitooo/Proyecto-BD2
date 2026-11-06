"""External multi-pass SPIMI merge — issues #47 and #72."""

import json

import pytest

from text.spimi import SPIMIBlockBuilder
from text.spimi_merge import merge_spimi_blocks
from text.spimi_storage import SPIMIBlockStore, iter_block_records


def _blocks(tmp_path, documents, capacity=2):
    store = SPIMIBlockStore(tmp_path / "blocks")
    return list(store.write_blocks(
        SPIMIBlockBuilder(max_postings=capacity).iter_blocks(documents)
    ))


def test_multi_pass_merge_sums_frequencies_across_blocks(tmp_path):
    paths = _blocks(tmp_path, [
        (1, "a b a c a"),
        (2, "a b"),
        (3, "á á a"),
    ], capacity=1)
    assert len(paths) > 2
    originals = {p: p.read_bytes() for p in paths}

    result = merge_spimi_blocks(paths, tmp_path / "index", max_open_files=2)
    records = list(iter_block_records(result.postings_path))

    assert records == [
        ("a", 1, 3), ("a", 2, 1), ("a", 3, 1),
        ("b", 1, 1), ("b", 2, 1),
        ("c", 1, 1),
        ("á", 3, 2),
    ]
    assert result.term_count == 4
    assert result.posting_count == 7
    assert result.lexicon_path.is_file()
    assert not (result.directory / ".runs").exists()
    assert {p: p.read_bytes() for p in paths} == originals


def test_offsets_are_byte_offsets_even_for_utf8(tmp_path):
    paths = _blocks(tmp_path, [(1, "árbol niño"), (2, "niño")], capacity=1)
    result = merge_spimi_blocks(paths, tmp_path / "index", max_open_files=2)
    lexicon = [json.loads(line) for line in result.lexicon_path.read_text(
        encoding="utf-8"
    ).splitlines()]

    assert [entry["t"] for entry in lexicon] == ["niño", "árbol"]
    with result.postings_path.open("rb") as stream:
        for entry in lexicon:
            stream.seek(entry["o"])
            assert json.loads(stream.readline())["t"] == entry["t"]
    assert [entry["df"] for entry in lexicon] == [2, 1]


def test_empty_input_creates_empty_searchable_files(tmp_path):
    result = merge_spimi_blocks([], tmp_path / "empty")
    assert result.term_count == result.posting_count == 0
    assert result.lexicon_path.read_bytes() == b""
    assert result.postings_path.read_bytes() == b""


def test_merge_refuses_existing_destination(tmp_path):
    paths = _blocks(tmp_path, [(1, "x")])
    destination = tmp_path / "index"
    destination.mkdir()
    marker = destination / "user-file.txt"
    marker.write_text("keep me", encoding="utf-8")
    with pytest.raises(FileExistsError):
        merge_spimi_blocks(paths, destination)
    assert marker.read_text(encoding="utf-8") == "keep me"


def test_duplicate_sources_are_rejected(tmp_path):
    path, = _blocks(tmp_path, [(1, "x")])
    with pytest.raises(ValueError, match="repeated"):
        merge_spimi_blocks([path, path], tmp_path / "index")


def test_bad_source_leaves_no_partial_destination(tmp_path):
    bad_path = tmp_path / "bad.jsonl"
    bad_path.write_text("not json\n", encoding="utf-8")
    destination = tmp_path / "index"
    with pytest.raises(ValueError, match="invalid SPIMI block"):
        merge_spimi_blocks([bad_path], destination)
    assert not destination.exists()
    assert bad_path.read_text(encoding="utf-8") == "not json\n"


@pytest.mark.parametrize("value", [0, 1, -1, True])
def test_invalid_fan_in(value, tmp_path):
    with pytest.raises(ValueError, match="max_open_files"):
        merge_spimi_blocks([], tmp_path / "unused", max_open_files=value)


def test_many_runs_merge_without_unbounded_file_descriptors(tmp_path):
    paths = _blocks(
        tmp_path,
        ((i, f"common t{i % 11}") for i in range(300)),
        capacity=1,
    )
    result = merge_spimi_blocks(paths, tmp_path / "index", max_open_files=3)
    assert result.posting_count == 600
    assert result.term_count == 12
    assert len(list(iter_block_records(result.postings_path))) == 600
