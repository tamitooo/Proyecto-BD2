import math

import pytest

from text import (
    BM25Ranker,
    BM25Statistics,
    TFIDFRanker,
    TFIDFWeighter,
    sparse_cosine_similarity,
)
from vector import cosine_similarity


def build_stats():
    return BM25Statistics.from_documents(
        {
            1: ["base", "base", "dato", "vectorial"],
            2: ["base", "dato", "relacional"],
            3: ["indice", "vectorial"],
            4: [],
        }
    )


def test_requiere_estadisticas_validas():
    with pytest.raises(TypeError):
        TFIDFWeighter({"base": 1})


def test_tf_weight_coincide_con_formula_manual():
    assert TFIDFWeighter.term_frequency_weight(0) == 0.0
    assert TFIDFWeighter.term_frequency_weight(1) == 1.0
    assert TFIDFWeighter.term_frequency_weight(10) == pytest.approx(2.0)
    assert TFIDFWeighter.term_frequency_weight(100) == pytest.approx(3.0)


def test_tf_weight_coincide_con_los_valores_de_la_clase():
    assert TFIDFWeighter.term_frequency_weight(2) == pytest.approx(1.3, abs=0.01)
    assert TFIDFWeighter.term_frequency_weight(1000) == pytest.approx(4.0)


def test_tf_weight_rechaza_frecuencias_negativas():
    with pytest.raises(ValueError):
        TFIDFWeighter.term_frequency_weight(-1)


def test_idf_coincide_con_formula_manual():
    weighter = TFIDFWeighter(build_stats())

    assert weighter.idf("base") == pytest.approx(math.log10(4 / 2))
    assert weighter.idf("relacional") == pytest.approx(math.log10(4 / 1))


def test_idf_favorece_terminos_raros():
    weighter = TFIDFWeighter(build_stats())

    assert weighter.idf("relacional") > weighter.idf("base")


def test_idf_de_termino_inexistente_es_cero():
    assert TFIDFWeighter(build_stats()).idf("inexistente") == 0.0


def test_idf_de_termino_en_toda_la_coleccion_es_cero():
    stats = BM25Statistics.from_documents({1: ["base"], 2: ["base", "dato"]})

    assert TFIDFWeighter(stats).idf("base") == 0.0


def test_idf_en_coleccion_vacia_es_cero():
    assert TFIDFWeighter(BM25Statistics()).idf("base") == 0.0


def test_peso_coincide_con_calculo_manual():
    weighter = TFIDFWeighter(build_stats())

    expected = (1.0 + math.log10(2)) * math.log10(4 / 2)
    assert weighter.weight("base", 1) == pytest.approx(expected)


def test_peso_de_termino_ausente_del_documento_es_cero():
    assert TFIDFWeighter(build_stats()).weight("relacional", 1) == 0.0


def test_peso_en_documento_vacio_es_cero():
    assert TFIDFWeighter(build_stats()).weight("base", 4) == 0.0


def test_documento_desconocido_lanza_keyerror():
    with pytest.raises(KeyError):
        TFIDFWeighter(build_stats()).weight("base", 99)


def build_class_example():
    """Documentos de la diapositiva 52 de la semana 07, sin stopwords."""
    return TFIDFWeighter(
        BM25Statistics.from_documents(
            {
                "D1": ["cargamento", "oro", "dañado", "fuego"],
                "D2": ["entrega", "plata", "llegó", "camión", "color", "plata"],
                "D3": ["cargamento", "oro", "llegó", "camión"],
            }
        )
    )


class CollectionOfTheClassExample(BM25Statistics):
    """N y DF de la diapositiva 68, sin registrar un millón de documentos."""

    DF = {"auto": 5_000, "mejor": 50_000, "carro": 10_000, "seguro": 1_000}

    @property
    def document_count(self):
        return 1_000_000

    def document_frequency(self, term):
        return self.DF.get(term, 0)


def assert_vector(actual, expected):
    assert set(actual) == set(expected)
    for term, weight in expected.items():
        assert actual[term] == pytest.approx(weight, abs=0.0001)


def test_vector_de_documento_coincide_con_la_tabla_de_la_clase():
    weighter = build_class_example()

    assert_vector(
        weighter.document_vector("D1"),
        {"dañado": 0.4771, "fuego": 0.4771, "oro": 0.1761, "cargamento": 0.1761},
    )
    assert_vector(
        weighter.document_vector("D3"),
        {"llegó": 0.1761, "oro": 0.1761, "cargamento": 0.1761, "camión": 0.1761},
    )


