"""Pruebas de ejecución de SIMILAR_TO (Parte 4, issues #87, #88 y #90).

La tabla guarda los vectores en una columna VARCHAR con JSON mientras la
extracción de características (#107) no exista; el vector de consulta se pasa
como literal. Se cubren HNSW, IVF y las tres métricas.
"""

import os
import shutil
import tempfile
import unittest
import uuid

from query.catalog import Catalog
from query.query_executor import QueryExecutor
from query.vector_queries import VectorQueryError, parse_vector


def _temp_dir(prefix):
    base = tempfile.gettempdir()
    if os.path.abspath(base) == os.path.abspath(os.getcwd()):
        local = os.environ.get("LOCALAPPDATA")
        base = os.path.join(local, "Temp") if local else base
    base = os.path.join(base, "bd2-tests")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"{prefix}{uuid.uuid4().hex}")
    os.makedirs(path)
    return path


class _Engine:
    """QueryExecutor sobre un catálogo propio (sin las tablas demo de DemoEngine)."""

    def __init__(self, directory):
        self._executor = QueryExecutor(Catalog(data_dir=directory))

    def run(self, sql):
        return self._executor.execute(sql)


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
        self.engine.run(
            "CREATE TABLE imagenes (id INT PRIMARY KEY, embedding VARCHAR(500))"
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

    def test_archivo_requiere_extraccion_de_caracteristicas(self):
        resultado = self.engine.run(
            "SELECT * FROM imagenes WHERE SIMILAR_TO('foto.jpg', k=2) USING HNSW"
        )
        self.assertFalse(resultado.success)
        self.assertIn("#107", resultado.error or "")

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
            engine.run("CREATE TABLE t (id INT PRIMARY KEY, nombre VARCHAR(10))")
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
