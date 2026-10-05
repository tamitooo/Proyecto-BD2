"""Pruebas de cumplimiento: fijan las correcciones de la revisión final.

Cada prueba corresponde a un punto del checklist (``docs/CHECKLIST_CUMPLIMIENTO.md``):

* SQL espacial **literal del enunciado** (2.2.3): ``distancia(ubicacion, ...)``
  y ``ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT k``.
* k-NN **sin** índice ordenado por distancia (antes ordenaba por latitud).
* Métrica Euclidiana sobre el R-Tree (antes se ignoraba).
* El R-Tree se mantiene con INSERT/UPDATE/DELETE y se restaura al reiniciar.
* Espacio del R-Tree = tamaño serializado real (antes ``nodos × 64``).
* JOIN con columnas calificadas de la tabla unida.
* Un solo índice agrupado por tabla.
* CSV pegado como texto en Linux/macOS (antes ``File name too long``).
"""

import math
import random
import tempfile
import unittest

from backend.engine import DemoEngine
from indexes.rtree import RTree
from query.sql_parser import SQLParser, SQLParseError
from spatial.geo import euclidean, generate_points, haversine
from spatial.index import SpatialIndex

CENTRO = (-12.0464, -77.0428)


class _ConTiendas(unittest.TestCase):
    con_indice = True

    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.engine = DemoEngine(data_dir=self.temporal.name, seed=True)
        self.engine.run(
            "CREATE TABLE tiendas (id INT PRIMARY KEY, nombre VARCHAR(30), "
            "lat FLOAT, lon FLOAT)"
        )
        self.puntos = generate_points(400, center=CENTRO, spread_km=20.0, seed=5)
        filas = ["id,nombre,lat,lon"] + [
            f"{i},T{i},{lat:.6f},{lon:.6f}"
            for i, (lat, lon) in enumerate(self.puntos, start=1)
        ]
        self.engine.import_csv("tiendas", "\n".join(filas) + "\n")
        # El CSV redondea a 6 decimales: se usan esas mismas coordenadas.
        self.puntos = [(round(a, 6), round(b, 6)) for a, b in self.puntos]
        if self.con_indice:
            r = self.engine.run(
                "CREATE INDEX idx_tiendas_ubicacion ON tiendas (lat, lon) USING RTREE"
            )
            self.assertTrue(r.success, r.error)

    def tearDown(self):
        self.temporal.cleanup()

    def run_ok(self, sql, **kw):
        r = self.engine.run(sql, **kw)
        self.assertTrue(r.success, f"{sql}: {r.error}")
        return r

    def fuerza_bruta_knn(self, origen, k, medir=haversine):
        orden = sorted(
            range(len(self.puntos)), key=lambda i: (medir(origen, self.puntos[i]), i)
        )
        return [i + 1 for i in orden[:k]]


class TestSQLDelEnunciadoConIndice(_ConTiendas):
    """Las dos consultas de 2.2.3 tal cual, resueltas con el R-Tree."""

    access_rango = "RTREE_RANGE_SCAN"
    access_knn = "RTREE_KNN"

    def test_rango_literal_del_enunciado(self):
        r = self.run_ok(
            "SELECT * FROM tiendas WHERE distancia(ubicacion, "
            "POINT(-12.0464, -77.0428)) < 5000"
        )
        self.assertEqual(r.execution_plan["access_path"], self.access_rango)
        esperado = {
            i for i, p in enumerate(self.puntos, start=1) if haversine(CENTRO, p) < 5000
        }
        self.assertEqual({row["id"] for row in r.rows}, esperado)

    def test_knn_literal_con_set(self):
        self.run_ok("SET mi_ubicacion = POINT(-12.0464, -77.0428)")
        r = self.run_ok(
            "SELECT * FROM tiendas ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10"
        )
        self.assertEqual(r.execution_plan["access_path"], self.access_knn)
        self.assertEqual([row["id"] for row in r.rows], self.fuerza_bruta_knn(CENTRO, 10))

    def test_knn_con_mi_ubicacion_enviada_por_el_mapa(self):
        origen = (-12.10, -77.00)
        r = self.run_ok(
            "SELECT * FROM tiendas ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 5",
            variables={"mi_ubicacion": list(origen)},
        )
        self.assertEqual([row["id"] for row in r.rows], self.fuerza_bruta_knn(origen, 5))

    def test_poligono_con_ubicacion(self):
        r = self.run_ok(
            "SELECT * FROM tiendas WHERE dentro_de(ubicacion, POLYGON((-12.10 -77.10, "
            "-12.10 -77.00, -12.00 -77.00, -12.00 -77.10)))"
        )
        esperado = {
            i
            for i, (lat, lon) in enumerate(self.puntos, start=1)
            if -12.10 <= lat <= -12.00 and -77.10 <= lon <= -77.00
        }
        self.assertEqual({row["id"] for row in r.rows}, esperado)


