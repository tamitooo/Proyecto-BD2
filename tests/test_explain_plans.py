"""Pruebas de EXPLAIN para búsquedas textuales y vectoriales (#61 y #91).

El plan debe describir la ruta que usaría la consulta (TEXT_BM25, TEXT_TF_IDF,
HNSW_KNN o IVF_KNN) sin ejecutar la búsqueda, y con ANALYZE debe incluir las
filas y el tiempo reales.
"""

import os
import shutil
import unittest
import uuid

from query.catalog import Catalog
from query.query_executor import QueryExecutor


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
        self.catalog.create_table(name, columns, primary_key=primary_key, primary_key_index=False)


class TestExplainVectorial(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-exp-")
        self.engine = _Engine(self._dir)
        self.engine.create_table("imagenes", [("id", "INT"), ("embedding", "VARCHAR(500)")])
        for i, vector in enumerate(("[1, 0]", "[0, 1]", "[0.8, 0.6]"), start=1):
            self.engine.run(f"INSERT INTO imagenes VALUES ({i}, '{vector}')")

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_explain_hnsw(self):
        resultado = self.engine.run(
            "EXPLAIN SELECT * FROM imagenes WHERE SIMILAR_TO([1, 0], k=2) "
            "USING HNSW WITH METRIC=cosine"
        )
        self.assertTrue(resultado.success, resultado.error)
        plan = resultado.execution_plan
        self.assertEqual(plan["access_path"], "HNSW_KNN")
        self.assertEqual(plan["planner_type"], "vector_index")
        self.assertEqual(plan["used_indexes"], ["embedding"])
        self.assertEqual(plan["steps"][0]["details"]["metric"], "cosine")
        self.assertIn("HNSW_KNN", resultado.rows[0]["plan"])

    def test_explain_ivf(self):
        resultado = self.engine.run(
            "EXPLAIN SELECT * FROM imagenes WHERE SIMILAR_TO([1, 0], k=2) "
            "USING IVF WITH METRIC=euclidean"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.execution_plan["access_path"], "IVF_KNN")

    def test_explain_analyze_vectorial(self):
        resultado = self.engine.run(
            "EXPLAIN ANALYZE SELECT * FROM imagenes WHERE SIMILAR_TO([1, 0], k=2) "
            "USING HNSW WITH METRIC=cosine"
        )
        self.assertTrue(resultado.success, resultado.error)
        plan = resultado.execution_plan
        self.assertEqual(plan["access_path"], "HNSW_KNN")
        self.assertEqual(plan["analyze"]["rows"], 2)
        self.assertGreaterEqual(plan["analyze"]["execution_time_ms"], 0)


class TestExplainTextual(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-exp-")
        self.engine = _Engine(self._dir)
        self.engine.create_table("documentos", [("id", "INT"), ("contenido", "VARCHAR(200)")])
        for doc_id, contenido in ((1, "base de datos vectorial"), (2, "machine learning"), (3, "base de datos")):
            self.engine.run(f"INSERT INTO documentos VALUES ({doc_id}, '{contenido}')")

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_explain_bm25(self):
        resultado = self.engine.run(
            "EXPLAIN SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos') USING BM25"
        )
        self.assertTrue(resultado.success, resultado.error)
        plan = resultado.execution_plan
        self.assertEqual(plan["access_path"], "TEXT_BM25")
        self.assertEqual(plan["planner_type"], "text_index")
        self.assertEqual(plan["used_indexes"], ["contenido"])
        self.assertEqual(plan["steps"][0]["details"]["documents"], 3)
        self.assertIn("TEXT_BM25", resultado.rows[0]["plan"])

    def test_explain_tf_idf(self):
        resultado = self.engine.run(
            "EXPLAIN SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos') USING TF_IDF"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.execution_plan["access_path"], "TEXT_TF_IDF")

    def test_explain_analyze_textual(self):
        resultado = self.engine.run(
            "EXPLAIN ANALYZE SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos') USING BM25"
        )
        self.assertTrue(resultado.success, resultado.error)
        plan = resultado.execution_plan
        self.assertEqual(plan["access_path"], "TEXT_BM25")
        self.assertEqual(plan["analyze"]["rows"], 2)


if __name__ == "__main__":
    unittest.main()
