"""Pruebas de ejecución de MATCH (Parte 3, issues #57, #58, #59 y #60).

Cubren BM25, TF-IDF + coseno, SCORE() como columna, ORDER BY sobre el alias y
LIMIT. El tokenizador es provisional hasta el pipeline de SPIMI (#44-#48).
"""

import os
import shutil
import unittest
import uuid

from query.catalog import Catalog
from query.query_executor import QueryExecutor
from query.text_queries import TextQueryError, tokenize


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _temp_dir(prefix):
    base = os.environ.get("BD2_TEST_DIR") or os.path.join(_REPO_ROOT, ".bd2-tests")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"{prefix}{uuid.uuid4().hex}")
    os.makedirs(path)
    return path


class _Engine:
    def __init__(self, directory):
        self.catalog = Catalog(data_dir=directory)
        self._executor = QueryExecutor(self.catalog)

    def run(self, sql):
        return self._executor.execute(sql)

    def create_table(self, name, columns, primary_key="id"):
        return self.catalog.create_table(
            name, columns, primary_key=primary_key, primary_key_index=False
        )


class TestTokenize(unittest.TestCase):
    def test_minusculas_y_signos(self):
        self.assertEqual(tokenize("Base de DATOS, relacional!"), ["base", "de", "datos", "relacional"])

    def test_acentos(self):
        self.assertEqual(tokenize("Programación en PYTHON"), ["programación", "en", "python"])

    def test_vacio(self):
        self.assertEqual(tokenize(None), [])


class TestEjecucionTextual(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-text-")
        self.engine = _Engine(self._dir)
        self.engine.create_table("documentos", [("id", "INT"), ("contenido", "VARCHAR(200)")])
        documentos = (
            (1, "base de datos vectorial"),
            (2, "machine learning"),
            (3, "base de datos"),
        )
        for doc_id, contenido in documentos:
            self.engine.run(f"INSERT INTO documentos VALUES ({doc_id}, '{contenido}')")

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def ids(self, result):
        return [row["id"] for row in result.rows]

    def test_bm25(self):
        resultado = self.engine.run(
            "SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos') USING BM25"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(set(self.ids(resultado)), {1, 3})
        scores = [row["_score"] for row in resultado.rows]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(resultado.execution_plan["access_path"], "TEXT_BM25")
        self.assertEqual(resultado.execution_plan["used_indexes"], ["contenido"])

    def test_tf_idf(self):
        resultado = self.engine.run(
            "SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos') USING TF_IDF"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(set(self.ids(resultado)), {1, 3})
        self.assertEqual(resultado.execution_plan["access_path"], "TEXT_TF_IDF")

    def test_score_como_columna(self):
        resultado = self.engine.run(
            "SELECT *, SCORE() as relevancia FROM documentos "
            "WHERE MATCH(contenido, 'machine learning') USING BM25"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(self.ids(resultado), [2])
        self.assertIn("relevancia", resultado.columns)
        self.assertGreater(resultado.rows[0]["relevancia"], 0)

    def test_order_by_score_y_limit(self):
        resultado = self.engine.run(
            "SELECT id, SCORE() as relevancia FROM documentos "
            "WHERE MATCH(contenido, 'base de datos') USING TF_IDF "
            "ORDER BY relevancia DESC LIMIT 1"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(len(resultado.rows), 1)
        self.assertEqual(resultado.rows[0]["id"], 3)
        self.assertEqual(resultado.columns, ["id", "relevancia"])

    def test_columna_inexistente(self):
        resultado = self.engine.run(
            "SELECT * FROM documentos WHERE MATCH(no_existe, 'texto') USING BM25"
        )
        self.assertFalse(resultado.success)
        self.assertIn("no existe", resultado.error or "")

    def test_texto_sin_terminos_utiles(self):
        resultado = self.engine.run(
            "SELECT * FROM documentos WHERE MATCH(contenido, '!!!') USING BM25"
        )
        self.assertFalse(resultado.success)
        self.assertIn("término", resultado.error or "")


class TestTablaVacia(unittest.TestCase):
    def test_error_claro(self):
        directory = _temp_dir("bd2-text-")
        try:
            engine = _Engine(directory)
            engine.create_table("documentos", [("id", "INT"), ("contenido", "VARCHAR(200)")])
            resultado = engine.run(
                "SELECT * FROM documentos WHERE MATCH(contenido, 'hola') USING BM25"
            )
            self.assertFalse(resultado.success)
            self.assertIn("vacía", resultado.error or "")
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
