"""Pruebas de las fuentes de la Persona 4 (issues i, j, k y p).

La muestra es determinista y su estructura está documentada en
``recommender/fixture.py``; por eso los valores esperados se escriben como
constantes y no como "lo que devolvió el motor".
"""

from __future__ import annotations

import os
import shutil
import unittest
import uuid

from backend.engine import DemoEngine
from recommender import (
    DDL,
    create_schema,
    recommend_by_copurchase,
    recommend_by_metadata,
    stores_with_product,
)
from recommender.fixture import SAMPLE, load_sample
from recommender.sql import RecommenderError, literal
from recommender.stores import availability_score
from spatial.geo import haversine

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CENTRO = (-12.0464, -77.0428)


def _new_engine():
    base = os.environ.get("BD2_TEST_DIR") or os.path.join(_ROOT, ".bd2-tests")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, "p5-" + uuid.uuid4().hex)
    os.makedirs(path)
    engine = DemoEngine(data_dir=path, seed=False)
    create_schema(engine)
    load_sample(engine)
    return engine, path


class _ConMotor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine, cls.path = _new_engine()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.path, ignore_errors=True)


class TestEsquemaYFixture(_ConMotor):
    def test_crea_las_cuatro_tablas_del_contrato(self):
        for table in DDL:
            self.assertTrue(self.engine.catalog.has_table(table), table)

    def test_columnas_del_contrato(self):
        tabla = self.engine.catalog.get_table("productos")
        self.assertEqual(
            [field.name for field in tabla.schema.fields],
            ["id", "nombre", "categoria", "precio", "descripcion", "imagen", "embedding"],
        )

    def test_muestra_tiene_una_fila_por_usuario_y_producto(self):
        pares = [(row[1], row[2]) for row in SAMPLE["compras"]]
        self.assertEqual(len(pares), len(set(pares)))

    def test_cargar_dos_veces_no_duplica(self):
        engine, path = _new_engine()
        try:
            second = load_sample(engine)
            self.assertEqual(second, {"productos": 0, "tiendas": 0, "stock": 0, "compras": 0})
        finally:
            shutil.rmtree(path, ignore_errors=True)


class TestCoCompra(_ConMotor):
    def test_productos_y_puntajes_esperados(self):
        result = recommend_by_copurchase(self.engine, 1, k=10)
        self.assertEqual([item.producto_id for item in result], [2, 3, 4])
        self.assertAlmostEqual(result[0].score, 3 / 6)
        self.assertAlmostEqual(result[1].score, 3 / 6)
        self.assertAlmostEqual(result[2].score, 2 / 6)

    def test_no_incluye_el_producto_de_consulta(self):
        result = recommend_by_copurchase(self.engine, 1, k=10)
        self.assertNotIn(1, [item.producto_id for item in result])

    def test_excluye_el_historial_del_usuario(self):
        result = recommend_by_copurchase(self.engine, 1, k=10, usuario_id=1)
        self.assertEqual([item.producto_id for item in result], [4])

    def test_limita_compradores_y_lo_declara_en_la_evidencia(self):
        result = recommend_by_copurchase(self.engine, 1, k=10, max_buyers=2)
        self.assertEqual([item.producto_id for item in result], [2, 3])
        self.assertAlmostEqual(result[0].score, 1.0)
        self.assertEqual(result[0].evidencia["compradores_usados"], 2)
        self.assertEqual(result[0].evidencia["compradores_totales"], 6)

    def test_producto_sin_compras_devuelve_lista_vacia(self):
        self.assertEqual(recommend_by_copurchase(self.engine, 9), [])
        self.assertEqual(recommend_by_copurchase(self.engine, 999), [])

    def test_respeta_k(self):
        self.assertEqual(len(recommend_by_copurchase(self.engine, 1, k=2)), 2)
        self.assertEqual(recommend_by_copurchase(self.engine, 1, k=0), [])


class TestMetadatos(_ConMotor):
    def test_ordena_por_cercania_de_precio_dentro_de_la_categoria(self):
        result = recommend_by_metadata(self.engine, 1, k=10)
        self.assertEqual([item.producto_id for item in result], [6, 2, 7, 3, 4, 5])
        self.assertAlmostEqual(result[0].score, 1.0 / (1.0 + 50.0 / 2500.0))

    def test_solo_devuelve_la_misma_categoria(self):
        result = recommend_by_metadata(self.engine, 1, k=10)
        self.assertTrue(all(item.evidencia["categoria"] == "Laptops" for item in result))

    def test_no_incluye_el_producto_de_consulta(self):
        result = recommend_by_metadata(self.engine, 1, k=10)
        self.assertNotIn(1, [item.producto_id for item in result])

    def test_producto_inexistente_devuelve_lista_vacia(self):
        self.assertEqual(recommend_by_metadata(self.engine, 999), [])

    def test_respeta_k(self):
        self.assertEqual(len(recommend_by_metadata(self.engine, 1, k=3)), 3)


