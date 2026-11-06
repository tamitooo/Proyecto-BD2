"""Pruebas de semántica SQL de las búsquedas textual y vectorial.

Cubren tres observaciones de la revisión:

* GROUP BY con agregados devolvía NULL (proyección de los agregados).
* MATCH y SIMILAR_TO ignoraban el resto del WHERE.
* ORDER BY solo funcionaba con el alias del score y en sentido invertido.

La semántica sigue el orden lógico de SQL: WHERE se aplica antes de
GROUP BY/ORDER BY/LIMIT y ORDER BY ASC/DESC usa el operador < o > (PostgreSQL,
docs 7.2.2, 7.2.3 y 7.5).
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


class TestAgregados(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-sem-")
        self.engine = _Engine(self._dir)
        self.engine.create_table("ventas", [("id", "INT"), ("dept", "VARCHAR(20)"), ("monto", "INT")])
        for i, (dept, monto) in enumerate((("A", 10), ("A", 20), ("B", 5)), start=1):
            self.engine.run(f"INSERT INTO ventas VALUES ({i}, '{dept}', {monto})")

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_group_by_con_agregados(self):
        resultado = self.engine.run(
            "SELECT dept, COUNT(*) AS n, SUM(monto) AS total FROM ventas GROUP BY dept"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.rows, [{"dept": "A", "n": 2, "total": 30},
                                          {"dept": "B", "n": 1, "total": 5}])

    def test_agregados_sin_group_by(self):
        resultado = self.engine.run("SELECT COUNT(*) AS n, SUM(monto) AS total FROM ventas")
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.rows, [{"n": 3, "total": 35}])

    def test_agregados_sin_alias(self):
        resultado = self.engine.run("SELECT COUNT(*), AVG(monto) FROM ventas")
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.columns, ["count_all", "avg_monto"])
        self.assertEqual(resultado.rows[0]["count_all"], 3)
        self.assertAlmostEqual(resultado.rows[0]["avg_monto"], 35 / 3)

    def test_group_by_dos_columnas(self):
        self.engine.run("INSERT INTO ventas VALUES (4, 'A', 5)")
        resultado = self.engine.run(
            "SELECT dept, monto, COUNT(*) AS n FROM ventas GROUP BY dept, monto"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(len(resultado.rows), 4)

    def test_group_by_columna_no_agrupada_es_error(self):
        resultado = self.engine.run("SELECT dept, monto FROM ventas GROUP BY dept")
        self.assertFalse(resultado.success)
        self.assertIn("GROUP BY", resultado.error or "")

    def test_select_estrella_con_group_by_es_error(self):
        resultado = self.engine.run("SELECT * FROM ventas GROUP BY dept")
        self.assertFalse(resultado.success)
        self.assertIn("GROUP BY", resultado.error or "")

    def test_group_by_order_by_agregado(self):
        resultado = self.engine.run(
            "SELECT dept, COUNT(*) AS n FROM ventas GROUP BY dept ORDER BY n DESC"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.rows, [{"dept": "A", "n": 2}, {"dept": "B", "n": 1}])


class TestWhereConMatchYSimilarTo(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-sem-")
        self.engine = _Engine(self._dir)
        self.engine.create_table("documentos", [("id", "INT"), ("contenido", "VARCHAR(200)"),
                                                ("idioma", "VARCHAR(5)"), ("vistas", "INT")])
        for i, (txt, lang, vistas) in enumerate((
                ("base de datos vectorial", "es", 100),
                ("machine learning", "en", 200),
                ("base de datos", "es", 50)), start=1):
            self.engine.run(f"INSERT INTO documentos VALUES ({i}, '{txt}', '{lang}', {vistas})")
        self.engine.create_table("imagenes", [("id", "INT"), ("embedding", "VARCHAR(200)"),
                                              ("categoria", "VARCHAR(5)")])
        for i, (vec, cat) in enumerate((("[1, 0]", "a"), ("[0, 1]", "b"), ("[0.8, 0.6]", "b")), start=1):
            self.engine.run(f"INSERT INTO imagenes VALUES ({i}, '{vec}', '{cat}')")

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_match_respeta_where_de_igualdad(self):
        resultado = self.engine.run(
            "SELECT id FROM documentos WHERE idioma = 'es' "
            "AND MATCH(contenido, 'base de datos') USING BM25"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(sorted(r["id"] for r in resultado.rows), [1, 3])

    def test_match_respeta_where_de_rango(self):
        resultado = self.engine.run(
            "SELECT id FROM documentos WHERE vistas >= 100 "
            "AND MATCH(contenido, 'base de datos') USING BM25"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(sorted(r["id"] for r in resultado.rows), [1])

    def test_match_con_where_sin_coincidencias(self):
        resultado = self.engine.run(
            "SELECT id FROM documentos WHERE idioma = 'en' "
            "AND MATCH(contenido, 'base de datos') USING BM25"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.rows, [])

    def test_similar_to_respeta_where(self):
        resultado = self.engine.run(
            "SELECT id FROM imagenes WHERE categoria = 'b' "
            "AND SIMILAR_TO([1, 0], k=5) USING HNSW WITH METRIC=cosine"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(sorted(r["id"] for r in resultado.rows), [2, 3])

    def test_match_limit_despues_del_where(self):
        resultado = self.engine.run(
            "SELECT id, SCORE() AS score FROM documentos WHERE idioma = 'es' "
            "AND MATCH(contenido, 'base de datos') USING BM25 "
            "ORDER BY score DESC LIMIT 1"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual([r["id"] for r in resultado.rows], [3])


class TestOrderBy(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-sem-")
        self.engine = _Engine(self._dir)
        self.engine.create_table("documentos", [("id", "INT"), ("contenido", "VARCHAR(200)")])
        for i, txt in enumerate(("base de datos vectorial", "machine learning", "base de datos"), start=1):
            self.engine.run(f"INSERT INTO documentos VALUES ({i}, '{txt}')")
        self.engine.create_table("imagenes", [("id", "INT"), ("embedding", "VARCHAR(200)")])
        for i, vec in enumerate(("[1, 0]", "[0, 1]", "[0.8, 0.6]"), start=1):
            self.engine.run(f"INSERT INTO imagenes VALUES ({i}, '{vec}')")

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_order_by_score_desc(self):
        resultado = self.engine.run(
            "SELECT id, SCORE() AS score FROM documentos "
            "WHERE MATCH(contenido, 'base de datos') USING BM25 ORDER BY score DESC"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual([r["id"] for r in resultado.rows], [3, 1])
        self.assertGreaterEqual(resultado.rows[0]["score"], resultado.rows[1]["score"])

    def test_order_by_score_asc(self):
        resultado = self.engine.run(
            "SELECT id, SCORE() AS score FROM documentos "
            "WHERE MATCH(contenido, 'base de datos') USING BM25 ORDER BY score ASC"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual([r["id"] for r in resultado.rows], [1, 3])
        self.assertLessEqual(resultado.rows[0]["score"], resultado.rows[1]["score"])

    def test_order_by_columna_normal(self):
        resultado = self.engine.run(
            "SELECT id FROM documentos "
            "WHERE MATCH(contenido, 'base de datos') USING BM25 ORDER BY id ASC"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual([r["id"] for r in resultado.rows], [1, 3])
        resultado = self.engine.run(
            "SELECT id FROM documentos "
            "WHERE MATCH(contenido, 'base de datos') USING BM25 ORDER BY id DESC"
        )
        self.assertEqual([r["id"] for r in resultado.rows], [3, 1])

    def test_limit_aplica_despues_de_order_by(self):
        resultado = self.engine.run(
            "SELECT id FROM documentos "
            "WHERE MATCH(contenido, 'base de datos') USING BM25 ORDER BY id ASC LIMIT 1"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual([r["id"] for r in resultado.rows], [1])

    def test_order_by_score_vectorial(self):
        resultado = self.engine.run(
            "SELECT id, SIMILARITY_SCORE() AS score FROM imagenes "
            "WHERE SIMILAR_TO([1, 0], k=3) USING HNSW WITH METRIC=cosine ORDER BY score ASC"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual([r["id"] for r in resultado.rows], [2, 3, 1])

    def test_order_by_columna_vectorial(self):
        resultado = self.engine.run(
            "SELECT id FROM imagenes "
            "WHERE SIMILAR_TO([1, 0], k=3) USING HNSW WITH METRIC=cosine ORDER BY id ASC"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual([r["id"] for r in resultado.rows], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
