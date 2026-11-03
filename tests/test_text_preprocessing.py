
"""Test for text preprocessing — issues #44 and #72."""

import pytest

from query.text_queries import tokenize as sql_tokenize
from text.preprocessing import TextPreprocessor, tokenize
from text.statistics import BM25Statistics

@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "Base de DATOS, relacional!",
            ["base", "de", "datos", "relacional"],
        ),
        (
            "Programación en PYTHON",
            ["programación", "en", "python"],
        ),
        (
            "Uno uno DOS",
            ["uno", "uno", "dos"],
        ),
        ("A_B-C.D", ["a", "b", "c", "d"]),
        ("!!! ___", []),
        ("", []),
        (None, []),
        (123, ["123"]),
    ],
)
def test_basic_tokenization(source, expected):
    assert tokenize(source) == expected


def test_composed_and_decomposed_accents():
    assert tokenize("CAFÉ cafe\u0301") == ["café", "café"]


def test_unicode_case_folding():
    assert tokenize("Straße") == ["strasse"]


def test_unicode_compatibility_normalization():
    assert tokenize("ＤＡＴＯＳ") == ["datos"]


def test_optional_stopwords():
    processor = TextPreprocessor(stopwords={"DE", "Y"})

    assert processor.tokenize("Base DE datos y Python") == [
        "base", "datos", "python"
    ]


def test_optional_accent_removal():
    processor = TextPreprocessor(strip_accents=True)

    assert processor.tokenize("CAFÉ NIÑEZ") == [
        "cafe", "ninez"
    ]


def test_normalized_stopwords():
    processor = TextPreprocessor(
        stopwords={"DÉ"},
        strip_accents=True,
    )

    assert processor.tokenize("de café") == ["cafe"]


def test_minimum_token_length():
    processor = TextPreprocessor(min_token_length=2)

    assert processor.tokenize("a b c++ go") == ["go"]


def test_streaming_iterator():
    processor = TextPreprocessor()

    assert list(processor.iter_tokens("uno uno dos")) == [
        "uno", "uno", "dos"
    ]


def test_optional_stemmer_interface():
    # Simple test callback; not a linguistic stemming algorithm.
    processor = TextPreprocessor(
        stemmer=lambda term: {
            "gatos": "gato"
        }.get(term, term)
    )

    assert processor.tokenize("GATOS gato") == [
        "gato", "gato"
    ]


@pytest.mark.parametrize("value", [0, -1, True])
def test_invalid_minimum_length(value):
    with pytest.raises(ValueError):
        TextPreprocessor(min_token_length=value)


def test_invalid_stopword_configuration():
    with pytest.raises(TypeError):
        TextPreprocessor(stopwords="de")


def test_invalid_stemmer_output():
    processor = TextPreprocessor(
        stemmer=lambda term: "two words"
    )

    with pytest.raises(ValueError):
        processor.tokenize("hello")


def test_sql_uses_same_tokenizer():
    assert sql_tokenize is tokenize
    assert sql_tokenize("BASE de DATOS") == [
        "base", "de", "datos"
    ]


def test_integration_with_bm25_statistics():
    documents = {
        1: tokenize("Base de datos base"),
        2: tokenize("Base relacional"),
    }

    stats = BM25Statistics.from_documents(documents)

    assert stats.document_count == 2
    assert stats.document_length(1) == 4
    assert stats.term_frequency("base", 1) == 2
    assert stats.document_frequency("base") == 2
    assert stats.documents_for_term("relacional") == frozenset({2})
