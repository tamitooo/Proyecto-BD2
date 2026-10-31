import math

import pytest

from text import BM25Statistics, TFIDFWeighter


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