class TestTiendasCercanas(_ConMotor):
    def test_solo_tiendas_en_el_radio_con_stock(self):
        stores = stores_with_product(self.engine, 1, _CENTRO, radius_m=3000)
        self.assertEqual([store.tienda_id for store in stores], [1, 2])
        self.assertEqual([store.cantidad for store in stores], [5, 2])

    def test_excluye_stock_cero(self):
        stores = stores_with_product(self.engine, 1, _CENTRO, radius_m=3000)
        self.assertNotIn(4, [store.tienda_id for store in stores])

    def test_producto_solo_en_tienda_lejana(self):
        self.assertEqual(stores_with_product(self.engine, 2, _CENTRO, radius_m=3000), [])
        self.assertEqual(
            [store.tienda_id for store in stores_with_product(self.engine, 2, _CENTRO, radius_m=40000)],
            [3],
        )

    def test_distancia_coincide_con_haversine(self):
        stores = stores_with_product(self.engine, 1, _CENTRO, radius_m=3000)
        esperado = haversine(_CENTRO, (-12.0364, -77.0428))
        self.assertAlmostEqual(stores[1].distancia_m, esperado, places=3)

    def test_respeta_limit(self):
        stores = stores_with_product(self.engine, 1, _CENTRO, radius_m=3000, limit=1)
        self.assertEqual([store.tienda_id for store in stores], [1])

    def test_radio_invalido(self):
        with self.assertRaises(ValueError):
            stores_with_product(self.engine, 1, _CENTRO, radius_m=0)
        with self.assertRaises(ValueError):
            stores_with_product(self.engine, 1, (200.0, 0.0))

    def test_puntaje_de_disponibilidad(self):
        stores = stores_with_product(self.engine, 1, _CENTRO, radius_m=3000)
        self.assertAlmostEqual(availability_score(stores), 1.0)
        self.assertEqual(availability_score([]), 0.0)


class TestContratoDeSalida(_ConMotor):
    def test_puntajes_positivos_acotados_y_ordenados(self):
        for result in (
            recommend_by_copurchase(self.engine, 1, k=10),
            recommend_by_metadata(self.engine, 1, k=10),
        ):
            self.assertTrue(result)
            for item in result:
                self.assertGreater(item.score, 0.0)
                self.assertLessEqual(item.score, 1.0)
            scores = [item.score for item in result]
            self.assertEqual(scores, sorted(scores, reverse=True))

    def test_formato_para_la_fusion(self):
        item = recommend_by_copurchase(self.engine, 1, k=1)[0]
        payload = item.as_dict()
        self.assertEqual(set(payload), {"producto_id", "score", "fuente", "evidencia"})
        self.assertEqual(payload["fuente"], "co_compra")

    def test_literal_escapa_comillas(self):
        self.assertEqual(literal("O'Brien"), "'O''Brien'")
        with self.assertRaises(RecommenderError):
            literal(float("nan"))


class TestCategoriaConComilla(unittest.TestCase):
    """La categoría viaja dentro del SQL: debe sobrevivir a un apóstrofo."""

    @classmethod
    def setUpClass(cls):
        cls.engine, cls.path = _new_engine()
        cls.engine.run(
            "INSERT INTO productos VALUES (100, 'Producto A', 'O''Brien', 10.0, "
            "'descripcion a', 'a.jpg', '')"
        )
        cls.engine.run(
            "INSERT INTO productos VALUES (101, 'Producto B', 'O''Brien', 12.0, "
            "'descripcion b', 'b.jpg', '')"
        )

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.path, ignore_errors=True)

    def test_encuentra_la_categoria_escapada(self):
        result = recommend_by_metadata(self.engine, 100, k=5)
        self.assertEqual([item.producto_id for item in result], [101])


class TestComprasDuplicadas(unittest.TestCase):
    """La muestra real repite ``(usuario, producto)``: el puntaje no se infla."""

    @classmethod
    def setUpClass(cls):
        cls.engine, cls.path = _new_engine()
        cls.engine.run("INSERT INTO compras VALUES (999, 1, 2, '2026-01-20', 1)")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.path, ignore_errors=True)

    def test_el_comprador_repetido_cuenta_una_vez(self):
        result = recommend_by_copurchase(self.engine, 1, k=10)
        by_id = {item.producto_id: item for item in result}
        self.assertAlmostEqual(by_id[2].score, 0.5)
        self.assertEqual(by_id[2].evidencia["co"], 3)
        self.assertEqual(by_id[2].evidencia["compras"], 4)


if __name__ == "__main__":
    unittest.main()
