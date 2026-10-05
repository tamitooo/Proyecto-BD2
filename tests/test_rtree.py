"""Pruebas del R-Tree y del índice espacial (Parte 2).

Se comprueba contra **modelos de referencia** (fuerza bruta) en lugar de contra
valores escritos a mano: si el índice devuelve algo distinto de recorrer todos
los puntos, la prueba falla.
"""

import math
import random
import unittest

from indexes.rtree import (
    RTree,
    mbr_area,
    mbr_contains_point,
    mbr_enlargement,
    mbr_intersects,
    mbr_of_mbrs,
    mbr_union,
    mindist_mbr_to_mbr,
    mindist_point_to_mbr,
)
from spatial.geo import (
    euclidean,
    generate_points,
    haversine,
    meters_per_degree_lon,
    point_in_polygon,
    polygon_area,
    polygon_perimeter_m,
    resolve_metric,
    validate_point,
    GeoError,
)
from spatial.index import SpatialIndex


class TestMINDIST(unittest.TestCase):
    """La fórmula de MINDIST que pide la clase (semana 06)."""

    def test_punto_dentro_del_mbr_aporta_cero(self):
        mbr = ((5.0, 1.0), (9.0, 7.0))
        self.assertEqual(mindist_point_to_mbr((7.0, 4.0), mbr), 0.0)
        self.assertEqual(mindist_point_to_mbr((5.0, 1.0), mbr), 0.0)

    def test_punto_fuera_por_un_eje(self):
        mbr = ((5.0, 1.0), (9.0, 7.0))
        # A la izquierda: (0-5)^2 + (0-1)^2 = 25 + 1
        self.assertAlmostEqual(
            mindist_point_to_mbr((0.0, 0.0), mbr), math.sqrt(26.0)
        )
        # Por debajo: sólo aporta el eje y
        self.assertAlmostEqual(mindist_point_to_mbr((7.0, 0.0), mbr), 1.0)

    def test_punto_fuera_por_los_dos_ejes(self):
        mbr = ((5.0, 1.0), (9.0, 7.0))
        self.assertAlmostEqual(
            mindist_point_to_mbr((10.0, 8.0), mbr), math.sqrt(2.0)
        )

    def test_mindist_entre_dos_mbr_solapados_es_cero(self):
        self.assertEqual(
            mindist_mbr_to_mbr(((0, 0), (5, 5)), ((3, 3), (8, 8))), 0.0
        )
        self.assertEqual(
            mindist_mbr_to_mbr(((0, 0), (5, 5)), ((5, 2), (8, 8))), 0.0
        )

    def test_mindist_entre_dos_mbr_separados(self):
        self.assertAlmostEqual(
            mindist_mbr_to_mbr(((0, 0), (5, 5)), ((9, 0), (12, 5))), 4.0
        )

    def test_mindist_es_cota_inferior_de_la_distancia_real(self):
        """La propiedad que hace que el k-NN sea exacto."""
        rng = random.Random(3)
        for _ in range(200):
            primer = (
                (rng.uniform(0, 50), rng.uniform(0, 50)),
                (rng.uniform(50, 100), rng.uniform(50, 100)),
            )
            segundo = (
                (rng.uniform(0, 50), rng.uniform(0, 50)),
                (rng.uniform(50, 100), rng.uniform(50, 100)),
            )
            q = (rng.uniform(0, 100), rng.uniform(0, 100))
            cota = mindist_point_to_mbr(q, primer)
            # Un punto cualquiera del MBR nunca está más cerca que la cota.
            real = euclidean(q, (primer[0][0], primer[0][1]))
            self.assertLessEqual(cota, real + 1e-9)


