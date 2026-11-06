"""Parser SQL de la búsqueda vectorial: ``SIMILAR_TO``, ``USING HNSW/IVF`` y ``SIMILARITY_SCORE()``."""

import os
import shutil
import tempfile
import unittest
import uuid

from query.catalog import Catalog
from query.query_executor import QueryExecutor
from query.query_planner import SimilaritySpec
from query.sql_parser import SQLParser, SQLParseError


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


class TestParserSimilarTo(unittest.TestCase):
    """Sintaxis válida de SIMILAR_TO y de la cláusula USING."""

    def setUp(self):
        self.parser = SQLParser()

    def test_ejemplo_imagenes_hnsw_coseno(self):
        sentencia = self.parser.parse(
            "SELECT * FROM imagenes WHERE SIMILAR_TO('foto_consulta.jpg', k=10) "
            "USING HNSW WITH METRIC=cosine"
        )
        q = sentencia.query_spec
        self.assertIsInstance(q.similarity, SimilaritySpec)
        self.assertEqual(q.similarity.predicate.target, "foto_consulta.jpg")
        self.assertEqual(q.similarity.predicate.k, 10)
        self.assertEqual(q.similarity.index_kind, "hnsw")
        self.assertEqual(q.similarity.metric, "cosine")
        self.assertEqual(q.predicates, ())
        self.assertEqual(q.table, "imagenes")

    def test_ejemplo_canciones_ivf_euclidiana_con_score(self):
        sentencia = self.parser.parse(
            "SELECT nombre, artista, SIMILARITY_SCORE() as score FROM canciones "
            "WHERE SIMILAR_TO('audio_query.mp3', k=5) "
            "USING IVF WITH METRIC=euclidean ORDER BY score DESC"
        )
        q = sentencia.query_spec
        self.assertEqual(q.similarity.predicate.k, 5)
        self.assertEqual(q.similarity.index_kind, "ivf")
        self.assertEqual(q.similarity.metric, "euclidean")
        self.assertEqual(sentencia.columns,
                         ("nombre", "artista", "SIMILARITY_SCORE() as score"))
        self.assertEqual(len(q.order_by), 1)
        self.assertEqual(q.order_by[0].column, "score")
        self.assertTrue(q.order_by[0].descending)

    def test_k_por_defecto(self):
        q = self.parser.parse(
            "SELECT * FROM imagenes WHERE SIMILAR_TO('x.jpg')"
        ).query_spec
        self.assertEqual(q.similarity.predicate.k, 10)
        self.assertIsNone(q.similarity.index_kind)
        self.assertIsNone(q.similarity.metric)

    def test_vector_literal(self):
        q = self.parser.parse(
            "SELECT * FROM imagenes WHERE SIMILAR_TO([0.1, 0.2, 0.3], k=3) "
            "USING HNSW"
        ).query_spec
        self.assertEqual(q.similarity.predicate.target, (0.1, 0.2, 0.3))

    def test_objetivo_por_columna(self):
        q = self.parser.parse(
            "SELECT * FROM imagenes WHERE SIMILAR_TO(embedding, k=5)"
        ).query_spec
        self.assertEqual(q.similarity.predicate.target, "embedding")

    def test_no_confunde_con_columnas_normales(self):
        q = self.parser.parse(
            "SELECT * FROM imagenes WHERE categoria = 'x' "
            "AND SIMILAR_TO('f.jpg', k=4) USING HNSW"
        ).query_spec
        self.assertEqual(len(q.predicates), 1)
        self.assertEqual(q.predicates[0].column, "categoria")
        self.assertEqual(q.similarity.predicate.target, "f.jpg")
        self.assertEqual(q.similarity.predicate.k, 4)

    def test_case_insensitive_y_espacios(self):
        q = self.parser.parse(
            "select * from imagenes where similar_to ( 'a.jpg' , k = 2 ) "
            "using ivf with metric = dot"
        ).query_spec
        self.assertEqual(q.similarity.predicate.target, "a.jpg")
        self.assertEqual(q.similarity.predicate.k, 2)
        self.assertEqual(q.similarity.index_kind, "ivf")
        self.assertEqual(q.similarity.metric, "dot_product")

    def test_alias_de_metricas(self):
        q = self.parser.parse(
            "SELECT * FROM imagenes WHERE SIMILAR_TO('a', k=1) "
            "USING HNSW WITH METRIC=coseno"
        ).query_spec
        self.assertEqual(q.similarity.metric, "cosine")

    def test_limit_se_combina_con_k(self):
        sentencia = self.parser.parse(
            "SELECT * FROM imagenes WHERE SIMILAR_TO('a.jpg', k=20) "
            "USING HNSW WITH METRIC=cosine LIMIT 5"
        )
        self.assertEqual(sentencia.limit, 5)
        self.assertEqual(sentencia.query_spec.similarity.predicate.k, 20)


class TestParserSimilarToErrores(unittest.TestCase):
    """Errores de sintaxis con mensajes claros."""

    def setUp(self):
        self.parser = SQLParser()

    def assertParseError(self, sql):
        with self.assertRaises(SQLParseError):
            self.parser.parse(sql)

    def test_using_sin_similar_to(self):
        self.assertParseError("SELECT * FROM imagenes USING HNSW")

    def test_indice_desconocido(self):
        self.assertParseError(
            "SELECT * FROM imagenes WHERE SIMILAR_TO('a', k=2) USING FAISS"
        )

    def test_metrica_desconocida(self):
        self.assertParseError(
            "SELECT * FROM imagenes WHERE SIMILAR_TO('a', k=2) "
            "USING HNSW WITH METRIC=manhattan"
        )

    def test_k_invalido(self):
        self.assertParseError(
            "SELECT * FROM imagenes WHERE SIMILAR_TO('a', k=diez)"
        )

    def test_k_cero(self):
        self.assertParseError(
            "SELECT * FROM imagenes WHERE SIMILAR_TO('a', k=0)"
        )

    def test_objetivo_invalido(self):
        self.assertParseError(
            "SELECT * FROM imagenes WHERE SIMILAR_TO(POINT(1, 2), k=2)"
        )

    def test_parentesis_sin_cerrar(self):
        self.assertParseError(
            "SELECT * FROM imagenes WHERE SIMILAR_TO('a.jpg', k=2"
        )

    def test_dos_similar_to_en_la_misma_consulta(self):
        self.assertParseError(
            "SELECT * FROM imagenes WHERE SIMILAR_TO('a', k=2) "
            "AND SIMILAR_TO('b', k=3)"
        )

    def test_similar_to_con_or_no_soportado(self):
        self.assertParseError(
            "SELECT * FROM imagenes WHERE SIMILAR_TO([1, 0], k=2) OR id = 1"
        )


class TestEjecutorSinSoporteTodavia(unittest.TestCase):
    """Tras #90, buscar por archivo exige ExtractFeatures (#107)."""

    def test_select_similar_to_por_archivo_pide_extractfeatures(self):
        directory = _temp_dir("bd2-sim-")
        try:
            engine = _Engine(directory)
            engine.create_table(
                "imagenes", [("id", "INT"), ("embedding", "VARCHAR(100)")]
            )
            engine.run("INSERT INTO imagenes VALUES (1, '[1, 0]')")
            resultado = engine.run(
                "SELECT * FROM imagenes WHERE SIMILAR_TO('foto.jpg', k=10)"
            )
            self.assertFalse(resultado.success)
            self.assertIn("#107", resultado.error or "")
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
