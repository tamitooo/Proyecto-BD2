"""Pruebas de ejecución de SIMILAR_TO (Parte 4, issues #87, #88 y #90).

La tabla guarda los vectores en una columna VARCHAR con JSON. El vector de
consulta puede ser un literal o un archivo multimedia (#107); la extracción de
archivos se prueba en ``tests/test_media_sql.py``. Se cubren HNSW, IVF y las
tres métricas.
"""

import os
import shutil
import tempfile
import unittest
import uuid

from query.catalog import Catalog
from query.query_executor import QueryExecutor
from query.vector_queries import VectorQueryError, parse_vector


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _temp_dir(prefix):
    base = os.environ.get("BD2_TEST_DIR") or os.path.join(_REPO_ROOT, ".bd2-tests")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"{prefix}{uuid.uuid4().hex}")
    os.makedirs(path)
    return path


class _Engine:
    """Catálogo propio (sin tablas demo ni índices persistentes para las pruebas)."""

    def __init__(self, directory):
        self.catalog = Catalog(data_dir=directory)
        self._executor = QueryExecutor(self.catalog)

    def run(self, sql):
        return self._executor.execute(sql)

    def create_table(self, name, columns, primary_key="id"):
        return self.catalog.create_table(
            name, columns, primary_key=primary_key, primary_key_index=False
        )


class TestParseVector(unittest.TestCase):
    def test_json(self):
        self.assertEqual(parse_vector("[0.1, 0.2]"), (0.1, 0.2))

    def test_separado_por_comas(self):
        self.assertEqual(parse_vector("0.1,0.2"), (0.1, 0.2))

    def test_lista(self):
        self.assertEqual(parse_vector([1, 2]), (1.0, 2.0))

    def test_vacio(self):
        with self.assertRaises(VectorQueryError):
            parse_vector("[]")

    def test_texto_invalido(self):
        with self.assertRaises(VectorQueryError):
            parse_vector("hola")

    def test_escalar(self):
        with self.assertRaises(VectorQueryError):
            parse_vector(5)


class TestEjecucionVectorial(unittest.TestCase):
    """SIMILAR_TO sobre una tabla con la columna embedding."""

    def setUp(self):
        self._dir = _temp_dir("bd2-vec-")
        self.engine = _Engine(self._dir)
        self.engine.create_table(
            "imagenes", [("id", "INT"), ("embedding", "VARCHAR(500)")]
        )
        for i, vector in enumerate(("[1, 0]", "[0, 1]", "[0.8, 0.6]"), start=1):
            self.engine.run(f"INSERT INTO imagenes VALUES ({i}, '{vector}')")

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def ids(self, result):
        return [row["id"] for row in result.rows]

    def test_hnsw_coseno(self):
        resultado = self.engine.run(
            "SELECT * FROM imagenes WHERE SIMILAR_TO([1, 0], k=2) "
            "USING HNSW WITH METRIC=cosine"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(self.ids(resultado), [1, 3])
        self.assertIn("_score", resultado.columns)
        self.assertGreaterEqual(resultado.rows[0]["_score"], resultado.rows[1]["_score"])
        self.assertEqual(resultado.execution_plan["access_path"], "HNSW_KNN")
        self.assertEqual(resultado.execution_plan["used_indexes"], ["embedding"])
        self.assertEqual(resultado.execution_plan["planner_type"], "vector_index")

    def test_similarity_score_como_columna(self):
        resultado = self.engine.run(
            "SELECT id, SIMILARITY_SCORE() as score FROM imagenes "
            "WHERE SIMILAR_TO([1, 0], k=2) USING HNSW WITH METRIC=cosine"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.columns, ["id", "score"])
        self.assertGreater(resultado.rows[0]["score"], 0)

    def test_ivf_euclidiana(self):
        resultado = self.engine.run(
            "SELECT * FROM imagenes WHERE SIMILAR_TO([2, 0], k=3) "
            "USING IVF WITH METRIC=euclidean"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(self.ids(resultado), [1, 3, 2])
        self.assertEqual(resultado.execution_plan["access_path"], "IVF_KNN")
        self.assertEqual(resultado.execution_plan["steps"][0]["details"]["metric"], "euclidean")
        self.assertEqual(resultado.execution_plan["steps"][0]["details"]["vectors"], 3)

    def test_producto_punto(self):
        resultado = self.engine.run(
            "SELECT * FROM imagenes WHERE SIMILAR_TO([1, 0], k=2) "
            "USING HNSW WITH METRIC=dot_product"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(self.ids(resultado), [1, 3])

    def test_limit_acota_los_resultados(self):
        resultado = self.engine.run(
            "SELECT * FROM imagenes WHERE SIMILAR_TO([1, 0], k=3) "
            "USING HNSW WITH METRIC=cosine LIMIT 1"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(len(resultado.rows), 1)

    def test_archivo_inexistente_da_error_claro(self):
        missing = f"no-existe-{uuid.uuid4().hex}.jpg"
        resultado = self.engine.run(
            f"SELECT * FROM imagenes WHERE SIMILAR_TO('{missing}', k=2) USING HNSW"
        )
        self.assertFalse(resultado.success)
        self.assertIn("no se encontró", resultado.error or "")

    def test_columna_como_objetivo_no_define_consulta(self):
        resultado = self.engine.run(
            "SELECT * FROM imagenes WHERE SIMILAR_TO(embedding, k=2) USING HNSW"
        )
        self.assertFalse(resultado.success)
        self.assertIn("vector de consulta", resultado.error or "")

    def test_dimension_incompatible(self):
        resultado = self.engine.run(
            "SELECT * FROM imagenes WHERE SIMILAR_TO([1, 0, 0], k=2) USING HNSW"
        )
        self.assertFalse(resultado.success)
        self.assertIn("dimensión", resultado.error or "")

    def test_filas_sin_vector_se_omiten(self):
        self.engine.run("INSERT INTO imagenes VALUES (4, 'no-vector')")
        resultado = self.engine.run(
            "SELECT * FROM imagenes WHERE SIMILAR_TO([1, 0], k=3) "
            "USING HNSW WITH METRIC=cosine"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(len(resultado.rows), 3)


class TestTablaSinVectores(unittest.TestCase):
    def test_error_claro_sin_columna_de_vectores(self):
        directory = _temp_dir("bd2-vec-")
        try:
            engine = _Engine(directory)
            engine.create_table("t", [("id", "INT"), ("nombre", "VARCHAR(10)")])
            engine.run("INSERT INTO t VALUES (1, 'hola')")
            resultado = engine.run(
                "SELECT * FROM t WHERE SIMILAR_TO([1, 0], k=2) USING HNSW"
            )
            self.assertFalse(resultado.success)
            self.assertIn("columna de vectores", resultado.error or "")
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
