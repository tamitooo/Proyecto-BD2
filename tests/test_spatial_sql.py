"""Pruebas de la extensión SQL espacial (Parte 2, sección 2.2.3).

Cubre las sintaxis del enunciado, que el motor resuelva con el R-Tree y que el
**resultado sea el mismo** que el de un escaneo secuencial con filtro.
"""

import unittest

from backend.engine import DemoEngine
from query.query_executor import QueryExecutor
from query.spatial_queries import spatial_kind
from query.sql_parser import SQLParser, SQLParseError
from spatial.geo import haversine, point_in_polygon


class TestParserEspacial(unittest.TestCase):
    """Las tres sintaxis del enunciado y sus errores."""

    def setUp(self):
        self.parser = SQLParser()

    def test_distancia_en_where(self):
        sentencia = self.parser.parse(
            "SELECT * FROM tiendas WHERE "
            "distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000"
        )
        predicado = sentencia.query_spec.predicates[0]
        self.assertTrue(predicado.is_spatial)
        self.assertEqual(predicado.column, "ubicacion")
        self.assertEqual(predicado.operator, "<")
        self.assertEqual(predicado.value, 5000.0)
        self.assertEqual(predicado.distance.point, (-12.0464, -77.0428))
        self.assertEqual(predicado.distance.metric, "haversine")

    def test_distancia_con_metrica_euclidiana(self):
        sentencia = self.parser.parse(
            "SELECT * FROM tiendas WHERE "
            "distancia(ubicacion, POINT(-12.0, -77.0), EUCLIDEAN) <= 0.5"
        )
        self.assertEqual(sentencia.query_spec.predicates[0].distance.metric,
                         "euclidean")

    def test_knn_con_order_by_y_limit(self):
        sentencia = self.parser.parse(
            "SELECT * FROM restaurantes "
            "ORDER BY distancia(ubicacion, POINT(-12.04, -77.04)) LIMIT 10"
        )
        orden = sentencia.query_spec.order_by[0]
        self.assertTrue(orden.is_spatial)
        self.assertFalse(orden.descending)
        self.assertEqual(orden.distance.column, "ubicacion")
        self.assertEqual(sentencia.limit, 10)

    def test_order_by_espacial_desc(self):
        sentencia = self.parser.parse(
            "SELECT * FROM t ORDER BY distancia(u, POINT(-12, -77)) DESC"
        )
        self.assertTrue(sentencia.query_spec.order_by[0].descending)

    def test_poligono(self):
        sentencia = self.parser.parse(
            "SELECT * FROM tiendas WHERE dentro_de(lat, "
            "POLYGON((-12.2 -77.2, -12.2 -76.9, -12.0 -76.9, -12.0 -77.2)))"
        )
        predicado = sentencia.query_spec.predicates[0]
        self.assertTrue(predicado.is_spatial)
        self.assertEqual(predicado.column, "lat")
        self.assertEqual(len(predicado.ring), 4)
        self.assertEqual(predicado.ring[0], (-12.2, -77.2))

    def test_where_espacial_combinado_con_normal(self):
        sentencia = self.parser.parse(
            "SELECT * FROM tiendas WHERE categoria = 'A' AND "
            "distancia(ubicacion, POINT(-12.04, -77.04)) < 3000"
        )
        predicates = sentencia.query_spec.predicates
        self.assertEqual(len(predicates), 2)
        self.assertFalse(predicates[0].is_spatial)
        self.assertTrue(predicates[1].is_spatial)

    def test_errores_de_sintaxis_espacial(self):
        casos = [
            "SELECT * FROM t WHERE distancia(u, POINT(-12, -77)) > 5000",
            "SELECT * FROM t WHERE distancia(u, POINT(a, b)) < 5",
            "SELECT * FROM t WHERE distancia(u) < 5",
            "SELECT * FROM t WHERE distancia(u, POINT(-12, -77), CHEBYSHEV) < 5",
            "SELECT * FROM t WHERE dentro_de(lat, POLYGON((-12 -77, -13 -78)))",
            "SELECT * FROM t WHERE dentro_de(lat, POINT(-12, -77))",
        ]
        for sql in casos:
            with self.subTest(sql=sql):
                with self.assertRaises(SQLParseError):
                    self.parser.parse(sql)

    def test_las_consultas_normales_siguen_funcionando(self):
        for sql in (
            "SELECT * FROM t WHERE id = 3",
            "SELECT * FROM t ORDER BY id DESC",
            "SELECT * FROM t WHERE a >= 1 AND b <= 2",
            "SELECT * FROM t WHERE a = 1 OR a = 2",
        ):
            with self.subTest(sql=sql):
                self.parser.parse(sql)