class TestMBR(unittest.TestCase):

    def test_union_y_area(self):
        self.assertEqual(
            mbr_union(((0, 0), (1, 1)), ((2, 2), (3, 3))), ((0, 0), (3, 3))
        )
        self.assertAlmostEqual(mbr_area(((0, 0), (3, 4))), 12.0)
        self.assertEqual(mbr_area(((1, 1), (1, 1))), 0.0)

    def test_ampliacion_de_area(self):
        mbr = ((0, 0), (2, 2))
        self.assertAlmostEqual(mbr_enlargement(mbr, (1.0, 1.0)), 0.0)
        self.assertAlmostEqual(mbr_enlargement(mbr, (3.0, 1.0)), 2.0)

    def test_interseccion_y_contiene(self):
        self.assertTrue(mbr_intersects(((0, 0), (2, 2)), ((1, 1), (3, 3))))
        self.assertFalse(mbr_intersects(((0, 0), (2, 2)), ((3, 3), (4, 4))))
        self.assertTrue(mbr_contains_point(((0, 0), (2, 2)), (1, 1)))
        self.assertFalse(mbr_contains_point(((0, 0), (2, 2)), (3, 1)))


class TestRTreeEstructura(unittest.TestCase):

    def _arbol_aleatorio(self, cantidad=2000, semilla=11, max_entries=8):
        rng = random.Random(semilla)
        arbol = RTree(max_entries=max_entries)
        puntos = []
        for i in range(cantidad):
            punto = (rng.uniform(0, 100), rng.uniform(0, 100))
            puntos.append((punto, i))
            arbol.insert(punto, i)
        return arbol, puntos

    def test_insertar_no_pierde_entradas(self):
        arbol, puntos = self._arbol_aleatorio(3000)
        self.assertEqual(len(arbol), 3000)
        self.assertEqual(sum(1 for _ in arbol.scan()), 3000)

    def test_validate_detecta_el_arbol_correcto(self):
        arbol, _ = self._arbol_aleatorio(1500)
        self.assertTrue(arbol.validate())

    def test_minimo_y_maximo_de_entradas(self):
        arbol, _ = self._arbol_aleatorio(1000, max_entries=8)
        self.assertEqual(arbol.min_entries, 4)
        pila = [arbol.root]
        while pila:
            nodo = pila.pop()
            self.assertLessEqual(len(nodo.entries), arbol.max_entries)
            if nodo is not arbol.root:
                self.assertGreaterEqual(len(nodo.entries), arbol.min_entries)
            if not nodo.is_leaf:
                for entrada in nodo.entries:
                    pila.append(entrada.child)

    def test_el_padre_cubre_a_los_hijos(self):
        arbol, _ = self._arbol_aleatorio(800)
        pila = [arbol.root]
        while pila:
            nodo = pila.pop()
            if nodo.is_leaf:
                continue
            for entrada in nodo.entries:
                self.assertTrue(mbr_intersects(entrada.mbr, entrada.child.mbr))
                pila.append(entrada.child)

    def test_altura_crece_con_split_de_raiz(self):
        arbol = RTree(max_entries=4)
        for i in range(3):
            arbol.insert((float(i), float(i)), i)
        self.assertEqual(arbol.height, 1)
        for i in range(3, 40):
            arbol.insert((float(i), float(i)), i)
        self.assertGreater(arbol.height, 1)
        arbol.validate()

    def test_las_hojas_estan_a_la_misma_profundidad(self):
        arbol, _ = self._arbol_aleatorio(2500, max_entries=6)
        profundidades = set()
        pila = [(arbol.root, 1)]
        while pila:
            nodo, profundidad = pila.pop()
            if nodo.is_leaf:
                profundidades.add(profundidad)
            else:
                for entrada in nodo.entries:
                    pila.append((entrada.child, profundidad + 1))
        self.assertEqual(len(profundidades), 1, profundidades)