class TestSQLDelEnunciadoSinIndice(TestSQLDelEnunciadoConIndice):
    """Sin R-Tree el resultado debe ser idéntico (sólo cambia el plan)."""

    con_indice = False
    access_rango = "HEAP_SCAN"
    access_knn = "HEAP_SCAN"

    def test_poligono_con_ubicacion(self):
        self.skipTest("el polígono sin índice no es parte del enunciado")


class TestVariablesDeSesion(unittest.TestCase):
    def test_variable_no_definida_da_error_claro(self):
        with self.assertRaisesRegex(SQLParseError, "SET mi_ubicacion"):
            SQLParser().parse("SELECT * FROM t ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 3")

    def test_set_valida_el_rango_de_coordenadas(self):
        with self.assertRaises(SQLParseError):
            SQLParser().parse("SET mi_ubicacion = POINT(-77.04, -212.0)")

    def test_arroba_es_equivalente(self):
        parser = SQLParser({"mi_ubicacion": (-12.0, -77.0)})
        sentencia = parser.parse("SELECT * FROM t ORDER BY distancia(u, @mi_ubicacion) LIMIT 1")
        self.assertEqual(sentencia.query_spec.order_by[0].distance.point, (-12.0, -77.0))


class TestMetricaEuclidiana(_ConTiendas):
    def test_rango_euclidiano_por_rtree_coincide_con_fuerza_bruta(self):
        r = self.run_ok(
            "SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428), "
            "EUCLIDEAN) < 0.05"
        )
        self.assertEqual(r.execution_plan["access_path"], "RTREE_RANGE_SCAN")
        esperado = {
            i for i, p in enumerate(self.puntos, start=1) if euclidean(CENTRO, p) < 0.05
        }
        self.assertTrue(esperado)
        self.assertEqual({row["id"] for row in r.rows}, esperado)

    def test_knn_euclidiano_por_rtree_coincide_con_fuerza_bruta(self):
        r = self.run_ok(
            "SELECT * FROM tiendas ORDER BY distancia(ubicacion, POINT(-12.0464, "
            "-77.0428), EUCLIDEAN) LIMIT 7"
        )
        self.assertEqual(
            [row["id"] for row in r.rows], self.fuerza_bruta_knn(CENTRO, 7, euclidean)
        )

    def test_panel_convierte_el_radio_a_grados(self):
        r = self.engine.spatial_query(
            "tiendas", kind="range", lat=CENTRO[0], lon=CENTRO[1],
            radius_m=3000, metric="euclidean",
        )
        self.assertTrue(r["success"], r["error"])
        esperado = sum(
            1 for p in self.puntos if euclidean(CENTRO, p) <= 3000 / 111_320.0
        )
        self.assertEqual(r["count"], esperado)
        self.assertLess(r["count"], len(self.puntos))


class TestMantenimientoYPersistenciaRTree(_ConTiendas):
    def _ids_cerca(self):
        r = self.run_ok(
            "SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 300"
        )
        return {row["id"] for row in r.rows}

    def test_insert_update_delete_mantienen_el_rtree(self):
        self.run_ok("INSERT INTO tiendas VALUES (9001, 'Nueva', -12.0465, -77.0429)")
        self.assertIn(9001, self._ids_cerca())
        self.run_ok("UPDATE tiendas SET lat = -12.30 WHERE id = 9001")
        self.assertNotIn(9001, self._ids_cerca())
        self.run_ok("DELETE FROM tiendas WHERE id = 9001")
        indice = self.engine.catalog.spatial_index_for("tiendas", "lat").implementation
        indice.validate()
        self.assertEqual(len(indice), len(self.puntos))

    def test_el_rtree_se_restaura_al_reiniciar(self):
        reiniciado = DemoEngine(data_dir=self.temporal.name, seed=False)
        indices = reiniciado.table_info("tiendas")["indexes"]
        self.assertTrue(
            any(i["kind"] == "rtree" and i.get("lon_column") == "lon" for i in indices)
        )
        r = reiniciado.run(
            "SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000"
        )
        self.assertTrue(r.success, r.error)
        self.assertEqual(r.execution_plan["access_path"], "RTREE_RANGE_SCAN")


