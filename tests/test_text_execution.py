"""Ejecución de MATCH: BM25, TF-IDF, SCORE(), ORDER BY y LIMIT."""

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
    def test_busqueda_productos_ordena_por_relevancia_y_precio(self):
        self.engine.create_table(
            "productos_orden",
            [
                ("id", "INT"),
                ("descripcion", "VARCHAR(200)"),
                ("precio", "FLOAT"),
            ],
        )

        productos = (
            (1, "laptop gaming gaming potente", 4200.0),
            (2, "laptop gaming ligera", 2800.0),
            (3, "laptop gaming económica", 1900.0),
        )

        for producto_id, descripcion, precio in productos:
            self.engine.run(
                "INSERT INTO productos_orden VALUES "
                f"({producto_id}, '{descripcion}', {precio})"
            )

        por_relevancia = self.engine.run(
            "SELECT id, precio, SCORE() AS score "
            "FROM productos_orden "
            "WHERE MATCH(descripcion, 'laptop gaming') "
            "USING BM25 "
            "ORDER BY score DESC"
        )

        self.assertTrue(por_relevancia.success, por_relevancia.error)
        self.assertEqual(por_relevancia.rows[0]["id"], 1)

        por_precio = self.engine.run(
            "SELECT id, precio, SCORE() AS score "
            "FROM productos_orden "
            "WHERE MATCH(descripcion, 'laptop gaming') "
            "USING BM25 "
            "ORDER BY precio ASC"
        )

        self.assertTrue(por_precio.success, por_precio.error)
        self.assertEqual(
            [row["id"] for row in por_precio.rows],
            [3, 2, 1],
        )

    def test_bm25_con_filtro_de_precio(self):
        self.engine.create_table(
            "productos_precio",
            [
                ("id", "INT"),
                ("descripcion", "VARCHAR(200)"),
                ("precio", "FLOAT"),
            ],
        )

        productos = (
            (1, "laptop gaming potente", 3500.0),
            (2, "laptop gaming económica", 1800.0),
            (3, "laptop gaming profesional", 6200.0),
        )

        for producto_id, descripcion, precio in productos:
            self.engine.run(
                "INSERT INTO productos_precio VALUES "
                f"({producto_id}, '{descripcion}', {precio})"
            )

        resultado = self.engine.run(
            "SELECT id, precio, SCORE() AS score "
            "FROM productos_precio "
            "WHERE MATCH(descripcion, 'laptop gaming') "
            "AND precio >= 2000 "
            "AND precio <= 5000 "
            "USING BM25 "
            "ORDER BY score DESC"
        )

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(
            [row["id"] for row in resultado.rows],
            [1],
        )

        self.assertTrue(
            all(2000 <= row["precio"] <= 5000 for row in resultado.rows)
        )

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

    def test_bm25_con_filtro_de_categoria(self):
        self.engine.create_table(
            "productos",
            [
                ("id", "INT"),
                ("descripcion", "VARCHAR(200)"),
                ("categoria", "VARCHAR(50)"),
            ],
        )

        productos = (
            (1, "laptop gaming potente", "laptops"),
            (2, "laptop ultraligera oficina", "laptops"),
            (3, "mochila para laptop gaming", "mochilas"),
        )

        for producto_id, descripcion, categoria in productos:
            self.engine.run(
                "INSERT INTO productos VALUES "
                f"({producto_id}, '{descripcion}', '{categoria}')"
            )

        resultado = self.engine.run(
            "SELECT id, categoria, SCORE() AS score "
            "FROM productos "
            "WHERE MATCH(descripcion, 'laptop gaming') "
            "AND categoria = 'laptops' "
            "USING BM25 "
            "ORDER BY score DESC"
        )

        self.assertTrue(resultado.success, resultado.error)
        self.assertGreater(len(resultado.rows), 0)

        self.assertTrue(
            all(row["categoria"] == "laptops" for row in resultado.rows)
        )

        self.assertNotIn(
            3,
            [row["id"] for row in resultado.rows],
        )

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


class TestIndiceSPIMI(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-spimi-")
        self.engine = _Engine(self._dir)
        self.engine.create_table("documentos", [("id", "INT"), ("contenido", "VARCHAR(200)")])
        for doc_id, contenido in ((1, "base de datos vectorial"), (2, "machine learning"), (3, "base de datos")):
            self.engine.run(f"INSERT INTO documentos VALUES ({doc_id}, '{contenido}')")

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def buscar(self, texto="base de datos", extra=""):
        resultado = self.engine.run(
            f"SELECT * FROM documentos WHERE MATCH(contenido, '{texto}') {extra} USING BM25"
        )
        self.assertTrue(resultado.success, resultado.error)
        return resultado

    def spimi(self, resultado):
        return next(s for s in resultado.execution_plan["steps"] if s["operator"] == "SPIMI_INDEX")["details"]

    def test_indice_en_disco_y_reutilizado(self):
        primero = self.spimi(self.buscar())
        self.assertFalse(primero["reused"])
        self.assertTrue(os.path.isdir(primero["index_path"]))
        with open(os.path.join(primero["index_path"], "CURRENT"), encoding="utf-8") as stream:
            vigente = os.path.join(primero["index_path"], stream.read().strip())
        self.assertTrue(os.path.isfile(os.path.join(vigente, "index", "lexicon.spimi.jsonl")))
        self.assertTrue(os.path.isfile(os.path.join(vigente, "documents.json")))
        self.assertTrue(self.spimi(self.buscar("machine"))["reused"])

    def test_insert_reconstruye_el_indice(self):
        self.buscar()
        self.engine.run("INSERT INTO documentos VALUES (4, 'bases vectoriales nuevas')")
        resultado = self.buscar("nuevas")
        self.assertFalse(self.spimi(resultado)["reused"])
        self.assertEqual([row["id"] for row in resultado.rows], [4])
        builds = [x for x in os.listdir(self.spimi(resultado)["index_path"]) if x.startswith("build-")]
        self.assertEqual(len(builds), 1)

    def test_drop_table_borra_el_indice(self):
        path = self.spimi(self.buscar())["index_path"]
        self.engine.catalog.drop_table("documentos")
        self.assertFalse(os.path.exists(path))

    def test_filtro_extra_usa_el_mismo_indice(self):
        resultado = self.engine.run(
            "SELECT * FROM documentos WHERE MATCH(contenido, 'base de datos') AND id > 1 USING BM25"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual([row["id"] for row in resultado.rows], [3])


class TestIndiceSPIMIConRutaRelativa(unittest.TestCase):
    def test_data_dir_relativo(self):
        base = _temp_dir("bd2-spimi-rel-")
        previo = os.getcwd()
        os.chdir(base)
        try:
            engine = _Engine("datos")
            engine.create_table("documentos", [("id", "INT"), ("contenido", "VARCHAR(200)")])
            engine.run("INSERT INTO documentos VALUES (1, 'base de datos')")
            for _ in range(2):
                resultado = engine.run(
                    "SELECT * FROM documentos WHERE MATCH(contenido, 'datos') USING BM25"
                )
                self.assertTrue(resultado.success, resultado.error)
                self.assertEqual([row["id"] for row in resultado.rows], [1])
        finally:
            os.chdir(previo)
            shutil.rmtree(base, ignore_errors=True)