class TestRTreeBusquedas(unittest.TestCase):
    """Rango y k-NN contra fuerza bruta."""

    @classmethod
    def setUpClass(cls):
        rng = random.Random(21)
        cls.puntos = [
            (rng.uniform(0, 100), rng.uniform(0, 100)) for _ in range(3000)
        ]
        cls.arbol = RTree(max_entries=16)
        for i, punto in enumerate(cls.puntos):
            cls.arbol.insert(punto, i)
        cls.arbol.validate()

    def test_rango_coincide_con_fuerza_bruta(self):
        rng = random.Random(5)
        for _ in range(25):
            x = rng.uniform(0, 90)
            y = rng.uniform(0, 90)
            caja = ((x, y), (x + rng.uniform(1, 10), y + rng.uniform(1, 10)))

            del_indice = {rid for rid, _ in self.arbol.range_search(caja)}
            de_fuerza = {
                i for i, p in enumerate(self.puntos)
                if caja[0][0] <= p[0] <= caja[1][0]
                and caja[0][1] <= p[1] <= caja[1][1]
            }
            self.assertEqual(del_indice, de_fuerza)

    def test_rango_circular(self):
        """``search_circle`` es el rango de la **caja** que inscribe el círculo.

        Devuelve candidatos por MBR: incluye todo lo que está dentro del círculo
        y puede incluir puntos de las esquinas de la caja, que la comprobación
        exacta posterior descarta. Por eso la comprobación es de **inclusión**,
        no de igualdad.
        """
        arbol = RTree(max_entries=16)
        for i, punto in enumerate(self.puntos):
            arbol.insert(punto, i)

        centro = (50.0, 50.0)
        radio = 12.0
        candidatos = {rid for rid, _ in arbol.search_circle(centro, radio)}

        dentro_del_circulo = {
            i for i, p in enumerate(self.puntos)
            if euclidean(centro, p) <= radio
        }
        dentro_de_la_caja = {
            i for i, p in enumerate(self.puntos)
            if abs(p[0] - centro[0]) <= radio and abs(p[1] - centro[1]) <= radio
        }

        # Todo lo que está en el círculo está entre los candidatos.
        self.assertTrue(dentro_del_circulo.issubset(candidatos))
        # Y los candidatos son exactamente los de la caja.
        self.assertEqual(candidatos, dentro_de_la_caja)

    def test_knn_coincide_con_fuerza_bruta(self):
        rng = random.Random(9)
        for k in (1, 5, 10, 50):
            for _ in range(8):
                q = (rng.uniform(0, 100), rng.uniform(0, 100))
                obtenido = self.arbol.knn(
                    q, k, coordinates=lambda rid: self.puntos[rid]
                )
                esperado = sorted(
                    ((euclidean(q, p), i) for i, p in enumerate(self.puntos))
                )[:k]

                self.assertEqual(
                    [rid for rid, _ in obtenido],
                    [rid for _, rid in esperado],
                )
                for (_, distancia), (esperada, _) in zip(obtenido, esperado):
                    self.assertAlmostEqual(distancia, esperada, places=9)

    def test_knn_con_k_mayor_que_el_dataset(self):
        arbol = RTree(max_entries=4)
        for i in range(5):
            arbol.insert((float(i), float(i)), i)
        vecinos = arbol.knn(
            (0.0, 0.0), 50, coordinates=lambda rid: (float(rid), float(rid))
        )
        self.assertEqual(len(vecinos), 5)

    def test_knn_invalido(self):
        with self.assertRaises(ValueError):
            self.arbol.knn((0.0, 0.0), 0)

    def test_busqueda_exacta(self):
        objetivo = self.puntos[77]
        self.assertIn(77, self.arbol.search(objetivo))
        self.assertEqual(self.arbol.search((999.0, 999.0)), [])


