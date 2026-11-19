"""Pruebas de la fuente visual de Persona 3 (issues g, h y p).

Cubren:

* recomendación desde el embedding guardado del producto X, sin incluir X;
* contrato ``{producto_id, score}`` ordenado y con score mayor-es-mejor;
* búsqueda desde una imagen nueva con ``EXTRACT_FEATURES`` + ``SIMILAR_TO``;
* IVF persistente y errores claros.
"""

from __future__ import annotations

import os
import shutil
import unittest
import uuid

from PIL import Image, ImageDraw

from backend.engine import DemoEngine
from recommender import (
    create_schema,
    product_embedding,
    recommend_by_visual,
    search_by_image,
)
from recommender.sql import RecommenderError
from vector.bow import model_path, train_model
from vector.extract_features import ExtractFeatures


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _temp_dir(prefix: str) -> str:
    base = os.environ.get("BD2_TEST_DIR") or os.path.join(_ROOT, ".bd2-tests")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, prefix + uuid.uuid4().hex)
    os.makedirs(path)
    return path


def _bars(path: str, *, offset: int = 0) -> str:
    image = Image.new("RGB", (96, 96), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for index in range(4):
        y = 10 + index * 20 + offset
        draw.rectangle((8, y, 88, y + 8), fill=(30, 30, 30))
    image.save(path)
    return path


def _checker(path: str) -> str:
    image = Image.new("RGB", (96, 96), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for y in range(0, 96, 12):
        for x in range(0, 96, 12):
            if (x // 12 + y // 12) % 2 == 0:
                draw.rectangle((x, y, x + 11, y + 11), fill=(30, 30, 30))
    image.save(path)
    return path


def _rings(path: str) -> str:
    image = Image.new("RGB", (96, 96), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for radius in range(10, 50, 10):
        draw.ellipse(
            (48 - radius, 48 - radius, 48 + radius, 48 + radius),
            outline=(30, 30, 30),
            width=4,
        )
    image.save(path)
    return path


def _product_sql(product_id: int, name: str, vector: str) -> str:
    return (
        f"INSERT INTO productos VALUES ({product_id}, '{name}', 'test', 1.0, "
        f"'descripcion', 'imagen.png', '{vector}')"
    )


class TestVisualDesdeProducto(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-visual-")
        self.engine = DemoEngine(data_dir=self._dir, seed=False)
        create_schema(self.engine)
        for product_id, vector in {
            1: "[1.0, 0.0]",
            2: "[0.9, 0.1]",
            3: "[0.0, 1.0]",
            4: "[-1.0, 0.0]",
        }.items():
            self.engine.run(_product_sql(product_id, f"Producto {product_id}", vector))
        result = self.engine.run(
            "CREATE INDEX idx_productos_embedding ON productos (embedding) "
            "USING IVF WITH METRIC=cosine"
        )
        self.assertTrue(result.success, result.error)

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_recomienda_vecinos_y_excluye_x(self):
        result = recommend_by_visual(self.engine, 1, k=3)
        ids = [item.producto_id for item in result]
        self.assertEqual(ids, [2, 3, 4])
        self.assertNotIn(1, ids)
        self.assertTrue(all(item.fuente == "visual" for item in result))
        self.assertEqual(result, sorted(result, key=lambda item: (-item.score, item.producto_id)))

    def test_score_en_rango_y_evidencia(self):
        for item in recommend_by_visual(self.engine, 1, k=3):
            self.assertGreaterEqual(item.score, 0.0)
            self.assertLessEqual(item.score, 1.0)
            self.assertIn("score_motor", item.evidencia)
            self.assertEqual(item.evidencia["modo"], "producto")

    def test_respeta_k_y_k_cero(self):
        self.assertEqual(len(recommend_by_visual(self.engine, 1, k=2)), 2)
        self.assertEqual(recommend_by_visual(self.engine, 1, k=0), [])

    def test_producto_sin_embedding_devuelve_vacio(self):
        self.engine.run(
            "INSERT INTO productos VALUES (5, 'Sin vector', 'test', 1.0, 'x', 'x.png', '')"
        )
        self.assertEqual(recommend_by_visual(self.engine, 5), [])
        self.assertIsNone(product_embedding(self.engine, 5))

    def test_producto_inexistente_devuelve_vacio(self):
        self.assertEqual(recommend_by_visual(self.engine, 999), [])

    def test_embedding_se_lee_como_json(self):
        self.assertEqual(product_embedding(self.engine, 1), (1.0, 0.0))

    def test_metrica_invalida(self):
        with self.assertRaises(ValueError):
            recommend_by_visual(self.engine, 1, metric="manhattan")


class TestBusquedaPorImagen(unittest.TestCase):
    def setUp(self):
        self._dir = _temp_dir("bd2-visual-upload-")
        self.media = os.path.join(self._dir, "media")
        self.models = os.path.join(self._dir, "models")
        os.makedirs(self.media)

        products = [
            _bars(os.path.join(self.media, "barras.png")),
            _bars(os.path.join(self.media, "barras_2.png"), offset=2),
            _checker(os.path.join(self.media, "cuadros.png")),
            _rings(os.path.join(self.media, "anillos.png")),
        ]
        documents = [
            ExtractFeatures.local_descriptors(path, kind="image") for path in products
        ]
        model = train_model("image", documents, 8, seed=7, descriptor_backend="dense")
        model.save(model_path(self.models, "image"))

        self.engine = DemoEngine(data_dir=self._dir, seed=False)
        create_schema(self.engine)
        for index, name in enumerate(
            ["barras.png", "barras_2.png", "cuadros.png", "anillos.png"], start=1
        ):
            result = self.engine.run(
                f"INSERT INTO productos VALUES ({index}, '{name}', 'test', 1.0, "
                f"'x', '{name}', EXTRACT_FEATURES('{name}', 'image'))"
            )
            self.assertTrue(result.success, result.error)
        result = self.engine.run(
            "CREATE INDEX idx_productos_embedding ON productos (embedding) "
            "USING IVF WITH METRIC=cosine"
        )
        self.assertTrue(result.success, result.error)
        self.query_image = _bars(os.path.join(self.media, "consulta.png"))

    def tearDown(self):
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_busca_por_imagen_y_devuelve_top(self):
        result = search_by_image(
            self.engine,
            self.query_image,
            k=2,
            media_root=self.media,
            model_root=self.models,
        )
        self.assertTrue(result)
        self.assertEqual(result[0].producto_id, 1)
        self.assertTrue(all(item.fuente == "visual" for item in result))
        self.assertTrue(all(item.evidencia["modo"] == "imagen" for item in result))
        self.assertEqual(
            result,
            sorted(result, key=lambda item: (-item.score, item.producto_id)),
        )

    def test_imagen_sin_modelo_da_error_claro(self):
        with self.assertRaisesRegex(RecommenderError, "vocabulario"):
            search_by_image(
                self.engine,
                self.query_image,
                media_root=self.media,
                model_root=os.path.join(self._dir, "sin_modelo"),
            )


if __name__ == "__main__":
    unittest.main()
