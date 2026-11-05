"""In-memory SPIMI block construction — issues #45 and #72."""

from collections import Counter
from random import Random

import pytest

from text import SPIMIBlockBuilder, TextPreprocessor


def _merged_frequencies(blocks):
    """Test oracle for #47; duplicate pairs must be summed at merge time."""
    merged = Counter()
    for block in blocks:
        for term, docs in block.postings.items():
            for doc_id, frequency in docs.items():
                merged[(term, doc_id)] += frequency
    return merged


def test_single_block_counts_terms_and_sorts_dictionary():
    blocks = list(SPIMIBlockBuilder().iter_blocks([
        (3, "Zebra ÁRBOL zebra"),
        (7, "árbol casa"),
    ]))

    assert len(blocks) == 1
    block = blocks[0]
    assert block.block_id == 0
    assert list(block.postings) == sorted(block.postings)
    assert block.postings == {
        "casa": {7: 1},
        "zebra": {3: 2},
        "árbol": {3: 1, 7: 1},
    }
    assert block.posting_count == 4
    assert block.token_count == 5
    assert block.estimated_bytes > 0
    assert len(block) == 3
    assert block.postings_for("absent") == {}


def test_capacity_splits_mid_document_without_losing_frequencies():
    blocks = list(SPIMIBlockBuilder(max_postings=2).iter_blocks([
        (1, "a a b c a"),
        (2, "a b"),
    ]))

    assert len(blocks) == 3
    assert [block.block_id for block in blocks] == [0, 1, 2]
    assert all(0 < block.posting_count <= 2 for block in blocks)
    assert sum(block.token_count for block in blocks) == 7
    assert _merged_frequencies(blocks) == Counter({
        ("a", 1): 3,
        ("b", 1): 1,
        ("c", 1): 1,
        ("a", 2): 1,
        ("b", 2): 1,
    })


def test_existing_posting_accumulates_tf_without_forcing_flush():
    blocks = list(SPIMIBlockBuilder(max_postings=1).iter_blocks([
        (1, "a a a a b b"),
    ]))

    assert [block.postings for block in blocks] == [
        {"a": {1: 4}},
        {"b": {1: 2}},
    ]


def test_empty_documents_do_not_create_empty_blocks():
    builder = SPIMIBlockBuilder()
    assert list(builder.iter_blocks([])) == []
    assert list(builder.iter_blocks([(1, None), (2, "!!!")])) == []


def test_configurable_preprocessor_is_shared():
    processor = TextPreprocessor(stopwords={"de"}, strip_accents=True)
    builder = SPIMIBlockBuilder(preprocessor=processor)

    block, = builder.iter_blocks([(1, "CAFÉ de NIÑEZ")])
    assert block.postings == {"cafe": {1: 1}, "ninez": {1: 1}}


def test_repeated_id_can_represent_document_fragments():
    blocks = list(SPIMIBlockBuilder(max_postings=1).iter_blocks([
        (42, "dato dato"),
        (42, "dato índice"),
    ]))
    assert _merged_frequencies(blocks) == Counter({
        ("dato", 42): 3,
        ("índice", 42): 1,
    })


def test_one_oversized_posting_is_still_emitted():
    blocks = list(SPIMIBlockBuilder(max_memory_bytes=1).iter_blocks([
        ("doc", "a a b"),
    ]))

    assert len(blocks) == 2
    assert blocks[0].postings == {"a": {"doc": 2}}
    assert blocks[1].postings == {"b": {"doc": 1}}
    assert all(block.estimated_bytes > 1 for block in blocks)


def test_input_is_lazy_and_does_not_load_corpus_first():
    visited = []

    def documents():
        visited.append(1)
        yield 1, "a b"
        visited.append(2)
        yield 2, "c"

    iterator = SPIMIBlockBuilder(max_postings=1).iter_blocks(documents())
    assert visited == []
    assert next(iterator).postings == {"a": {1: 1}}
    assert visited == [1]
    assert sum(block.token_count for block in iterator) == 2
    assert visited == [1, 2]


def test_large_generator_has_bounded_block_postings():
    builder = SPIMIBlockBuilder(max_postings=13)
    documents = ((i, f"t{i % 7}") for i in range(1000))

    total_postings = 0
    total_tokens = 0
    for block in builder.iter_blocks(documents):
        assert 1 <= block.posting_count <= 13
        total_postings += block.posting_count
        total_tokens += block.token_count
    assert total_postings == total_tokens == 1000


@pytest.mark.parametrize("max_postings", [1, 2, 5, 17])
def test_randomized_blocks_match_reference_counter(max_postings):
    rng = Random(2026)
    vocabulary = ["datos", "índice", "árbol", "python", "audio"]
    documents = [
        (doc_id, " ".join(rng.choice(vocabulary) for _ in range(31)))
        for doc_id in range(40)
    ]
    expected = Counter()
    for doc_id, value in documents:
        for term in TextPreprocessor().iter_tokens(value):
            expected[(term, doc_id)] += 1

    blocks = SPIMIBlockBuilder(max_postings=max_postings).iter_blocks(documents)
    actual = Counter()
    for block in blocks:
        assert 1 <= block.posting_count <= max_postings
        assert list(block.postings) == sorted(block.postings)
        for term, docs in block.postings.items():
            for doc_id, frequency in docs.items():
                actual[(term, doc_id)] += frequency
    assert actual == expected


def test_heuristic_budget_with_single_posting_exception():
    budget = 512
    blocks = SPIMIBlockBuilder(max_memory_bytes=budget).iter_blocks([
        (doc_id, "alpha beta gamma") for doc_id in range(30)
    ])
    for block in blocks:
        assert block.estimated_bytes <= budget or block.posting_count == 1


def test_builder_does_not_retain_state_between_runs():
    builder = SPIMIBlockBuilder(max_postings=1)
    documents = [(1, "a b")]
    first = list(builder.iter_blocks(documents))
    second = list(builder.iter_blocks(documents))
    assert first == second
    assert [block.block_id for block in second] == [0, 1]


@pytest.mark.parametrize("value", [0, -1, True, 2.5])
def test_invalid_posting_limit(value):
    with pytest.raises(ValueError, match="max_postings"):
        SPIMIBlockBuilder(max_postings=value)


@pytest.mark.parametrize("value", [0, -10, True, 2.5])
def test_invalid_byte_budget(value):
    with pytest.raises(ValueError, match="max_memory_bytes"):
        SPIMIBlockBuilder(max_memory_bytes=value)


def test_invalid_preprocessor():
    with pytest.raises(TypeError, match="preprocessor"):
        SPIMIBlockBuilder(preprocessor=None)


def test_unhashable_document_id():
    builder = SPIMIBlockBuilder()
    with pytest.raises(TypeError, match="hashable"):
        list(builder.iter_blocks([([], "hello")]))
