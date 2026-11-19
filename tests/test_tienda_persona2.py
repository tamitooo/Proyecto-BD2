import shutil
import tempfile
import unittest

from query.catalog import Catalog
from query.query_executor import QueryExecutor


class TestTiendaPersona2(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="bd2-tienda-persona2-")
        self.catalog = Catalog(data_dir=self.directory)
        self.executor = QueryExecutor(self.catalog)

        self.catalog.create_table(
            "productos",
            [
                ("id", "INT"),
                ("nombre", "VARCHAR(100)"),
                ("categoria", "VARCHAR(50)"),
                ("precio", "FLOAT"),
                ("descripcion", "VARCHAR(300)"),
                ("imagen", "VARCHAR(100)"),
            ],
            primary_key="id",
            primary_key_index=False,
        )

        productos = (
            (
                1,
                "Laptop Gamer Pro",
                "laptops",
                4200.0,
                "laptop gaming potente tarjeta grafica alto rendimiento",
                "producto_001.png",
            ),
            (
                2,
                "Laptop Gamer Lite",
                "laptops",
                2800.0,
                "laptop gaming ligera para juegos y estudio",
                "producto_002.png",
            ),
            (
                3,
                "Laptop Oficina",
                "laptops",
                1800.0,
                "laptop ligera para oficina trabajo y estudio",
                "producto_003.png",
            ),
            (
                4,
                "Mochila Gamer",
                "mochilas",
                250.0,
                "mochila para laptop gaming resistente",
                "producto_004.png",
            ),
        )

        for producto in productos:
            valores = ", ".join(
                f"'{valor}'" if isinstance(valor, str) else str(valor)
                for valor in producto
            )

            resultado = self.executor.execute(
                f"INSERT INTO productos VALUES ({valores})"
            )

            self.assertTrue(resultado.success, resultado.error)

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_busqueda_match_con_categoria_y_precio(self):
        resultado = self.executor.execute(
            "SELECT id, categoria, precio, SCORE() AS score "
            "FROM productos "
            "WHERE MATCH(descripcion, 'laptop gaming') "
            "AND categoria = 'laptops' "
            "AND precio >= 2000 "
            "AND precio <= 5000 "
            "USING BM25 "
            "ORDER BY score DESC "
            "LIMIT 10"
        )

        self.assertTrue(resultado.success, resultado.error)

        ids = [fila["id"] for fila in resultado.rows]

        self.assertIn(1, ids)
        self.assertIn(2, ids)
        self.assertNotIn(3, ids)
        self.assertNotIn(4, ids)

        for fila in resultado.rows:
            self.assertEqual(fila["categoria"], "laptops")
            self.assertGreaterEqual(fila["precio"], 2000)
            self.assertLessEqual(fila["precio"], 5000)

    def test_busqueda_puede_ordenar_por_precio(self):
        resultado = self.executor.execute(
            "SELECT id, precio, SCORE() AS score "
            "FROM productos "
            "WHERE MATCH(descripcion, 'laptop') "
            "USING BM25 "
            "ORDER BY precio ASC"
        )

        self.assertTrue(resultado.success, resultado.error)

        precios = [fila["precio"] for fila in resultado.rows]

        self.assertEqual(precios, sorted(precios))

    def test_recomendacion_descripcion_excluye_producto_origen(self):
        producto_x = self.executor.execute(
            "SELECT descripcion FROM productos WHERE id = 1"
        )

        self.assertTrue(producto_x.success, producto_x.error)

        descripcion = producto_x.rows[0]["descripcion"].replace("'", "''")

        resultado = self.executor.execute(
            "SELECT id, SCORE() AS score "
            "FROM productos "
            f"WHERE MATCH(descripcion, '{descripcion}') "
            "USING BM25 "
            "ORDER BY score DESC "
            "LIMIT 11"
        )

        self.assertTrue(resultado.success, resultado.error)

        recomendaciones = [
            {
                "producto_id": fila["id"],
                "score": fila["score"],
            }
            for fila in resultado.rows
            if fila["id"] != 1
        ][:10]

        self.assertNotIn(
            1,
            [item["producto_id"] for item in recomendaciones],
        )

        self.assertTrue(recomendaciones)

        for item in recomendaciones:
            self.assertIsInstance(item["producto_id"], int)
            self.assertIsInstance(item["score"], (int, float))

        scores = [item["score"] for item in recomendaciones]

        self.assertEqual(
            scores,
            sorted(scores, reverse=True),
        )


if __name__ == "__main__":
    unittest.main()