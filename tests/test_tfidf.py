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


def test_pesos_reflejan_cambios_en_la_coleccion():
    stats = build_stats()
    weighter = TFIDFWeighter(stats)
    before = weighter.idf("base")

    stats.remove_document(2)

    assert weighter.idf("base") == pytest.approx(math.log10(3 / 1))
    assert weighter.idf("base") > before
