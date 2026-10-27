import pytest

from text.statistics import BM25Statistics


def corpus():
    # Tokens deliberadamente ya preprocesados: este módulo no tokeniza.
    return {
        1: ["base", "dato", "vectorial", "base"],
        2: ["base", "dato", "relacional"],
        3: ["indice", "vectorial"],
        4: [],
    }


def test_calcula_tf_df_longitudes_n_y_avgdl():
    stats = BM25Statistics.from_documents(corpus())

    assert stats.document_count == 4
    assert len(stats) == 4

    assert stats.term_frequency("base", 1) == 2
    assert stats.term_frequency("vectorial", 1) == 1
    assert stats.term_frequency("base", 3) == 0
    assert stats.term_frequency("inexistente", 1) == 0
    assert stats.term_frequency("base", 999) == 0

    assert stats.document_frequency("base") == 2
    assert stats.document_frequency("dato") == 2
    assert stats.document_frequency("vectorial") == 2
    assert stats.document_frequency("indice") == 1
    assert stats.document_frequency("inexistente") == 0

    assert stats.document_length(1) == 4
    assert stats.document_length(2) == 3
    assert stats.document_length(3) == 2
    assert stats.document_length(4) == 0
    assert stats.average_document_length == pytest.approx(9 / 4)


def test_documento_duplicado_no_corrompe_estadisticas():
    stats = BM25Statistics()
    stats.add_document("d1", ["a", "a", "b"])

    with pytest.raises(ValueError, match="already registered"):
        stats.add_document("d1", ["otro"])

    assert stats.document_count == 1
    assert stats.document_frequency("a") == 1
    assert stats.term_frequency("a", "d1") == 2
    assert stats.average_document_length == 3


def test_remove_document_actualiza_df_y_avgdl():
    stats = BM25Statistics.from_documents(
        {
            1: ["base", "base", "dato"],
            2: ["base", "indice"],
        }
    )

    assert stats.remove_document(1) is True
    assert stats.document_count == 1
    assert stats.document_frequency("base") == 1
    assert stats.document_frequency("dato") == 0
    assert stats.average_document_length == 2
    assert stats.remove_document(999) is False


def test_document_length_desconocido_es_error_claro():
    stats = BM25Statistics()
    with pytest.raises(KeyError, match="unknown document"):
        stats.document_length("missing")


def test_documento_vacio_cuenta_en_n_y_avgdl():
    stats = BM25Statistics()
    stats.add_document(1, [])
    stats.add_document(2, ["uno", "dos"])

    assert stats.document_count == 2
    assert stats.document_length(1) == 0
    assert stats.average_document_length == 1.0


def test_clear_reinicia_todas_las_estadisticas():
    stats = BM25Statistics.from_documents(corpus())
    stats.clear()

    assert stats.document_count == 0
    assert stats.average_document_length == 0.0
    assert stats.document_frequency("base") == 0
    assert stats.term_frequency("base", 1) == 0
