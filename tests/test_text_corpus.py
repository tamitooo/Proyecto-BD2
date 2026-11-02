import json

from benchmarks.text_corpus import DOCS_RESPUESTA, escribir
from benchmarks.text_queries import construir_consultas


def test_banco_respeta_los_grupos():
    banco = construir_consultas()
    assert len(banco) == 36
    assert all(q["n_palabras"] == 1 for q in banco if q["grupo"] == "una")
    assert all(q["n_palabras"] == 3 for q in banco if q["grupo"] == "tres")
    assert all(q["n_palabras"] >= 5 for q in banco if q["grupo"] == "larga")


def test_misma_semilla_mismo_corpus(tmp_path):
    uno = escribir(500, tmp_path / "a", semilla=7)
    otro = escribir(500, tmp_path / "b", semilla=7)
    assert uno["corpus"].read_text(encoding="utf-8") == otro["corpus"].read_text(encoding="utf-8")
    assert uno["bytes"] == otro["bytes"]


def test_relevantes_contienen_todos_los_terminos(tmp_path):
    salida = escribir(500, tmp_path / "c")
    textos = {}
    for linea in salida["corpus"].read_text(encoding="utf-8").splitlines():
        doc = json.loads(linea)
        textos[doc["id"]] = set(doc["texto"].split())

    banco = json.loads(salida["queries"].read_text(encoding="utf-8"))
    for consulta in banco["consultas"]:
        assert len(consulta["relevantes"]) == DOCS_RESPUESTA
        for posicion in consulta["relevantes"]:
            assert set(consulta["terminos"]) <= textos[posicion]


def test_pocos_documentos_es_error(tmp_path):
    try:
        escribir(100, tmp_path / "d")
    except ValueError as error:
        assert "documentos" in str(error)
    else:
        raise AssertionError("se esperaba ValueError")
