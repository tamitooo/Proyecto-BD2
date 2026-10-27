import math

import pytest

from text.bm25 import BM25Ranker
from text.statistics import BM25Statistics


def build_stats():
    return BM25Statistics.from_documents(
        {
            1: ["base", "base", "dato", "vectorial"],
            2: ["base", "dato", "relacional"],
            3: ["indice", "vectorial"],
            4: [],
        }
    )


def manual_idf(n, df):
    return math.log(1.0 + (n - df + 0.5) / (df + 0.5))


def manual_term_score(tf, doc_len, avgdl, n, df, k1=1.2, b=0.75):
    idf = manual_idf(n, df)
    return idf * (
        tf * (k1 + 1.0)
        / (tf + k1 * (1.0 - b + b * doc_len / avgdl))
    )


def test_idf_coincide_con_formula_manual():
    stats = build_stats()
    ranker = BM25Ranker(stats)

    assert ranker.idf("base") == pytest.approx(manual_idf(4, 2))
    assert ranker.idf("indice") == pytest.approx(manual_idf(4, 1))
    assert ranker.idf("inexistente") == 0.0


def test_term_score_coincide_con_calculo_manual():
    stats = build_stats()
    ranker = BM25Ranker(stats, k1=1.2, b=0.75)

    expected = manual_term_score(
        tf=2,
        doc_len=4,
        avgdl=stats.average_document_length,
        n=4,
        df=2,
        k1=1.2,
        b=0.75,
    )
    assert ranker.term_score("base", 1) == pytest.approx(expected)


def test_score_multitermino_es_suma_de_aportes():
    stats = build_stats()
    ranker = BM25Ranker(stats)

    expected = ranker.term_score("base", 1) + ranker.term_score("vectorial", 1)
    assert ranker.score(1, ["base", "vectorial"]) == pytest.approx(expected)


def test_tf_mayor_incrementa_score_pero_con_saturacion():
    stats = BM25Statistics.from_documents(
        {
            1: ["x", "a", "b", "c"],
            2: ["x", "x", "a", "b"],
            3: ["x", "x", "x", "x"],
        }
    )
    ranker = BM25Ranker(stats, b=0.0)

    s1 = ranker.term_score("x", 1)
    s2 = ranker.term_score("x", 2)
    s3 = ranker.term_score("x", 3)

    assert s1 < s2 < s3
    assert (s3 - s2) < (s2 - s1)


def test_b_normaliza_documentos_largos():
    stats = BM25Statistics.from_documents(
        {
            1: ["x", "a"],
            2: ["x"] + ["relleno"] * 19,
        }
    )

    without_length_norm = BM25Ranker(stats, b=0.0)
    with_length_norm = BM25Ranker(stats, b=1.0)

    assert without_length_norm.term_score("x", 1) == pytest.approx(
        without_length_norm.term_score("x", 2)
    )
    assert with_length_norm.term_score("x", 1) > with_length_norm.term_score("x", 2)


def test_k1_y_b_son_configurables_y_validados():
    stats = build_stats()

    low_k1 = BM25Ranker(stats, k1=0.3, b=0.75).term_score("base", 1)
    high_k1 = BM25Ranker(stats, k1=2.0, b=0.75).term_score("base", 1)
    assert low_k1 != pytest.approx(high_k1)

    with pytest.raises(ValueError, match="k1"):
        BM25Ranker(stats, k1=0)
    with pytest.raises(ValueError, match="b"):
        BM25Ranker(stats, b=-0.1)
    with pytest.raises(ValueError, match="b"):
        BM25Ranker(stats, b=1.1)


def test_terminos_ausentes_y_consulta_vacia_no_fallan():
    stats = build_stats()
    ranker = BM25Ranker(stats)

    assert ranker.term_score("no-existe", 1) == 0.0
    assert ranker.score(1, ["no-existe"]) == 0.0
    assert ranker.score(1, []) == 0.0


def test_documento_desconocido_es_error_claro():
    ranker = BM25Ranker(build_stats())
    with pytest.raises(KeyError, match="unknown document"):
        ranker.score(999, ["base"])


def test_repeticion_en_query_suma_nuevamente_el_aporte():
    ranker = BM25Ranker(build_stats())
    one = ranker.score(1, ["base"])
    repeated = ranker.score(1, ["base", "base"])
    assert repeated == pytest.approx(2 * one)


def test_search_top_k_usa_candidatos_de_postings_y_ordena_descendente():
    stats = build_stats()
    ranker = BM25Ranker(stats)

    results = ranker.search(["base", "vectorial"], k=3)

    assert len(results) <= 3
    assert [score for _, score in results] == sorted(
        [score for _, score in results], reverse=True
    )
    # doc 4 está vacío y no pertenece a ninguna posting list.
    assert 4 not in [doc_id for doc_id, _ in results]


def test_search_coincide_con_ranking_exhaustivo_de_candidatos():
    stats = build_stats()
    ranker = BM25Ranker(stats)
    terms = ["base", "dato", "vectorial"]

    candidates = stats.candidate_documents(terms)
    exhaustive = sorted(
        ((doc_id, ranker.score(doc_id, terms)) for doc_id in candidates),
        key=lambda item: (-item[1], type(item[0]).__name__, repr(item[0])),
    )[:2]

    assert ranker.search(terms, k=2) == exhaustive


def test_search_k_mayor_que_candidatos_devuelve_todos():
    ranker = BM25Ranker(build_stats())
    results = ranker.search(["indice"], k=100)
    assert [doc_id for doc_id, _ in results] == [3]


def test_search_consulta_vacia_o_sin_postings_devuelve_vacio():
    ranker = BM25Ranker(build_stats())
    assert ranker.search([], k=10) == []
    assert ranker.search(["inexistente"], k=10) == []


def test_search_k_no_positivo_devuelve_vacio_y_tipo_invalido_falla():
    ranker = BM25Ranker(build_stats())
    assert ranker.search(["base"], k=0) == []
    assert ranker.search(["base"], k=-1) == []
    with pytest.raises(TypeError, match="k"):
        ranker.search(["base"], k=2.5)


def test_search_desempata_por_doc_id_de_forma_determinista():
    stats = BM25Statistics.from_documents(
        {
            2: ["x"],
            1: ["x"],
            3: ["x"],
        }
    )
    ranker = BM25Ranker(stats, b=0.0)
    results = ranker.search(["x"], k=3)
    assert [doc_id for doc_id, _ in results] == [1, 2, 3]


def test_statistics_postings_se_actualizan_al_eliminar_documento():
    stats = build_stats()
    assert stats.documents_for_term("base") == frozenset({1, 2})
    assert stats.candidate_documents(["base", "indice"]) == {1, 2, 3}

    assert stats.remove_document(2)
    assert stats.documents_for_term("base") == frozenset({1})
    assert stats.document_frequency("base") == 1