class TestRTreeBulkLoad(unittest.TestCase):

    def test_bulk_load_respeta_las_invariantes(self):
        for cantidad in (1, 5, 17, 100, 1000, 5000):
            with self.subTest(cantidad=cantidad):
                rng = random.Random(cantidad)
                puntos = [
                    ((rng.uniform(0, 100), rng.uniform(0, 100)), i)
                    for i in range(cantidad)
                ]
                arbol = RTree(max_entries=16)
                arbol.bulk_load(puntos)
                self.assertEqual(len(arbol), cantidad)
                arbol.validate()

    def test_bulk_load_da_mejor_llenado_que_insertar_uno_a_uno(self):
        rng = random.Random(31)
        puntos = [
            ((rng.uniform(0, 100), rng.uniform(0, 100)), i)
            for i in range(4000)
        ]

        con_bulk = RTree(max_entries=16)
        con_bulk.bulk_load(puntos)

        uno_a_uno = RTree(max_entries=16)
        for punto, rid in puntos:
            uno_a_uno.insert(punto, rid)

        self.assertGreaterEqual(
            con_bulk.stats()["fill_factor"], uno_a_uno.stats()["fill_factor"]
        )
        con_bulk.validate()
        uno_a_uno.validate()

    def test_bulk_load_encuentra_los_mismos_rangos(self):
        rng = random.Random(77)
        puntos = [
            (rng.uniform(0, 100), rng.uniform(0, 100)) for _ in range(2000)
        ]
        arbol = RTree(max_entries=16)
        arbol.bulk_load([(p, i) for i, p in enumerate(puntos)])
        arbol.validate()

        for _ in range(10):
            x, y = rng.uniform(0, 80), rng.uniform(0, 80)
            caja = ((x, y), (x + 15, y + 15))
            del_indice = {rid for rid, _ in arbol.range_search(caja)}
            de_fuerza = {
                i for i, p in enumerate(puntos)
                if caja[0][0] <= p[0] <= caja[1][0]
                and caja[0][1] <= p[1] <= caja[1][1]
            }
            self.assertEqual(del_indice, de_fuerza)


class TestIndiceEspacial(unittest.TestCase):
    """El envoltorio con latitud/longitud y las dos métricas."""

    @classmethod
    def setUpClass(cls):
        cls.ciudad = generate_points(
            4000, center=(-12.0464, -77.0428), spread_km=25.0, seed=3
        )
        cls.indice = SpatialIndex("lat", "lon", max_entries=16, metric="haversine")
        cls.indice.bulk_load(
            [({"lat": lat, "lon": lon}, i) for i, (lat, lon) in enumerate(cls.ciudad)]
        )

    def test_el_indice_es_valido(self):
        self.assertTrue(self.indice.validate())
        self.assertEqual(len(self.indice), len(self.ciudad))

    def test_rango_haversine_coincide_con_fuerza_bruta(self):
        centro = (-12.0464, -77.0428)
        for radio in (1_000, 5_000, 10_000):
            with self.subTest(radio=radio):
                del_indice = {
                    rid for rid, _ in self.indice.range_search(centro, radio)
                }
                de_fuerza = {
                    i for i, p in enumerate(self.ciudad)
                    if haversine(centro, p) <= radio
                }
                self.assertEqual(del_indice, de_fuerza)

    def test_rango_devuelve_distancias_ordenadas(self):
        centro = (-12.0464, -77.0428)
        resultados = self.indice.range_search(centro, 5_000)
        distancias = [d for _, d in resultados]
        self.assertEqual(distancias, sorted(distancias))

    def test_knn_haversine_coincide_con_fuerza_bruta(self):
        centro = (-12.0464, -77.0428)
        for k in (1, 10, 50, 100):
            with self.subTest(k=k):
                obtenido = self.indice.knn(centro, k)
                esperado = sorted(
                    ((haversine(centro, p), i) for i, p in enumerate(self.ciudad))
                )[:k]
                self.assertEqual(
                    [rid for rid, _ in obtenido],
                    [rid for _, rid in esperado],
                )

    def test_radio_cero_y_negativo(self):
        centro = (-12.0464, -77.0428)
        self.assertEqual(self.indice.range_search(centro, 0.0), [])
        with self.assertRaises(ValueError):
            self.indice.range_search(centro, -1.0)

    def test_poligono_coincide_con_fuerza_bruta(self):
        anillo = [
            (-12.10, -77.10),
            (-12.10, -77.00),
            (-12.00, -77.00),
            (-12.00, -77.10),
        ]
        del_indice = {rid for rid, _ in self.indice.polygon_search(anillo)}
        de_fuerza = {
            i for i, p in enumerate(self.ciudad) if point_in_polygon(p, anillo)
        }
        self.assertEqual(del_indice, de_fuerza)

    def test_poligono_invalido(self):
        with self.assertRaises(ValueError):
            self.indice.polygon_search([(-12.0, -77.0), (-12.1, -77.1)])

    def test_metricas_por_nombre(self):
        nombre, funcion = resolve_metric("HAVERSINE")
        self.assertEqual(nombre, "haversine")
        self.assertIs(funcion, haversine)
        nombre, _ = resolve_metric("euclidean")
        self.assertEqual(nombre, "euclidean")
        with self.assertRaises(GeoError):
            resolve_metric("chebyshev")

    def test_coordenadas_por_rid(self):
        lat, lon = self.indice.coordinates(0)
        self.assertAlmostEqual(lat, self.ciudad[0][0])
        self.assertAlmostEqual(lon, self.ciudad[0][1])
        with self.assertRaises(KeyError):
            self.indice.coordinates(999_999)