class TestEspacioDelRTree(unittest.TestCase):
    def test_serializacion_ida_y_vuelta(self):
        rng = random.Random(1)
        arbol = RTree(max_entries=8)
        arbol.bulk_load([((rng.random(), rng.random()), i) for i in range(500)])
        datos = arbol.serialize()
        self.assertEqual(len(datos), arbol.serialized_size_bytes())
        copia = RTree.deserialize(datos)
        copia.validate()
        caja = ((0.2, 0.2), (0.5, 0.6))
        self.assertEqual(
            sorted(r for r, _ in arbol.range_search(caja)),
            sorted(r for r, _ in copia.range_search(caja)),
        )

    def test_el_tamano_cuenta_todas_las_entradas(self):
        puntos = generate_points(5000, center=CENTRO, spread_km=30, seed=42)
        indice = SpatialIndex("lat", "lon", max_entries=16)
        indice.bulk_load([({"lat": a, "lon": b}, i) for i, (a, b) in enumerate(puntos)])
        nodos = indice.stats()["nodes"]
        tamano = indice.serialized_size_bytes()
        # Cada entrada guarda un MBR (32 B) + puntero (8 B): >= 40 B por punto.
        self.assertGreaterEqual(tamano, 40 * len(puntos))
        self.assertGreater(tamano, nodos * 64 * 5)

    def test_rid_tupla_se_serializa(self):
        arbol = RTree(max_entries=4)
        for i in range(20):
            arbol.insert((float(i), float(i)), (i // 4, i % 4))
        copia = RTree.deserialize(arbol.serialize())
        self.assertEqual(sorted(r for r, _ in copia.scan()), sorted(r for r, _ in arbol.scan()))


class TestRelacionalCorrecciones(unittest.TestCase):
    def setUp(self):
        self.temporal = tempfile.TemporaryDirectory()
        self.engine = DemoEngine(data_dir=self.temporal.name, seed=True)

    def tearDown(self):
        self.temporal.cleanup()

    def test_join_con_columnas_calificadas_de_la_tabla_unida(self):
        r = self.engine.run(
            "SELECT users.name, employees.salary FROM users "
            "JOIN employees ON users.dept = employees.dept"
        )
        self.assertTrue(r.success, r.error)
        self.assertEqual(r.columns, ["name", "salary"])
        self.assertTrue(r.rows)

    def test_join_columna_homonima_no_se_pisa(self):
        r = self.engine.run(
            "SELECT users.name, employees.name FROM users "
            "JOIN employees ON users.dept = employees.dept"
        )
        self.assertTrue(r.success, r.error)
        self.assertEqual(r.columns, ["name", "employees.name"])

    def test_columna_de_tabla_inexistente_es_error(self):
        r = self.engine.run(
            "SELECT users.name, foo.x FROM users JOIN employees ON users.dept = employees.dept"
        )
        self.assertFalse(r.success)

    def test_un_solo_indice_agrupado_por_tabla(self):
        r = self.engine.run("CREATE INDEX idx2 ON employees (id) USING BPLUS_CLUSTERED")
        self.assertFalse(r.success)
        self.assertIn("un índice agrupado", r.error)

    def test_csv_pegado_como_texto_largo(self):
        self.engine.run("CREATE TABLE t (id INT PRIMARY KEY, x INT)")
        texto = "id,x\n" + "".join(f"{i},{i * 2}\n" for i in range(1, 400))
        reporte = self.engine.import_csv("t", texto)
        self.assertEqual(reporte["inserted"] if isinstance(reporte, dict) else reporte.inserted, 399)


if __name__ == "__main__":
    unittest.main()
