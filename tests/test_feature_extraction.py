"""Pruebas de la pipeline 2.4.1: SIFT/MFCC → BoVW → TF-IDF.

Se valida:

* SIFT denso (128 dimensiones) y MFCC por trama (20 dimensiones);
* K-Means y vocabulario persistido;
* histograma de K palabras, IDF y normalización L2;
* separación de contenido: patrones similares se parecen más que patrones
  distintos; 440 Hz se parece más a 440 Hz que a 880 Hz;
* errores claros cuando falta el vocabulario o el archivo.
"""

import json
import math
import os
import shutil
import unittest
import uuid
import wave

from vector.bow import FeatureModel, model_path, train_model
from vector.extract_features import ExtractFeatures, FeatureExtractionError
from vector.metrics import cosine_similarity
from vector.sift import sift_backend

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    np = None
    Image = None
    ImageDraw = None


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


@unittest.skipUnless(np is not None and Image is not None, "requiere Pillow y numpy")
class TestExtraccionLocal(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-bow-local-")

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def path(self, name):
        return os.path.join(self._dir, name)

    def test_sift_backend_disponible(self):
        self.assertIn(sift_backend(), {"opencv", "dense"})

    def test_sift_128_dimensiones_y_determinista(self):
        path = _bars(self.path("barras.png"), (180, 20, 20))
        first = ExtractFeatures.local_descriptors(path, kind="image")
        second = ExtractFeatures.local_descriptors(path, kind="image")
        self.assertEqual(first.ndim, 2)
        self.assertEqual(first.shape[1], 128)
        self.assertGreater(first.shape[0], 0)
        self.assertTrue(np.array_equal(first, second))
        for descriptor in first[:5]:
            self.assertAlmostEqual(float(np.linalg.norm(descriptor)), 1.0, places=5)

    def test_sift_imagen_lisa_no_tiene_descriptores(self):
        path = self.path("lisa.png")
        Image.new("RGB", (96, 96), (200, 20, 20)).save(path)
        descriptors = ExtractFeatures.local_descriptors(path, kind="image")
        self.assertEqual(descriptors.shape, (0, 128))

    def test_mfcc_por_trama(self):
        path = _wav(self.path("tono.wav"), 440.0)
        frames = ExtractFeatures.local_descriptors(path, kind="audio")
        self.assertEqual(frames.ndim, 2)
        self.assertEqual(frames.shape[1], 20)
        self.assertGreater(frames.shape[0], 0)
        self.assertTrue(np.isfinite(frames).all())

    def test_resuelve_media_root(self):
        media = self.path("media")
        os.makedirs(media)
        _bars(os.path.join(media, "foto.png"), (180, 20, 20))
        descriptors = ExtractFeatures.local_descriptors(
            "foto.png", kind="image", media_root=media
        )
        self.assertGreater(descriptors.shape[0], 0)

    def test_archivo_inexistente(self):
        with self.assertRaisesRegex(FeatureExtractionError, "no se encontró"):
            ExtractFeatures.local_descriptors(self.path("no-existe.jpg"))

    def test_formato_no_soportado(self):
        with self.assertRaisesRegex(FeatureExtractionError, "no está soportado"):
            ExtractFeatures.local_descriptors(self.path("video.mp4"))

    @unittest.skipIf(shutil.which("ffmpeg"), "ffmpeg está disponible")
    def test_mp3_sin_ffmpeg_da_error_claro(self):
        path = self.path("audio.mp3")
        with open(path, "wb") as handle:
            handle.write(b"ID3\x03\x00\x00\x00\x00\x00\x00")
        with self.assertRaisesRegex(FeatureExtractionError, "ffmpeg"):
            ExtractFeatures.local_descriptors(path)

    def test_imagen_corrupta(self):
        path = self.path("rota.png")
        with open(path, "wb") as handle:
            handle.write(b"esto no es una imagen")
        with self.assertRaisesRegex(FeatureExtractionError, "no se pudo calcular SIFT"):
            ExtractFeatures.local_descriptors(path)


@unittest.skipUnless(np is not None and Image is not None, "requiere Pillow y numpy")
class TestModeloBoVW(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = _temp_dir("bd2-bow-model-")
        cls.media = os.path.join(cls._dir, "media")
        cls.models = os.path.join(cls._dir, "models")
        os.makedirs(cls.media)
        cls.image_files = [
            _bars(os.path.join(cls.media, "barras.png"), (180, 20, 20)),
            _bars(
                os.path.join(cls.media, "barras_2.png"),
                (200, 30, 30),
                width=9,
                offset=3,
            ),
            _checker(os.path.join(cls.media, "cuadros.png"), (20, 20, 180)),
            _rings(os.path.join(cls.media, "anillos.png"), (20, 150, 30)),
        ]
        cls.query_bars = _bars(
            os.path.join(cls.media, "consulta_barras.png"),
            (190, 25, 25),
            offset=1,
        )
        cls.query_checker = _checker(
            os.path.join(cls.media, "consulta_cuadros.png"), (25, 25, 190)
        )
        cls.audio_files = [
            _wav(os.path.join(cls.media, "440.wav"), 440.0),
            _wav(os.path.join(cls.media, "440_b.wav"), 440.0, phase=1.0),
            _wav(os.path.join(cls.media, "880.wav"), 880.0),
        ]
        cls.query_audio = _wav(
            os.path.join(cls.media, "consulta_440.wav"), 440.0, phase=0.5
        )

        image_documents = [
            ExtractFeatures.local_descriptors(path, kind="image")
            for path in cls.image_files
        ]
        cls.image_model = train_model(
            "image",
            image_documents,
            8,
            seed=7,
            descriptor_backend=sift_backend(),
        )
        cls.image_model.save(model_path(cls.models, "image"))

        audio_documents = [
            ExtractFeatures.local_descriptors(path, kind="audio")
            for path in cls.audio_files
        ]
        cls.audio_model = train_model(
            "audio", audio_documents, 4, seed=7
        )
        cls.audio_model.save(model_path(cls.models, "audio"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls._dir, ignore_errors=True)

    def extract(self, path, kind):
        return ExtractFeatures.extract(
            path, kind=kind, model_root=self.models
        )

    def test_vector_k_normalizado_y_determinista(self):
        first = self.extract(self.query_bars, "image")
        second = self.extract(self.query_bars, "image")
        self.assertEqual(first.kind, "image")
        self.assertEqual(first.mode, "bow")
        self.assertEqual(first.dimension, self.image_model.n_words)
        self.assertEqual(first.values, second.values)
        self.assertAlmostEqual(math.hypot(*first.values), 1.0, places=4)
        self.assertTrue(all(math.isfinite(value) for value in first.values))

    def test_histograma_tiene_k_palabras(self):
        descriptors = ExtractFeatures.local_descriptors(
            self.query_bars, kind="image"
        )
        histogram = self.image_model.histogram(descriptors)
        self.assertEqual(histogram.shape, (self.image_model.n_words,))
        self.assertEqual(int(histogram.sum()), descriptors.shape[0])

    def test_idf_una_entrada_por_palabra(self):
        self.assertEqual(self.image_model.idf.shape, (self.image_model.n_words,))
        self.assertTrue((self.image_model.idf > 0).all())
        self.assertGreaterEqual(self.image_model.n_documents, 4)

    def test_patrones_similares_se_parecen_mas(self):
        query = self.extract(self.query_bars, "image").values
        bars = self.extract(self.image_files[0], "image").values
        checker = self.extract(self.image_files[2], "image").values
        self.assertGreater(
            cosine_similarity(query, bars),
            cosine_similarity(query, checker) + 0.2,
        )

    def test_audio_misma_frecuencia_se_parece_mas(self):
        query = self.extract(self.query_audio, "audio").values
        same = self.extract(self.audio_files[0], "audio").values
        different = self.extract(self.audio_files[2], "audio").values
        self.assertGreater(
            cosine_similarity(query, same),
            cosine_similarity(query, different) + 0.2,
        )

    def test_modelo_save_load(self):
        loaded = FeatureModel.load(model_path(self.models, "image"))
        self.assertEqual(loaded.n_words, self.image_model.n_words)
        self.assertEqual(loaded.descriptor_dim, self.image_model.descriptor_dim)
        self.assertEqual(
            loaded.descriptor_backend, self.image_model.descriptor_backend
        )
        self.assertTrue(np.allclose(loaded.centroids, self.image_model.centroids))
        self.assertTrue(np.allclose(loaded.idf, self.image_model.idf))
        descriptors = ExtractFeatures.local_descriptors(
            self.query_bars, kind="image"
        )
        self.assertTrue(
            np.allclose(
                loaded.encode(descriptors),
                self.image_model.encode(descriptors),
            )
        )

    def test_sin_vocabulario_da_error_claro(self):
        empty = os.path.join(self._dir, "sin_modelos")
        with self.assertRaisesRegex(FeatureExtractionError, "no hay vocabulario"):
            ExtractFeatures.extract(
                self.query_bars, kind="image", model_root=empty
            )

    def test_json_tiene_k_valores(self):
        features = self.extract(self.query_bars, "image")
        payload = json.loads(features.to_json())
        self.assertEqual(len(payload), features.dimension)
        self.assertEqual(features.dimension, self.image_model.n_words)


if __name__ == "__main__":
    unittest.main()
