"""``SIMILAR_TO('foto.jpg')`` de punta a punta con BoVW/TF-IDF (2.4.1 / #107).

La prueba crea imágenes con textura y WAV en ``<data_dir>/media``, entrena el
vocabulario (SIFT/MFCC + K-Means), indexa con ``EXTRACT_FEATURES`` y consulta
con ``SIMILAR_TO('archivo')``. El ranking se compara con el coseno calculado
en Python, que es la referencia exacta para un dataset pequeño.
"""

import os
import shutil
import unittest
import uuid
import wave

import numpy as np
from PIL import Image, ImageDraw
from query.catalog import Catalog
from query.query_executor import QueryExecutor
from query.vector_queries import parse_vector
from vector.bow import model_path, train_model
from vector.extract_features import ExtractFeatures
from vector.metrics import cosine_similarity


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _temp_dir(prefix):
    base = os.environ.get("BD2_TEST_DIR") or os.path.join(_REPO_ROOT, ".bd2-tests")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"{prefix}{uuid.uuid4().hex}")
    os.makedirs(path)
    return path


def _bars(path, color, *, count=4, width=8, offset=0):
    image = Image.new("RGB", (96, 96), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for index in range(count):
        y = 10 + index * 20 + offset
        draw.rectangle((8, y, 88, y + width), fill=color)
    image.save(path)
    return path


def _checker(path, color, *, size=12):
    image = Image.new("RGB", (96, 96), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for y in range(0, 96, size):
        for x in range(0, 96, size):
            if (x // size + y // size) % 2 == 0:
                draw.rectangle((x, y, x + size - 1, y + size - 1), fill=color)
    image.save(path)
    return path


def _rings(path, color):
    image = Image.new("RGB", (96, 96), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for radius in range(10, 50, 10):
        draw.ellipse(
            (48 - radius, 48 - radius, 48 + radius, 48 + radius),
            outline=color,
            width=4,
        )
    image.save(path)
    return path


def _wav(path, frequency, *, phase=0.0, rate=16000):
    time_axis = np.arange(rate // 2) / rate
    samples = (
        0.5 * np.sin(2 * np.pi * frequency * time_axis + phase) * 32767
    ).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return path


class _Engine:
    def __init__(self, directory):
        self.catalog = Catalog(data_dir=directory)
        self.executor = QueryExecutor(self.catalog)
        self.media_dir = os.path.join(directory, "media")
        self.model_dir = os.path.join(directory, "models")
        os.makedirs(self.media_dir, exist_ok=True)
        os.makedirs(self.model_dir, exist_ok=True)

    def run(self, sql):
        return self.executor.execute(sql)

    def train(self, kind, paths, n_words):
        documents = [
            ExtractFeatures.local_descriptors(path, kind=kind)
            for path in paths
        ]
        model = train_model(kind, documents, n_words, seed=7)
        model.save(model_path(self.model_dir, kind))
        return model


class TestSimilarToPorArchivo(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-media-sql-")
        self.engine = _Engine(self._dir)
        self.image_files = [
            _bars(os.path.join(self.engine.media_dir, "rojo.png"), (180, 20, 20)),
            _bars(
                os.path.join(self.engine.media_dir, "rojo_2.png"),
                (200, 30, 30),
                width=9,
                offset=3,
            ),
            _checker(os.path.join(self.engine.media_dir, "azul.png"), (20, 20, 180)),
            _rings(os.path.join(self.engine.media_dir, "verde.png"), (20, 150, 30)),
        ]
        _bars(
            os.path.join(self.engine.media_dir, "consulta.png"),
            (180, 20, 20),
            offset=0,
        )
        self.image_model = self.engine.train("image", self.image_files, 8)

        self.assertTrue(self.engine.run(
            "CREATE TABLE fotos (id INT PRIMARY KEY, nombre VARCHAR(64), "
            "embedding VARCHAR(4096), categoria VARCHAR(16))"
        ).success)
        rows = [
            (1, "rojo.png", "rojo"),
            (2, "rojo_2.png", "rojo"),
            (3, "azul.png", "azul"),
            (4, "verde.png", "verde"),
        ]
        for doc_id, name, category in rows:
            result = self.engine.run(
                f"INSERT INTO fotos VALUES ({doc_id}, '{name}', "
                f"EXTRACT_FEATURES('{name}'), '{category}')"
            )
            self.assertTrue(result.success, result.error)

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def query(self, target, *, index="HNSW", metric="cosine", k=3, extra=""):
        return self.engine.run(
            "SELECT id, nombre, SIMILARITY_SCORE() AS score FROM fotos "
            f"WHERE SIMILAR_TO({target}, k={k}) "
            f"USING {index} WITH METRIC={metric}{extra}"
        )

    def expected_ids(self, target, k=3):
        path = target.strip("'")
        query_vector = ExtractFeatures.extract(
            path,
            media_root=self.engine.media_dir,
            model_root=self.engine.model_dir,
        ).values
        ranking = []
        for _, row in self.engine.catalog.get_table("fotos").storage.scan():
            vector = parse_vector(dict(row)["embedding"])
            ranking.append((dict(row)["id"], cosine_similarity(query_vector, vector)))
        ranking.sort(key=lambda item: (-item[1], item[0]))
        return [doc_id for doc_id, _ in ranking[:k]]

    def test_hnsw_consulta_por_archivo_y_plan(self):
        result = self.query("'consulta.png'")
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.rows[0]["id"], 1)
        details = result.execution_plan["steps"][0]["details"]
        self.assertEqual(details["query_source"], "file")
        self.assertEqual(details["media_kind"], "image")
        self.assertEqual(details["media_file"], "consulta.png")
        self.assertEqual(details["dimension"], self.image_model.n_words)
        self.assertEqual(details["n_words"], self.image_model.n_words)
        self.assertEqual(details["feature_mode"], "bow")
        self.assertGreater(details["extract_ms"], 0)

    def test_ivf_consulta_por_archivo(self):
        result = self.query("'consulta.png'", index="IVF")
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.rows[0]["id"], 1)
        self.assertEqual(result.execution_plan["access_path"], "IVF_KNN")
        self.assertEqual(result.execution_plan["steps"][0]["details"]["query_source"], "file")

    def test_coincide_con_la_fuerza_bruta(self):
        result = self.query("'consulta.png'", k=3)
        self.assertTrue(result.success, result.error)
        self.assertEqual(
            [row["id"] for row in result.rows],
            self.expected_ids("'consulta.png'", k=3),
        )

    def test_hnsw_e_ivf_dan_el_mismo_orden(self):
        hnsw = self.query("'consulta.png'", index="HNSW")
        ivf = self.query("'consulta.png'", index="IVF")
        self.assertTrue(hnsw.success and ivf.success)
        self.assertEqual([row["id"] for row in hnsw.rows], [row["id"] for row in ivf.rows])

    def test_nombre_con_espacios(self):
        _bars(
            os.path.join(self.engine.media_dir, "consulta espacios.png"),
            (190, 25, 25),
            offset=2,
        )
        result = self.query("'consulta espacios.png'", k=2)
        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.execution_plan["steps"][0]["details"]["media_file"],
            "consulta espacios.png",
        )

    def test_ruta_absoluta(self):
        absolute = os.path.join(self.engine.media_dir, "consulta.png")
        result = self.query(f"'{absolute}'", k=2)
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.rows[0]["id"], 1)
        self.assertEqual(
            result.execution_plan["steps"][0]["details"]["media_file"], "consulta.png"
        )

    def test_sintaxis_del_enunciado_con_jpg(self):
        _bars(
            os.path.join(self.engine.media_dir, "foto.jpg"),
            (185, 22, 22),
            offset=1,
        )
        result = self.query("'foto.jpg'", k=2)
        self.assertTrue(result.success, result.error)
        self.assertEqual(
            result.execution_plan["steps"][0]["details"]["media_file"], "foto.jpg"
        )

    def test_archivo_inexistente(self):
        result = self.query("'no-existe.jpg'")
        self.assertFalse(result.success)
        self.assertIn("no se encontró", result.error or "")

    def test_dimension_incompatible_con_archivo(self):
        self.assertTrue(self.engine.run(
            "CREATE TABLE chicos (id INT PRIMARY KEY, embedding VARCHAR(100))"
        ).success)
        self.engine.run("INSERT INTO chicos VALUES (1, '[1, 0]')")
        result = self.engine.run(
            "SELECT * FROM chicos WHERE SIMILAR_TO('consulta.png', k=2) USING HNSW"
        )
        self.assertFalse(result.success)
        self.assertIn(f"dimensión {self.image_model.n_words}", result.error or "")
        self.assertIn("dimensión 2", result.error or "")

    def test_order_by_score_y_select_estrella(self):
        result = self.engine.run(
            "SELECT *, SIMILARITY_SCORE() AS relevancia FROM fotos "
            "WHERE SIMILAR_TO('consulta.png', k=3) "
            "USING HNSW WITH METRIC=cosine ORDER BY relevancia DESC"
        )
        self.assertTrue(result.success, result.error)
        scores = [row["relevancia"] for row in result.rows]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertIn("embedding", result.columns)

    def test_explain_no_construye_el_indice_pero_muestra_la_extraccion(self):
        result = self.engine.run(
            "EXPLAIN SELECT id FROM fotos "
            "WHERE SIMILAR_TO('consulta.png', k=2) USING HNSW WITH METRIC=cosine"
        )
        self.assertTrue(result.success, result.error)
        details = result.execution_plan["steps"][0]["details"]
        self.assertEqual(details["query_source"], "file")
        self.assertEqual(details["media_kind"], "image")
        self.assertEqual(details["n_words"], self.image_model.n_words)
        self.assertEqual(details["build_ms"], 0.0)


class TestSimilarToPorAudio(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-media-audio-sql-")
        self.engine = _Engine(self._dir)
        self.audio_files = [
            _wav(os.path.join(self.engine.media_dir, "tono_440.wav"), 440.0),
            _wav(os.path.join(self.engine.media_dir, "tono_440_b.wav"), 440.0, phase=1.0),
            _wav(os.path.join(self.engine.media_dir, "tono_880.wav"), 880.0),
        ]
        _wav(os.path.join(self.engine.media_dir, "consulta_440.wav"), 440.0, phase=0.5)
        self.audio_model = self.engine.train("audio", self.audio_files, 4)

        self.assertTrue(self.engine.run(
            "CREATE TABLE audios (id INT PRIMARY KEY, nombre VARCHAR(64), "
            "embedding VARCHAR(2048), categoria VARCHAR(16))"
        ).success)
        for doc_id, name, category in [
            (1, "tono_440.wav", "440"),
            (2, "tono_440_b.wav", "440"),
            (3, "tono_880.wav", "880"),
        ]:
            result = self.engine.run(
                f"INSERT INTO audios VALUES ({doc_id}, '{name}', "
                f"EXTRACT_FEATURES('{name}'), '{category}')"
            )
            self.assertTrue(result.success, result.error)

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_consulta_wav_con_ivf(self):
        result = self.engine.run(
            "SELECT id, nombre, categoria, SIMILARITY_SCORE() AS score FROM audios "
            "WHERE SIMILAR_TO('consulta_440.wav', k=2) "
            "USING IVF WITH METRIC=cosine"
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual({row["categoria"] for row in result.rows}, {"440"})
        details = result.execution_plan["steps"][0]["details"]
        self.assertEqual(details["query_source"], "file")
        self.assertEqual(details["media_kind"], "audio")
        self.assertEqual(details["dimension"], self.audio_model.n_words)
        self.assertEqual(details["n_words"], self.audio_model.n_words)


class TestExtractFeaturesEnSql(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-media-insert-")
        self.engine = _Engine(self._dir)
        self.image_files = [
            _bars(os.path.join(self.engine.media_dir, "rojo.png"), (180, 20, 20)),
            _checker(os.path.join(self.engine.media_dir, "azul.png"), (20, 20, 180)),
        ]
        self.image_model = self.engine.train("image", self.image_files, 4)
        self.assertTrue(self.engine.run(
            "CREATE TABLE fotos (id INT PRIMARY KEY, nombre VARCHAR(64), "
            "embedding VARCHAR(4096))"
        ).success)

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_insert_con_tipo_explicito(self):
        result = self.engine.run(
            "INSERT INTO fotos VALUES (1, 'rojo.png', "
            "EXTRACT_FEATURES('rojo.png', 'image'))"
        )
        self.assertTrue(result.success, result.error)
        row = self.engine.run("SELECT embedding FROM fotos WHERE id = 1").rows[0]
        self.assertEqual(len(parse_vector(row["embedding"])), self.image_model.n_words)

    def test_update_reindexa_el_vector(self):
        self.engine.run(
            "INSERT INTO fotos VALUES (1, 'rojo.png', EXTRACT_FEATURES('rojo.png'))"
        )
        self.engine.run(
            "UPDATE fotos SET embedding = EXTRACT_FEATURES('azul.png') WHERE id = 1"
        )
        result = self.engine.run(
            "SELECT id, SIMILARITY_SCORE() AS score FROM fotos "
            "WHERE SIMILAR_TO('azul.png', k=1) USING HNSW WITH METRIC=cosine"
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.rows[0]["id"], 1)
        self.assertAlmostEqual(result.rows[0]["score"], 1.0, places=4)

    def test_archivo_inexistente_en_insert(self):
        result = self.engine.run(
            "INSERT INTO fotos VALUES (2, 'x.png', EXTRACT_FEATURES('x.png'))"
        )
        self.assertFalse(result.success)
        self.assertIn("EXTRACT_FEATURES", result.error or "")
        self.assertIn("no se encontró", result.error or "")

    def test_sin_vocabulario_da_error_claro(self):
        shutil.rmtree(self.engine.model_dir, ignore_errors=True)
        result = self.engine.run(
            "INSERT INTO fotos VALUES (3, 'rojo.png', EXTRACT_FEATURES('rojo.png'))"
        )
        self.assertFalse(result.success)
        self.assertIn("no hay vocabulario", result.error or "")


if __name__ == "__main__":
    unittest.main()