def test_vector_de_documento_amortigua_terminos_repetidos():
    # La tabla de la clase usa tf crudo: plata = 2 * 0.4771 = 0.9542. Aquí se
    # aplica la variante 1 + log10(tf) de la diapositiva 68.
    weighter = build_class_example()

    assert weighter.document_vector("D2")["plata"] == pytest.approx(
        (1.0 + math.log10(2)) * math.log10(3)
    )


def test_vector_de_documento_coincide_con_peso_de_cada_termino():
    weighter = TFIDFWeighter(build_stats())

    for term, weight in weighter.document_vector(1).items():
        assert weight == pytest.approx(weighter.weight(term, 1))


def test_vector_de_consulta_coincide_con_el_ejemplo_de_la_clase():
    weighter = TFIDFWeighter(CollectionOfTheClassExample())

    assert_vector(
        weighter.query_vector(["mejor", "seguro", "carro"]),
        {"mejor": 1.301, "carro": 2.0, "seguro": 3.0},
    )


def test_vector_de_consulta_cuenta_terminos_repetidos():
    weighter = build_class_example()

    assert weighter.query_vector(["plata", "plata"])["plata"] == pytest.approx(
        (1.0 + math.log10(2)) * math.log10(3)
    )


def test_consulta_y_documento_comparten_terminos():
    weighter = build_class_example()

    assert_vector(
        weighter.query_vector(["oro", "plata", "camión"]),
        {"oro": 0.1761, "plata": 0.4771, "camión": 0.1761},
    )


def test_vector_omite_pesos_en_cero():
    stats = BM25Statistics.from_documents({1: ["base", "dato"], 2: ["base"]})
    weighter = TFIDFWeighter(stats)

    assert set(weighter.document_vector(1)) == {"dato"}
    assert set(weighter.query_vector(["base", "dato", "inexistente"])) == {"dato"}


def test_vectores_vacios():
    weighter = TFIDFWeighter(build_stats())

    assert weighter.document_vector(4) == {}
    assert weighter.query_vector([]) == {}
    assert weighter.query_vector(["inexistente"]) == {}


def test_vector_de_documento_desconocido_lanza_keyerror():
    with pytest.raises(KeyError):
        TFIDFWeighter(build_stats()).document_vector(99)


def test_consulta_rechaza_un_str_sin_tokenizar():
    with pytest.raises(TypeError):
        TFIDFWeighter(build_stats()).query_vector("base de datos")


def test_consulta_acepta_cualquier_iterable_de_terminos():
    weighter = build_class_example()

    assert weighter.query_vector(iter(["plata"])) == weighter.query_vector(["plata"])


def test_pesos_reflejan_cambios_en_la_coleccion():
    stats = build_stats()
    weighter = TFIDFWeighter(stats)
    before = weighter.idf("base")

    stats.remove_document(2)

    assert weighter.idf("base") == pytest.approx(math.log10(3 / 1))
    assert weighter.idf("base") > before


def test_coseno_coincide_con_el_ejemplo_de_la_clase():
    # Diapositiva 68: el documento va sin IDF y la consulta con TF-IDF.
    query = {"mejor": 1.3, "carro": 2.0, "seguro": 3.0}
    document = {"auto": 1.0, "carro": 1.0, "seguro": 1.3}

    assert sparse_cosine_similarity(query, document) == pytest.approx(0.8, abs=0.01)


def test_coseno_coincide_con_la_version_densa():
    first = {"a": 1.0, "b": 2.0, "c": 3.0}
    second = {"b": 4.0, "c": 0.5, "d": 2.0}

    assert sparse_cosine_similarity(first, second) == pytest.approx(
        cosine_similarity([1.0, 2.0, 3.0, 0.0], [0.0, 4.0, 0.5, 2.0])
    )


def test_coseno_de_un_vector_consigo_mismo_es_uno():
    vector = {"base": 0.3, "dato": 1.7}

    assert sparse_cosine_similarity(vector, vector) == pytest.approx(1.0)


def test_coseno_es_simetrico():
    first = {"a": 1.0, "b": 2.0, "c": 3.0}
    second = {"b": 4.0}

    assert sparse_cosine_similarity(first, second) == pytest.approx(
        sparse_cosine_similarity(second, first)
    )


