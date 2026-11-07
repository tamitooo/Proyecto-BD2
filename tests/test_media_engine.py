"""Pruebas del puente API → BoVW/TF-IDF (#107 / 2.4.1).

No levanta uvicorn: valida la función que usa ``POST /api/media/extract`` y el
comportamiento del directorio de medios/modelos del ``DemoEngine``.
"""

import io
import os
import shutil
import unittest
import uuid
import wave

import numpy as np
from PIL import Image, ImageDraw

from backend.engine import DemoEngine
from vector.bow import model_path, train_model
from vector.extract_features import ExtractFeatures, FeatureExtractionError


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _temp_dir(prefix):
    base = os.environ.get("BD2_TEST_DIR") or os.path.join(_REPO_ROOT, ".bd2-tests")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"{prefix}{uuid.uuid4().hex}")
    os.makedirs(path)
    return path


def _bars_image(color=(180, 20, 20), *, offset=0) -> Image.Image:
    image = Image.new("RGB", (96, 96), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for index in range(4):
        y = 10 + index * 20 + offset
        draw.rectangle((8, y, 88, y + 8), fill=color)
    return image


def _checker_image(color=(20, 20, 180)) -> Image.Image:
    image = Image.new("RGB", (96, 96), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for y in range(0, 96, 12):
        for x in range(0, 96, 12):
            if (x // 12 + y // 12) % 2 == 0:
                draw.rectangle((x, y, x + 11, y + 11), fill=color)
    return image


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _wav_bytes(frequency: float = 440.0, *, phase: float = 0.0) -> bytes:
    buffer = io.BytesIO()
    rate = 16000
    samples = (
        0.5 * np.sin(2 * np.pi * frequency * np.arange(rate // 2) / rate + phase)
        * 32767
    ).astype(np.int16)
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return buffer.getvalue()


def _train(engine: DemoEngine, kind: str, paths, n_words: int):
    documents = [
        ExtractFeatures.local_descriptors(path, kind=kind) for path in paths
    ]
    model = train_model(kind, documents, n_words, seed=7)
    model.save(model_path(engine.model_dir, kind))
    return model


class TestMediaEngine(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-api-media-")
        self.engine = DemoEngine(data_dir=self._dir, seed=False)
        os.makedirs(self.engine.media_dir, exist_ok=True)

        self.base_image = os.path.join(self.engine.media_dir, "base.png")
        _bars_image().save(self.base_image)
        self.image_model = _train(
            self.engine, "image", [self.base_image], 4
        )

        self.base_audio = os.path.join(self.engine.media_dir, "base.wav")
        with open(self.base_audio, "wb") as handle:
            handle.write(_wav_bytes())
        self.audio_model = _train(
            self.engine, "audio", [self.base_audio], 4
        )

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_extrae_y_guarda_en_media(self):
        with open(self.base_image, "rb") as handle:
            content = handle.read()
        result = self.engine.extract_media(filename="base.png", content=content)
        self.assertEqual(result["name"], "base.png")
        self.assertEqual(result["kind"], "image")
        self.assertEqual(result["mode"], "bow")
        self.assertEqual(result["dimension"], self.image_model.n_words)
        self.assertEqual(len(result["vector"]), self.image_model.n_words)
        self.assertTrue(os.path.isfile(os.path.join(self.engine.media_dir, "base.png")))
        self.assertGreater(result["elapsed_ms"], 0)

    def test_mismo_archivo_reutiliza_el_nombre(self):
        content = _png_bytes(_bars_image((200, 30, 30)))
        first = self.engine.extract_media(filename="foto.png", content=content)
        second = self.engine.extract_media(filename="foto.png", content=content)
        self.assertEqual(first["path"], second["path"])

    def test_contenido_distinto_no_pisa_el_archivo(self):
        first = self.engine.extract_media(
            filename="foto.png", content=_png_bytes(_bars_image())
        )
        second = self.engine.extract_media(
            filename="foto.png", content=_png_bytes(_checker_image())
        )
        self.assertNotEqual(first["name"], second["name"])
        self.assertTrue(os.path.isfile(first["path"]))
        self.assertTrue(os.path.isfile(second["path"]))

    def test_archivo_invalido_no_queda_en_media(self):
        with self.assertRaises(FeatureExtractionError):
            self.engine.extract_media(
                filename="roto.png", content=b"no es una imagen"
            )
        self.assertFalse(
            os.path.exists(os.path.join(self.engine.media_dir, "roto.png"))
        )

    def test_flujo_del_panel_hasta_la_consulta(self):
        content = _png_bytes(_bars_image((185, 22, 22)))
        info = self.engine.extract_media(filename="consulta.png", content=content)
        self.assertTrue(self.engine.run(
            "CREATE TABLE fotos (id INT PRIMARY KEY, nombre VARCHAR(64), "
            "embedding VARCHAR(4096))"
        ).success)
        self.assertTrue(self.engine.run(
            f"INSERT INTO fotos VALUES (1, '{info['name']}', "
            f"EXTRACT_FEATURES('{info['name']}'))"
        ).success)

        result = self.engine.run(
            "SELECT id, nombre, SIMILARITY_SCORE() AS score FROM fotos "
            f"WHERE SIMILAR_TO('{info['name']}', k=1) "
            "USING HNSW WITH METRIC=cosine"
        )
        self.assertTrue(result.success, result.error)
        self.assertEqual(result.rows[0]["id"], 1)
        details = result.execution_plan["steps"][0]["details"]
        self.assertEqual(details["query_source"], "file")
        self.assertEqual(details["n_words"], self.image_model.n_words)

    def test_audio_wav_por_el_mismo_endpoint(self):
        result = self.engine.extract_media(
            filename="tono.wav", content=_wav_bytes(440.0)
        )
        self.assertEqual(result["kind"], "audio")
        self.assertEqual(result["mode"], "bow")
        self.assertEqual(result["dimension"], self.audio_model.n_words)

    def test_sin_modelo_da_error_claro(self):
        shutil.rmtree(self.engine.model_dir, ignore_errors=True)
        with self.assertRaisesRegex(FeatureExtractionError, "no hay vocabulario"):
            self.engine.extract_media(
                filename="foto.png",
                content=_png_bytes(_bars_image()),
            )


if __name__ == "__main__":
    unittest.main()
