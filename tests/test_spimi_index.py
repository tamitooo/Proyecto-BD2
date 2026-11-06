"""Indexed disk term lookup — issues #48 and #72."""

import json

import pytest

from text.preprocessing import TextPreprocessor
from text.spimi import SPIMIBlockBuilder
from text.spimi_index import SPIMIInvertedIndex
from text.spimi_merge import merge_spimi_blocks
from text.spimi_storage import SPIMIBlockStore
from text.statistics import BM25Statistics


def _index(tmp_path, documents, *, preprocessor=None, capacity=2):
    builder = SPIMIBlockBuilder(
        max_postings=capacity,
        preprocessor=preprocessor or TextPreprocessor(),
    )
    store = SPIMIBlockStore(tmp_path / "blocks")
    paths = store.write_blocks(builder.iter_blocks(documents))
    result = merge_spimi_blocks(paths, tmp_path / "index", max_open_files=2)
    return SPIMIInvertedIndex(result.directory, preprocessor=builder.preprocessor)


def test_lookup_normalizes_and_reads_only_requested_postings(tmp_path):
    index = _index(tmp_path, [
        (10, "BASE base datos"),
        (2, "base índice"),
        ("audio", "sonido datos"),
    ], capacity=1)

    assert index.search_term("bAsE") == {2: 1, 10: 2}
    assert index.search_term("ÍNDICE") == {2: 1}
    assert index.lookup("sonido") == {"audio": 1}
    assert index.document_frequency("BASE") == 2
    assert index.document_frequency("desconocido") == 0
    assert index.vocabulary_size == 4


def test_absent_or_multiple_terms_are_not_a_term_lookup(tmp_path):
    index = _index(tmp_path, [(1, "python base")])
    assert index.search_term("missing") == {}
    assert index.search_term("!!!") == {}
    assert index.search_term(None) == {}
    assert index.search_term("python base") == {}


def test_unicode_byte_offsets_and_custom_preprocessor(tmp_path):
    processor = TextPreprocessor(stopwords={"de"}, strip_accents=True)
    index = _index(tmp_path, [(1, "CAFÉ de NIÑEZ"), (2, "Café")],
                   preprocessor=processor, capacity=1)
    assert index.lookup("CAFÉ") == {1: 1, 2: 1}
    assert index.lookup("niñez") == {1: 1}
    assert index.lookup("de") == {}


def test_empty_index_is_valid(tmp_path):
    index = _index(tmp_path, [(1, "!!!"), (2, None)])
    assert index.vocabulary_size == 0
    assert index.search_term("anything") == {}


def test_disk_index_matches_existing_bm25_statistics(tmp_path):
    documents = {
        1: "base base datos",
        2: "datos índices",
        3: "base índices índices",
    }
    processor = TextPreprocessor()
    stats = BM25Statistics.from_documents({
        doc_id: processor.tokenize(value) for doc_id, value in documents.items()
    })
    index = _index(tmp_path, documents.items(), capacity=1)

    for term in ("base", "datos", "índices"):
        expected = {
            doc_id: stats.term_frequency(term, doc_id)
            for doc_id in stats.documents_for_term(term)
        }
        assert index.lookup(term) == expected
        assert index.document_frequency(term) == stats.document_frequency(term)


def test_reject_invalid_preprocessor(tmp_path):
    with pytest.raises(TypeError, match="preprocessor"):
        SPIMIInvertedIndex(tmp_path, preprocessor=None)


def test_missing_postings_file(tmp_path):
    path = tmp_path / "index"
    path.mkdir()
    with pytest.raises(FileNotFoundError):
        SPIMIInvertedIndex(path)


def test_corrupt_lexicon_is_rejected(tmp_path):
    index = _index(tmp_path, [(1, "base datos")])
    lexicon = index.lexicon_path
    lines = lexicon.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines]
    entries[1]["o"] = 0  # second term cannot point to first term's offset
    lexicon.write_text(
        "\n".join(json.dumps(item) for item in entries) + "\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="lexicon"):
        SPIMIInvertedIndex(index.directory)


def test_corrupt_posting_is_detected_on_lookup(tmp_path):
    index = _index(tmp_path, [(1, "base")])
    index.postings_path.write_bytes(b'{"t":"other","d":1,"f":1}\n')
    with pytest.raises(ValueError, match="different term"):
        index.lookup("base")