def test_coseno_sin_terminos_en_comun_es_cero():
    assert sparse_cosine_similarity({"a": 1.0}, {"b": 1.0}) == 0.0


def test_coseno_con_vector_vacio_es_cero():
    assert sparse_cosine_similarity({}, {"a": 1.0}) == 0.0
    assert sparse_cosine_similarity({"a": 1.0}, {}) == 0.0
    assert sparse_cosine_similarity({}, {}) == 0.0


def test_coseno_con_vector_de_ceros_es_cero():
    assert sparse_cosine_similarity({"a": 0.0}, {"a": 1.0}) == 0.0


def test_coseno_no_depende_de_la_longitud_del_vector():
    vector = {"a": 1.0, "b": 2.0}
    scaled = {term: weight * 100 for term, weight in vector.items()}

    assert sparse_cosine_similarity(vector, scaled) == pytest.approx(1.0)


def test_coseno_con_magnitudes_extremas():
    assert sparse_cosine_similarity({"a": 1e300}, {"a": 1e300}) == pytest.approx(1.0)
    assert sparse_cosine_similarity({"a": 1e-300}, {"a": 1e-300}) == pytest.approx(1.0)


def test_coseno_rechaza_pesos_no_finitos():
    with pytest.raises(ValueError):
        sparse_cosine_similarity({"a": math.inf}, {"a": 1.0})
    with pytest.raises(ValueError):
        sparse_cosine_similarity({"a": 1.0}, {"a": math.nan})


def test_coseno_entre_consulta_y_documento_reales():
    weighter = build_class_example()
    query = weighter.query_vector(["oro", "plata", "camión"])

    scores = {
        doc_id: sparse_cosine_similarity(query, weighter.document_vector(doc_id))
        for doc_id in ("D1", "D2", "D3")
    }

    assert scores["D2"] > scores["D3"] > scores["D1"] > 0.0


def build_ranker():
    return TFIDFRanker(
        BM25Statistics.from_documents(
            {
                "D1": ["cargamento", "oro", "dañado", "fuego"],
                "D2": ["entrega", "plata", "llegó", "camión", "color", "plata"],
                "D3": ["cargamento", "oro", "llegó", "camión"],
            }
        )
    )


def test_ranking_requiere_estadisticas_validas():
    with pytest.raises(TypeError):
        TFIDFRanker({"base": 1})


def test_ranking_ordena_por_similitud_descendente():
    results = build_ranker().search(["oro", "plata", "camión"], k=3)

    assert [doc_id for doc_id, _ in results] == ["D2", "D3", "D1"]
    assert [score for _, score in results] == sorted(
        (score for _, score in results), reverse=True
    )


def test_ranking_coincide_con_el_score_de_cada_documento():
    ranker = build_ranker()
    query = ["oro", "plata", "camión"]

    for doc_id, score in ranker.search(query, k=3):
        assert score == pytest.approx(ranker.score(doc_id, query))


def test_ranking_coincide_con_fuerza_bruta():
    ranker = TFIDFRanker(build_stats())
    query = ["base", "vectorial", "relacional"]

    expected = sorted(
        (
            (doc_id, ranker.score(doc_id, query))
            for doc_id in (1, 2, 3, 4)
            if ranker.score(doc_id, query) > 0.0
        ),
        key=lambda item: -item[1],
    )

    results = ranker.search(query, k=4)

    assert [doc_id for doc_id, _ in results] == [doc_id for doc_id, _ in expected]
    for (_, score), (_, expected_score) in zip(results, expected):
        assert score == pytest.approx(expected_score)


def test_ranking_respeta_k():
    ranker = build_ranker()

    assert len(ranker.search(["oro", "plata", "camión"], k=2)) == 2
    assert len(ranker.search(["oro", "plata", "camión"], k=100)) == 3


def test_ranking_con_k_no_positivo_es_vacio():
    assert build_ranker().search(["oro"], k=0) == []
    assert build_ranker().search(["oro"], k=-1) == []


def test_ranking_rechaza_k_no_entero():
    with pytest.raises(TypeError):
        build_ranker().search(["oro"], k=1.5)


def test_ranking_rechaza_un_str_sin_tokenizar():
    with pytest.raises(TypeError):
        build_ranker().search("oro")


