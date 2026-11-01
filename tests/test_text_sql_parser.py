"""Pruebas del parser SQL para la búsqueda textual (Parte 3, sección 2.3.3).

Cubre la sintaxis del enunciado:

* ``WHERE MATCH(contenido, 'base de datos vectorial')``
* ``USING TF_IDF`` / ``USING BM25``
* ``SCORE() AS relevancia`` en las columnas y ``ORDER BY relevancia``

#56 es solo el parser: el ejecutor textual llega con #60 y el plan con #61.
"""

import unittest

from backend.engine import DemoEngine
from query.query_planner import MatchSpec
from query.sql_parser import SQLParser, SQLParseError


class TestParserMatch(unittest.TestCase):
    """Sintaxis válida de MATCH y de la cláusula USING."""

    def setUp(self):
        self.parser = SQLParser()

    def test_ejemplo_documentos_tf_idf(self):
        sentencia = self.parser.parse(
            "SELECT * FROM documentos "
            "WHERE MATCH(contenido, 'base de datos vectorial') "
            "USING TF_IDF LIMIT 10"
        )
        q = sentencia.query_spec
        self.assertIsInstance(q.match, MatchSpec)
        self.assertEqual(q.match.predicate.column, "contenido")
        self.assertEqual(q.match.predicate.query, "base de datos vectorial")
        self.assertEqual(q.match.ranking, "tf_idf")
        self.assertEqual(sentencia.limit, 10)
        self.assertEqual(q.predicates, ())

    def test_ejemplo_articulos_bm25_con_score(self):
        sentencia = self.parser.parse(
            "SELECT *, SCORE() as relevancia FROM articulos "
            "WHERE MATCH(texto, 'machine learning') "
            "USING BM25 ORDER BY relevancia DESC"
        )
        q = sentencia.query_spec
        self.assertEqual(q.match.predicate.column, "texto")
        self.assertEqual(q.match.predicate.query, "machine learning")
        self.assertEqual(q.match.ranking, "bm25")
        self.assertEqual(sentencia.columns, ("*", "SCORE() as relevancia"))
        self.assertEqual(len(q.order_by), 1)
        self.assertEqual(q.order_by[0].column, "relevancia")
        self.assertTrue(q.order_by[0].descending)

    def test_sin_using_el_ranking_queda_sin_definir(self):
        q = self.parser.parse(
            "SELECT * FROM documentos WHERE MATCH(contenido, 'hola')"
        ).query_spec
        self.assertIsNone(q.match.ranking)

    def test_case_insensitive_y_espacios(self):
        q = self.parser.parse(
            "select * from documentos where match ( contenido , 'Hola Mundo' ) using bm25"
        ).query_spec
        self.assertEqual(q.match.predicate.query, "Hola Mundo")
        self.assertEqual(q.match.ranking, "bm25")

    def test_columna_calificada(self):
        q = self.parser.parse(
            "SELECT * FROM documentos WHERE MATCH(d.contenido, 'texto')"
        ).query_spec
        self.assertEqual(q.match.predicate.column, "contenido")

    def test_comillas_dobles_y_duplicadas(self):
        q = self.parser.parse(
            "SELECT * FROM documentos WHERE MATCH(contenido, 'it''s ok')"
        ).query_spec
        self.assertEqual(q.match.predicate.query, "it's ok")

    def test_combinado_con_predicado_normal(self):
        q = self.parser.parse(
            "SELECT * FROM documentos WHERE idioma = 'es' "
            "AND MATCH(contenido, 'bases') USING BM25"
        ).query_spec
        self.assertEqual(len(q.predicates), 1)
        self.assertEqual(q.predicates[0].column, "idioma")
        self.assertEqual(q.match.predicate.query, "bases")


class TestParserMatchErrores(unittest.TestCase):
    """Errores de sintaxis con mensajes claros."""

    def setUp(self):
        self.parser = SQLParser()

    def assertParseError(self, sql):
        with self.assertRaises(SQLParseError):
            self.parser.parse(sql)

    def test_sin_columna(self):
        self.assertParseError("SELECT * FROM documentos WHERE MATCH('hola')")

    def test_texto_sin_comillas(self):
        self.assertParseError("SELECT * FROM documentos WHERE MATCH(contenido, hola)")

    def test_texto_vacio(self):
        self.assertParseError("SELECT * FROM documentos WHERE MATCH(contenido, '')")

    def test_using_desconocido(self):
        self.assertParseError(
            "SELECT * FROM documentos WHERE MATCH(contenido, 'x') USING FAISS"
        )

    def test_using_sin_match(self):
        self.assertParseError("SELECT * FROM documentos USING TF_IDF")

    def test_metrica_en_ranking_textual(self):
        self.assertParseError(
            "SELECT * FROM documentos WHERE MATCH(contenido, 'x') "
            "USING TF_IDF WITH METRIC=cosine"
        )

    def test_match_con_hnsw(self):
        self.assertParseError(
            "SELECT * FROM documentos WHERE MATCH(contenido, 'x') USING HNSW"
        )

    def test_match_y_similar_to_juntos(self):
        self.assertParseError(
            "SELECT * FROM documentos WHERE MATCH(contenido, 'x') "
            "AND SIMILAR_TO('a.jpg', k=2)"
        )

    def test_dos_match_en_la_misma_consulta(self):
        self.assertParseError(
            "SELECT * FROM documentos WHERE MATCH(a, 'x') AND MATCH(b, 'y')"
        )


class TestEjecutorSinSoporteTodavia(unittest.TestCase):
    """Mientras #60 no exista, el motor debe fallar con un mensaje explícito."""

    def test_select_match_devuelve_error_claro(self):
        engine = DemoEngine()
        engine.run("CREATE TABLE documentos (id INT PRIMARY KEY, contenido VARCHAR(200))")
        resultado = engine.run(
            "SELECT * FROM documentos WHERE MATCH(contenido, 'hola') USING BM25"
        )
        self.assertFalse(resultado.success)
        self.assertIn("issue #60", resultado.error or "")


if __name__ == "__main__":
    unittest.main()