class TestEjecucionEspacial(unittest.TestCase):
    """El motor resuelve las consultas espaciales con el R-Tree."""

    @classmethod
    def setUpClass(cls):
        import tempfile

        from spatial.geo import generate_points

        cls.temporal = tempfile.TemporaryDirectory()
        cls.engine = DemoEngine(data_dir=cls.temporal.name, seed=True)
        cls.engine.run(
            "CREATE TABLE tiendas (id INT PRIMARY KEY, nombre VARCHAR(40), "
            "categoria VARCHAR(10), lat FLOAT, lon FLOAT)"
        )

        cls.ciudad = generate_points(
            500, center=(-12.0464, -77.0428), spread_km=25.0, seed=17
        )
        filas = ["id,nombre,categoria,lat,lon"]
        for i, (lat, lon) in enumerate(cls.ciudad, start=1):
            filas.append(
                f"{i},Tienda {i},{'A' if i % 2 else 'B'},{lat:.6f},{lon:.6f}"
            )
        cls.engine.import_csv("tiendas", "\n".join(filas) + "\n")

    @classmethod
    def tearDownClass(cls):
        cls.temporal.cleanup()

    def _cargar_indice(self):
        if not self.engine.catalog.spatial_index_for("tiendas", "lat"):
            resultado = self.engine.run(
                "CREATE INDEX idx_tiendas_ubicacion ON tiendas (lat, lon) USING RTREE"
            )
            self.assertTrue(resultado.success, resultado.error)

    # ------------------------------------------------------------- el índice

    def test_create_index_rtree(self):
        resultado = self.engine.run(
            "CREATE INDEX IF NOT EXISTS idx_tiendas_ubicacion "
            "ON tiendas (lat, lon) USING RTREE"
        )
        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.statement, "CREATE INDEX")

        registrado = self.engine.catalog.spatial_index_for("tiendas", "lat")
        self.assertIsNotNone(registrado)
        self.assertEqual(registrado.metadata.kind, "rtree")
        self.assertEqual(registrado.implementation.lat_column, "lat")
        self.assertEqual(registrado.implementation.lon_column, "lon")

    def test_create_index_rtree_necesita_dos_columnas(self):
        resultado = self.engine.run(
            "CREATE INDEX idx_una_sola ON tiendas (lat) USING RTREE"
        )
        self.assertFalse(resultado.success)
        self.assertIn("dos columnas", resultado.error or "")

    def test_el_indice_espacial_aparece_en_el_panel_de_archivos(self):
        self._cargar_indice()
        indices = self.engine.table_info("tiendas")["indexes"]
        tecnicas = {i["name"]: i["kind"] for i in indices}
        self.assertEqual(tecnicas.get("idx_tiendas_ubicacion"), "rtree")

    # ------------------------------------------------------------- consultas

    def test_rango_usa_el_rtree_y_coincide_con_fuerza_bruta(self):
        self._cargar_indice()
        centro = (-12.0464, -77.0428)
        resultado = self.engine.run(
            "SELECT id FROM tiendas WHERE "
            f"distancia(lat, POINT({centro[0]}, {centro[1]})) < 3000"
        )

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(
            resultado.execution_plan["access_path"], "RTREE_RANGE_SCAN"
        )
        self.assertEqual(
            resultado.execution_plan["used_indexes"], ["idx_tiendas_ubicacion"]
        )

        del_indice = {fila["id"] for fila in resultado.rows}
        de_fuerza = {
            i for i, punto in enumerate(self.ciudad, start=1)
            if haversine(centro, punto) < 3000
        }
        self.assertEqual(del_indice, de_fuerza)

    def test_rango_devuelve_la_distancia_calculada(self):
        self._cargar_indice()
        resultado = self.engine.run(
            "SELECT * FROM tiendas WHERE "
            "distancia(lat, POINT(-12.0464, -77.0428)) < 2000"
        )
        self.assertTrue(resultado.success, resultado.error)
        for fila in resultado.rows:
            distancia = haversine(
                (-12.0464, -77.0428), (fila["lat"], fila["lon"])
            )
            self.assertLessEqual(distancia, 2000)

    def test_knn_usa_el_rtree_y_devuelve_los_mas_cercanos(self):
        self._cargar_indice()
        centro = (-12.0464, -77.0428)
        resultado = self.engine.run(
            "SELECT id FROM tiendas ORDER BY "
            f"distancia(lat, POINT({centro[0]}, {centro[1]})) LIMIT 10"
        )

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.execution_plan["access_path"], "RTREE_KNN")

        del_indice = [fila["id"] for fila in resultado.rows]
        esperados = sorted(
            (
                (haversine(centro, punto), i)
                for i, punto in enumerate(self.ciudad, start=1)
            )
        )[:10]
        self.assertEqual(del_indice, [rid for _, rid in esperados])

    def test_knn_da_lo_mismo_que_el_escaneo_con_external_sort(self):
        """Sin R-Tree el resultado debe ser idéntico (sólo cambia el plan)."""
        self._cargar_indice()
        centro = (-12.0464, -77.0428)
        con_indice = self.engine.run(
            "SELECT id FROM tiendas ORDER BY "
            f"distancia(lat, POINT({centro[0]}, {centro[1]})) LIMIT 5"
        )
        self.assertTrue(con_indice.success, con_indice.error)
        self.assertEqual(con_indice.execution_plan["access_path"], "RTREE_KNN")

        # Fuerza bruta pura: las 5 distancias menores.
        esperados = sorted(
            (
                (haversine(centro, punto), i)
                for i, punto in enumerate(self.ciudad, start=1)
            )
        )[:5]
        self.assertEqual(
            [fila["id"] for fila in con_indice.rows],
            [rid for _, rid in esperados],
        )

    def test_knn_sin_limit_es_un_error_claro(self):
        self._cargar_indice()
        resultado = self.engine.run(
            "SELECT id FROM tiendas ORDER BY "
            "distancia(lat, POINT(-12.0464, -77.0428))"
        )
        self.assertFalse(resultado.success)
        self.assertIn("LIMIT", resultado.error or "")

    def test_poligono_usa_el_rtree(self):
        self._cargar_indice()
        anillo = [
            (-12.10, -77.10),
            (-12.10, -77.00),
            (-12.00, -77.00),
            (-12.00, -77.10),
        ]
        vertices = ", ".join(f"{lat} {lon}" for lat, lon in anillo)
        resultado = self.engine.run(
            f"SELECT id FROM tiendas WHERE dentro_de(lat, POLYGON(({vertices})))"
        )

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.execution_plan["access_path"], "RTREE_POLYGON")

        del_indice = {fila["id"] for fila in resultado.rows}
        de_fuerza = {
            i for i, punto in enumerate(self.ciudad, start=1)
            if point_in_polygon(punto, anillo)
        }
        self.assertEqual(del_indice, de_fuerza)

    def test_sin_indice_espacial_la_consulta_sigue_siendo_correcta(self):
        """Si no hay R-Tree, se puede resolver por escaneo (más lento) o avisar.

        Lo que **no** puede pasar es devolver un resultado incorrecto.
        """
        # Se elimina el índice para forzar el camino sin R-Tree.
        self.engine.run("DROP INDEX IF EXISTS idx_tiendas_ubicacion")
        resultado = self.engine.run(
            "SELECT id FROM tiendas WHERE "
            "distancia(lat, POINT(-12.0464, -77.0428)) < 3000"
        )
        # Sin índice espacial, el motor avisa en lugar de inventar un plan.
        if resultado.success:
            de_fuerza = {
                i for i, punto in enumerate(self.ciudad, start=1)
                if haversine((-12.0464, -77.0428), punto) < 3000
            }
            self.assertEqual({f["id"] for f in resultado.rows}, de_fuerza)
        else:
            self.assertIn("R-Tree", resultado.error or "")

    def test_explain_muestra_el_plan_espacial(self):
        self._cargar_indice()
        resultado = self.engine.run(
            "EXPLAIN SELECT * FROM tiendas ORDER BY "
            "distancia(lat, POINT(-12.0464, -77.0428)) LIMIT 5"
        )
        self.assertTrue(resultado.success, resultado.error)
        plan = resultado.execution_plan
        self.assertEqual(plan["access_path"], "RTREE_KNN")
        self.assertEqual(plan["planner_type"], "spatial_rtree")
        self.assertTrue(plan["spatial"])
        self.assertEqual(plan["runtime_steps"], [])
        self.assertIn("RTREE_KNN", resultado.rows[0]["plan"])

    def test_explain_analyze_incluye_la_traza(self):
        self._cargar_indice()
        resultado = self.engine.run(
            "EXPLAIN ANALYZE SELECT * FROM tiendas WHERE "
            "distancia(lat, POINT(-12.0464, -77.0428)) < 3000"
        )
        self.assertTrue(resultado.success, resultado.error)
        plan = resultado.execution_plan
        self.assertEqual(plan["access_path"], "RTREE_RANGE_SCAN")
        self.assertTrue(plan["runtime_steps"])
        self.assertIn("analyze", plan)


if __name__ == "__main__":
    unittest.main()