def test_ranking_sin_resultados():
    ranker = build_ranker()

    assert ranker.search([]) == []
    assert ranker.search(["inexistente"]) == []
    assert TFIDFRanker(BM25Statistics()).search(["oro"]) == []


def test_ranking_omite_terminos_presentes_en_toda_la_coleccion():
    stats = BM25Statistics.from_documents({1: ["base", "dato"], 2: ["base"]})

    assert [doc_id for doc_id, _ in TFIDFRanker(stats).search(["base", "dato"])] == [1]
    assert TFIDFRanker(stats).search(["base"]) == []


def test_ranking_normaliza_por_longitud():
    stats = BM25Statistics.from_documents(
        {
            "corto": ["base", "otro"],
            "largo": ["base", "uno", "dos", "tres", "cuatro", "cinco"],
            "resto": ["seis"],
        }
    )

    assert TFIDFRanker(stats).search(["base"])[0][0] == "corto"


def test_ranking_desempata_igual_que_bm25():
    stats = BM25Statistics.from_documents(
        {3: ["base", "dato"], 1: ["base", "dato"], 2: ["base", "dato"], 4: ["otro"]}
    )

    tfidf = [doc_id for doc_id, _ in TFIDFRanker(stats).search(["base"])]
    bm25 = [doc_id for doc_id, _ in BM25Ranker(stats).search(["base"])]

    assert tfidf == bm25 == [1, 2, 3]


def test_ranking_acepta_ids_heterogeneos():
    stats = BM25Statistics.from_documents(
        {1: ["base"], "a": ["base"], (2, 3): ["base"], "b": ["otro"]}
    )

    assert len(TFIDFRanker(stats).search(["base"], k=3)) == 3


def test_ranking_acepta_cualquier_iterable_de_terminos():
    ranker = build_ranker()

    assert ranker.search(iter(["oro"])) == ranker.search(["oro"])
    assert ranker.score("D1", iter(["oro"])) == ranker.score("D1", ["oro"])


def test_score_de_documento_desconocido_lanza_keyerror():
    with pytest.raises(KeyError):
        build_ranker().score("D9", ["oro"])


def assert_ranking_coincide_con_score(ranker, query):
    results = ranker.search(query, k=10)

    assert results
    for doc_id, score in results:
        assert score == pytest.approx(ranker.score(doc_id, query))


def test_ranking_refleja_documentos_eliminados():
    stats = build_stats()
    ranker = TFIDFRanker(stats)
    ranker.search(["vectorial", "base"])

    stats.remove_document(1)

    assert 1 not in [doc_id for doc_id, _ in ranker.search(["vectorial", "base"])]
    assert_ranking_coincide_con_score(ranker, ["vectorial", "base"])


def test_ranking_refleja_documentos_agregados():
    stats = build_stats()
    ranker = TFIDFRanker(stats)
    ranker.search(["vectorial"])

    stats.add_document(5, ["vectorial", "nuevo"])

    assert 5 in [doc_id for doc_id, _ in ranker.search(["vectorial"])]
    assert_ranking_coincide_con_score(ranker, ["vectorial"])


def test_ranking_detecta_reemplazo_con_la_misma_longitud():
    stats = build_stats()
    ranker = TFIDFRanker(stats)
    ranker.search(["relacional"])

    stats.remove_document(2)
    stats.add_document(2, ["relacional", "indice", "indice"])

    assert_ranking_coincide_con_score(ranker, ["relacional", "indice"])


def test_ranking_tras_vaciar_la_coleccion():
    stats = build_stats()
    ranker = TFIDFRanker(stats)
    ranker.search(["base"])

    stats.clear()

    assert ranker.search(["base"]) == []


def test_normas_solo_se_recalculan_si_la_coleccion_cambia():
    stats = build_stats()
    ranker = TFIDFRanker(stats)

    norms = ranker.document_norms()
    assert ranker.document_norms() is norms

    stats.add_document(5, ["nuevo"])
    assert ranker.document_norms() is not norms
    assert set(ranker.document_norms()) == {1, 2, 3, 4, 5}


def test_normas_coinciden_con_el_vector_de_cada_documento():
    stats = build_stats()
    ranker = TFIDFRanker(stats)
    weighter = TFIDFWeighter(stats)

    for doc_id, norm in ranker.document_norms().items():
        weights = weighter.document_vector(doc_id).values()
        assert norm == pytest.approx(math.sqrt(sum(w * w for w in weights)))