class TestGeo(unittest.TestCase):

    def test_haversine_distancias_conocidas(self):
        # Lima -> Arequipa: ~765 km
        distancia = haversine((-12.0464, -77.0428), (-16.4090, -71.5375))
        self.assertGreater(distancia, 700_000)
        self.assertLess(distancia, 800_000)

    def test_haversine_de_un_punto_a_si_mismo(self):
        self.assertAlmostEqual(
            haversine((-12.0, -77.0), (-12.0, -77.0)), 0.0, places=6
        )

    def test_haversine_un_grado_de_latitud(self):
        """1° de latitud son ~111.32 km en toda la esfera."""
        distancia = haversine((0.0, 0.0), (1.0, 0.0))
        self.assertAlmostEqual(distancia, 111_195, delta=500)

    def test_euclidiana(self):
        self.assertAlmostEqual(euclidean((0, 0), (3, 4)), 5.0)

    def test_validacion_de_coordenadas(self):
        self.assertEqual(validate_point(-12.0, -77.0), (-12.0, -77.0))
        with self.assertRaises(GeoError):
            validate_point(-91.0, -77.0)
        with self.assertRaises(GeoError):
            validate_point(-12.0, 181.0)
        with self.assertRaises(GeoError):
            validate_point(float("nan"), -77.0)

    def test_metros_por_grado_de_longitud(self):
        self.assertAlmostEqual(meters_per_degree_lon(0.0), 111_320.0, places=1)
        self.assertLess(meters_per_degree_lon(60.0), 60_000.0)

    def test_punto_en_poligono(self):
        cuadrado = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)]
        self.assertTrue(point_in_polygon((5.0, 5.0), cuadrado))
        self.assertFalse(point_in_polygon((15.0, 5.0), cuadrado))
        self.assertFalse(point_in_polygon((-1.0, 5.0), cuadrado))
        # Sobre el borde cuenta como dentro.
        self.assertTrue(point_in_polygon((0.0, 5.0), cuadrado))

    def test_poligono_concavo(self):
        # Una "C": el punto del hueco está fuera.
        anillo = [
            (0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 7.0),
            (3.0, 7.0), (3.0, 3.0), (10.0, 3.0), (10.0, 0.0),
        ]
        self.assertFalse(point_in_polygon((6.0, 5.0), anillo))
        self.assertTrue(point_in_polygon((1.5, 5.0), anillo))

    def test_area_y_perimetro_del_poligono(self):
        cuadrado = [(0.0, 0.0), (0.0, 1.0), (1.0, 1.0), (1.0, 0.0)]
        self.assertAlmostEqual(polygon_area(cuadrado), 1.0)
        self.assertGreater(polygon_perimeter_m(cuadrado), 400_000)

    def test_generacion_de_puntos_es_reproducible(self):
        primeros = generate_points(50, seed=5)
        segundos = generate_points(50, seed=5)
        self.assertEqual(primeros, segundos)
        self.assertEqual(len(primeros), 50)
        for lat, lon in primeros:
            self.assertTrue(-90 <= lat <= 90)
            self.assertTrue(-180 <= lon <= 180)

    def test_poligono_con_menos_de_tres_vertices(self):
        with self.assertRaises(GeoError):
            point_in_polygon((0.0, 0.0), [(0.0, 0.0), (1.0, 1.0)])


if __name__ == "__main__":
    unittest.main()
