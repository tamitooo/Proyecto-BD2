"""CREATE INDEX ... USING IVF: índice persistido en disco y usado por SIMILAR_TO."""

import math
import random
import shutil
import tempfile
import unittest
from pathlib import Path

from query.catalog import Catalog
from query.query_executor import QueryExecutor
from query.sql_parser import SQLParseError, SQLParser
from storage.heap_file import HeapFile


def _cosine(a, b):
    return sum(x * y for x, y in zip(a, b)) / math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))


class TestParserIVF(unittest.TestCase):
    def test_create_index_ivf_con_metrica(self):
        s = SQLParser().parse("CREATE INDEX idx ON imagenes (embedding) USING IVF WITH METRIC=coseno")
        self.assertEqual((s.kind, s.metric, s.column), ("ivf", "cosine", "embedding"))

    def test_metrica_por_defecto(self):
        self.assertIsNone(SQLParser().parse("CREATE INDEX ON imagenes (embedding) USING IVF").metric)

    def test_metrica_solo_con_ivf(self):
        with self.assertRaises(SQLParseError):
            SQLParser().parse("CREATE INDEX idx ON t (x) USING HASH WITH METRIC=cosine")


class TestIndiceIVFPersistido(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="bd2-ivf-sql-")
        self.catalog = Catalog(data_dir=self.dir)
        self.ex = QueryExecutor(self.catalog)
        self.ok("CREATE TABLE imagenes (id INT PRIMARY KEY, embedding VARCHAR(300))")
        rng = random.Random(3)
        self.vectors = {}
        for i in range(1, 201):
            vector = [round(rng.gauss((i % 4) * 3, 1), 4) for _ in range(6)]
            self.vectors[i] = vector
            self.ok(f"INSERT INTO imagenes VALUES ({i}, '{vector}')")
        self.ok("CREATE INDEX idx_img ON imagenes (embedding) USING IVF WITH METRIC=cosine")
        self.query = self.vectors[5]

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def ok(self, sql):
        result = self.ex.execute(sql)
        self.assertTrue(result.success, f"{sql}: {result.error}")
        return result

    def knn(self, k=10, metric="cosine", extra=""):
        return self.ok(f"SELECT id FROM imagenes WHERE SIMILAR_TO({self.query}, k={k}) {extra}"
                       f"USING IVF WITH METRIC={metric}")

    def test_similar_to_usa_el_indice_sin_construir(self):
        result = self.knn()
        step = result.execution_plan["steps"][0]
        self.assertEqual(result.execution_plan["used_indexes"], ["idx_img"])
        self.assertTrue(step["details"]["persistent"])
        self.assertEqual(step["details"]["build_ms"], 0.0)

    def test_recall_contra_fuerza_bruta(self):
        exact = sorted(self.vectors, key=lambda i: -_cosine(self.query, self.vectors[i]))[:10]
        got = [row["id"] for row in self.knn().rows]
        self.assertGreaterEqual(len(set(got) & set(exact)) / 10, 0.9)

    def test_archivo_en_disco(self):
        self.assertTrue((Path(self.dir) / "indexes" / "imagenes__idx_img.idx").is_file())

    def test_restaura_desde_el_archivo_sin_recorrer_la_tabla(self):
        expected = [row["id"] for row in self.knn().rows]
        definition = self.catalog.describe_tables()[0]
        original = HeapFile.scan
        HeapFile.scan = lambda *a, **k: (_ for _ in ()).throw(AssertionError("recorrió la tabla"))
        try:
            restored = Catalog(data_dir=self.dir)
            restored.restore_table(definition)
        finally:
            HeapFile.scan = original
        self.ex = QueryExecutor(restored)
        result = self.knn()
        self.assertEqual(result.execution_plan["used_indexes"], ["idx_img"])
        self.assertEqual([row["id"] for row in result.rows], expected)

    def test_insert_y_delete_mantienen_el_indice(self):
        nearby = [x + 0.001 for x in self.query]
        self.ok(f"INSERT INTO imagenes VALUES (999, '{nearby}')")
        self.assertIn(999, [row["id"] for row in self.knn(k=2).rows])
        self.ok("DELETE FROM imagenes WHERE id = 999")
        self.assertNotIn(999, [row["id"] for row in self.knn(k=2).rows])

    def test_otra_metrica_no_usa_el_indice(self):
        result = self.knn(metric="euclidean")
        self.assertEqual(result.execution_plan["used_indexes"], ["embedding"])

    def test_filtro_adicional_del_where(self):
        rows = self.knn(k=3, extra="AND id > 150 ").rows
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["id"] > 150 for row in rows))

    def test_explain_muestra_el_indice(self):
        result = self.ok(f"EXPLAIN SELECT id FROM imagenes WHERE SIMILAR_TO({self.query}, k=5) "
                         "USING IVF WITH METRIC=cosine")
        self.assertIn("idx_img", result.execution_plan["steps"][0]["reason"])

    def test_drop_index_borra_el_archivo(self):
        self.ok("DROP INDEX idx_img")
        self.assertFalse((Path(self.dir) / "indexes" / "imagenes__idx_img.idx").exists())

    def test_vector_de_otra_dimension_se_rechaza(self):
        result = self.ex.execute("INSERT INTO imagenes VALUES (500, '[1, 2]')")
        self.assertFalse(result.success)
        self.assertEqual(self.ok("SELECT COUNT(*) AS n FROM imagenes").rows[0]["n"], 200)


class TestIndiceIVFSobreTablaVacia(unittest.TestCase):
    def test_se_entrena_con_el_primer_insert(self):
        directory = tempfile.mkdtemp(prefix="bd2-ivf-sql-")
        try:
            ex = QueryExecutor(Catalog(data_dir=directory))
            for sql in ("CREATE TABLE v (id INT PRIMARY KEY, embedding VARCHAR(50))",
                        "CREATE INDEX iv ON v (embedding) USING IVF",
                        "INSERT INTO v VALUES (1, '[1, 0]')",
                        "INSERT INTO v VALUES (2, '[0, 1]')"):
                self.assertTrue(ex.execute(sql).success, sql)
            result = ex.execute("SELECT id FROM v WHERE SIMILAR_TO([1, 0.1], k=1) USING IVF")
            self.assertEqual([row["id"] for row in result.rows], [1])
            self.assertEqual(result.execution_plan["used_indexes"], ["iv"])
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
