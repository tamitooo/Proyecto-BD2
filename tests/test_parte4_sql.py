"""Pruebas de la Parte 4 por SQL (issue #80).

Compara el resultado de ``SIMILAR_TO`` ejecutado con HNSW e IVF contra la
respuesta exacta calculada en Python para las tres métricas. Con un dataset
pequeño ambos índices deben coincidir con la fuerza bruta, que es la referencia
de corrección de un k-NN.
"""

import math
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


QUERY = (1.0, 1.5)
VECTORS = {
    1: (1.0, 1.5),
    2: (5.0, 5.0),
    3: (0.8, 0.6),
    4: (-1.0, 0.0),
    5: (0.6, 0.8),
}
CATEGORIAS = {1: "a", 2: "b", 3: "a", 4: "b", 5: "b"}


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _norm(a):
    return math.hypot(*a)


def _cosine(a, b):
    na, nb = _norm(a), _norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return _dot(a, b) / (na * nb)


def _euclidean(a, b):
    return math.dist(a, b)


def _expected(metric, k=None):
    """Ranking exacto: (id, score) ordenado por score descendente."""
    rows = []
    for doc_id, vector in VECTORS.items():
        if metric == "cosine":
            rows.append((doc_id, _cosine(QUERY, vector)))
        elif metric == "dot_product":
            rows.append((doc_id, _dot(QUERY, vector)))
        else:
            rows.append((doc_id, 1.0 / (1.0 + _euclidean(QUERY, vector))))
    rows.sort(key=lambda item: (-item[1], item[0]))
    return rows if k is None else rows[:k]


class TestParte4Sql(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-p4-")
        self.engine = _Engine(self._dir)
        self.engine.create_table("imagenes", [("id", "INT"), ("embedding", "VARCHAR(200)"),
                                               ("categoria", "VARCHAR(5)")])
        for doc_id, vector in VECTORS.items():
            self.engine.run(
                f"INSERT INTO imagenes VALUES ({doc_id}, '[{vector[0]}, {vector[1]}]', '{CATEGORIAS[doc_id]}')"
            )

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def query(self, index, metric, *, k=3, extra=""):
        return self.engine.run(
            "SELECT id, SIMILARITY_SCORE() AS score FROM imagenes "
            f"WHERE SIMILAR_TO([{QUERY[0]}, {QUERY[1]}], k={k}) "
            f"USING {index} WITH METRIC={metric}{extra}"
        )

    def test_hnsw_y_ivf_coinciden_con_la_fuerza_bruta(self):
        for index in ("HNSW", "IVF"):
            for metric in ("euclidean", "cosine", "dot_product"):
                with self.subTest(index=index, metric=metric):
                    resultado = self.query(index, metric)
                    self.assertTrue(resultado.success, resultado.error)
                    esperado = _expected(metric, k=3)
                    self.assertEqual([r["id"] for r in resultado.rows], [d for d, _ in esperado])
                    for fila, (_, score) in zip(resultado.rows, esperado):
                        self.assertAlmostEqual(fila["score"], score, places=6)

    def test_hnsw_e_ivf_dan_el_mismo_resultado(self):
        for metric in ("euclidean", "cosine", "dot_product"):
            with self.subTest(metric=metric):
                hnsw = self.query("HNSW", metric)
                ivf = self.query("IVF", metric)
                self.assertTrue(hnsw.success and ivf.success)
                self.assertEqual([r["id"] for r in hnsw.rows], [r["id"] for r in ivf.rows])

    def test_k_mayor_que_la_tabla_devuelve_todo(self):
        resultado = self.query("HNSW", "cosine", k=10)
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(len(resultado.rows), len(VECTORS))

    def test_where_se_aplica_antes_del_top_k(self):
        resultado = self.engine.run(
            "SELECT id, categoria FROM imagenes WHERE categoria = 'b' "
            f"AND SIMILAR_TO([{QUERY[0]}, {QUERY[1]}], k=5) USING HNSW WITH METRIC=cosine"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(sorted(r["id"] for r in resultado.rows), [2, 4, 5])
        self.assertTrue(all(r["categoria"] == "b" for r in resultado.rows))

    def test_order_by_id_sobre_los_vecinos(self):
        resultado = self.query("HNSW", "cosine", k=3, extra=" ORDER BY id ASC")
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual([r["id"] for r in resultado.rows], [1, 2, 5])

    def test_metricas_distintas_dan_ordenes_distintos(self):
        cosine = [r["id"] for r in self.query("HNSW", "cosine").rows]
        dot = [r["id"] for r in self.query("HNSW", "dot_product").rows]
        self.assertNotEqual(cosine, dot)


if __name__ == "__main__":
    unittest.main()
