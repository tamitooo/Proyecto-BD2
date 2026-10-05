"""Pruebas del script SQL del curso (fixtures de ``tests/fixtures``).

Ejercita exactamente el flujo que pide la cátedra:

    CREATE TABLE  ->  carga del CSV  ->  SELECT / EXPLAIN / EXPLAIN ANALYZE

Usa un directorio de datos temporal, así que no toca ``backend/data``.
"""

import os
import tempfile
import unittest
from pathlib import Path

from backend.engine import DemoEngine

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CSV_ALUMNOS = FIXTURES / "alumnos_prueba_bd2.csv"
SQL_PROYECTO = FIXTURES / "queries-proy.sql"


def sentencias_del_script():
    """Divide el .sql en sentencias, descartando comentarios ``--``."""
    lineas = [
        linea
        for linea in SQL_PROYECTO.read_text(encoding="utf-8").splitlines()
        if not linea.strip().startswith("--")
    ]
    texto = "\n".join(lineas)
    return [
        sentencia.strip()
        for sentencia in texto.split(";")
        if sentencia.strip()
    ]


class TestScriptDelCurso(unittest.TestCase):
    """El script completo del profesor sobre el CSV de prueba."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.engine = DemoEngine(data_dir=cls.temp.name, seed=True)

        cls.sentencias = sentencias_del_script()
        cls.creacion = cls.sentencias[0]
        # El script del curso se ejecuta en orden: primero el DDL, después la
        # carga del CSV y por último las consultas.
        cls.creacion_resultado = cls.engine.run(cls.creacion)
        cls.importacion = cls.engine.import_csv("alumnos", CSV_ALUMNOS)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    # ---------------------- 1. CREATE TABLE ----------------------
    def test_01_el_script_tiene_las_sentencias_esperadas(self):
        self.assertEqual(len(self.sentencias), 6)
        self.assertTrue(self.sentencias[0].upper().startswith("CREATE TABLE"))
        self.assertIn("EXPLAIN", self.sentencias[4].upper())
        self.assertIn("EXPLAIN ANALYZE", self.sentencias[5].upper())

    def test_02_create_table_crea_tabla_archivos_e_indice_de_pk(self):
        resultado = self.creacion_resultado

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.statement, "CREATE TABLE")

        tabla = self.engine.catalog.get_table("alumnos")
        self.assertEqual(
            tabla.schema.col_names(),
            ["id", "nombre", "carrera_id", "nota"],
        )
        self.assertEqual(tabla.schema.primary_key, "id")
        self.assertEqual(tabla.storage_kind, "heap")

        # La PRIMARY KEY genera un índice Hash único
        indices = list(tabla.indexes.values())
        self.assertEqual(len(indices), 1)
        self.assertEqual(indices[0].metadata.column, "id")
        self.assertEqual(indices[0].metadata.kind, "hash")
        self.assertTrue(indices[0].metadata.unique)

        # Archivos físicos en disco
        self.assertTrue(Path(tabla.storage.path).exists())

    def test_03_create_table_repetida_falla_sin_if_not_exists(self):
        repetida = self.engine.run(self.creacion)
        self.assertFalse(repetida.success)
        self.assertIn("ya existe", repetida.error or "")

        con_guardas = self.engine.run(self.creacion.replace(
            "CREATE TABLE alumnos",
            "CREATE TABLE IF NOT EXISTS alumnos",
        ))
        self.assertTrue(con_guardas.success, con_guardas.error)

    # ---------------------- 2. Carga del CSV ----------------------
    def test_04_importacion_del_csv(self):
        self.assertEqual(self.importacion.rows_read, 12)
        self.assertEqual(self.importacion.inserted, 12)
        self.assertEqual(self.importacion.failed, 0)
        self.assertEqual(
            self.importacion.columns,
            ["id", "nombre", "carrera_id", "nota"],
        )
        self.assertEqual(
            self.engine.table_info("alumnos")["row_count"],
            12,
        )

    # ---------------------- 3. Consultas ----------------------
    def test_05_consulta_1_igualdad_con_coma_en_el_literal(self):
        resultado = self.engine.run(self.sentencias[1])

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(len(resultado.rows), 1)
        self.assertEqual(resultado.rows[0]["nombre"], "Pérez, Juan")
        self.assertEqual(resultado.rows[0]["id"], 3)

    def test_06_consulta_2_rango_ordenado(self):
        resultado = self.engine.run(self.sentencias[2])

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(
            [fila["id"] for fila in resultado.rows],
            [3, 4, 8, 9, 10, 11],
        )
        self.assertTrue(all(fila["nota"] >= 14 for fila in resultado.rows))

    def test_07_consulta_3_sin_resultados(self):
        resultado = self.engine.run(self.sentencias[3])

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.rows, [])

    def test_08_consulta_4_explain_devuelve_el_plan(self):
        resultado = self.engine.run(self.sentencias[4])

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.statement, "EXPLAIN")

        plan = resultado.execution_plan
        self.assertIsNotNone(plan)
        self.assertEqual(plan["table"], "alumnos")
        self.assertTrue(plan["steps"])
        self.assertIn("EXTERNAL_SORT", [p["operator"] for p in plan["steps"]])
        self.assertEqual(plan["runtime_steps"], [])
        self.assertIn("Plan lógico", resultado.rows[0]["plan"])

    def test_09_consulta_5_explain_analyze_incluye_traza_real(self):
        resultado = self.engine.run(self.sentencias[5])

        self.assertTrue(resultado.success, resultado.error)
        plan = resultado.execution_plan
        self.assertTrue(plan["runtime_steps"])
        self.assertIn("analyze", plan)
        self.assertEqual(plan["analyze"]["rows"], 6)

        operadores = [paso["operator"] for paso in plan["runtime_steps"]]
        self.assertIn("HEAP_SCAN", operadores)
        self.assertIn("FILTER", operadores)
        self.assertIn("Ejecución real", resultado.rows[0]["plan"])

    def test_10_el_plan_usa_el_indice_de_la_clave_primaria(self):
        resultado = self.engine.run(
            "EXPLAIN SELECT * FROM alumnos WHERE id = 3"
        )

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(
            resultado.execution_plan["access_path"],
            "HASH_INDEX_LOOKUP",
        )
        self.assertEqual(
            resultado.execution_plan["used_indexes"],
            ["idx_alumnos_id_hash"],
        )


class TestDDLYCSVAdicionales(unittest.TestCase):
    """Casos extra pedidos por la cátedra: DROP, UPDATE, OR, LIMIT, persistencia."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.engine = DemoEngine(data_dir=cls.temp.name, seed=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_update_con_where_mantiene_indices(self):
        self.engine.run(
            "CREATE TABLE notas (id INT PRIMARY KEY, valor INT)"
        )
        self.engine.import_csv(
            "notas",
            "id,valor\n1,10\n2,20\n3,30\n",
        )

        actualizacion = self.engine.run(
            "UPDATE notas SET valor = 99 WHERE id = 2"
        )
        self.assertTrue(actualizacion.success, actualizacion.error)
        self.assertEqual(actualizacion.affected_rows, 1)

        consulta = self.engine.run("SELECT * FROM notas WHERE id = 2")
        self.assertEqual(consulta.rows[0]["valor"], 99)
        self.assertEqual(
            consulta.execution_plan["access_path"],
            "HASH_INDEX_LOOKUP",
        )

    def test_or_y_limit(self):
        self.engine.run("CREATE TABLE t (id INT PRIMARY KEY, x INT)")
        self.engine.import_csv("t", "id,x\n1,10\n2,20\n3,30\n4,40\n")

        con_or = self.engine.run(
            "SELECT id FROM t WHERE x = 10 OR x = 40 ORDER BY id"
        )
        self.assertTrue(con_or.success, con_or.error)
        self.assertEqual([fila["id"] for fila in con_or.rows], [1, 4])

        con_limit = self.engine.run(
            "SELECT id, x FROM t ORDER BY x DESC LIMIT 2"
        )
        self.assertEqual([fila["id"] for fila in con_limit.rows], [4, 3])

    def test_drop_table_borra_del_catalogo_y_del_disco(self):
        self.engine.run("CREATE TABLE temporal (id INT PRIMARY KEY)")
        ruta = self.engine.catalog.get_table("temporal").storage.path

        resultado = self.engine.run("DROP TABLE temporal")

        self.assertTrue(resultado.success, resultado.error)
        self.assertFalse(self.engine.catalog.has_table("temporal"))
        self.assertFalse(os.path.exists(ruta))

        inexistente = self.engine.run("DROP TABLE temporal")
        self.assertFalse(inexistente.success)

        con_guardas = self.engine.run("DROP TABLE IF EXISTS temporal")
        self.assertTrue(con_guardas.success, con_guardas.error)

    def test_el_catalogo_persiste_entre_reinicios(self):
        self.engine.run("CREATE TABLE persistente (id INT PRIMARY KEY, v INT)")
        self.engine.import_csv("persistente", "id,v\n1,7\n2,8\n")

        otro = DemoEngine(data_dir=self.temp.name, seed=False)

        self.assertTrue(otro.catalog.has_table("persistente"))
        self.assertEqual(otro.table_info("persistente")["row_count"], 2)
        consulta = otro.run("SELECT * FROM persistente WHERE id = 2")
        self.assertEqual(consulta.rows[0]["v"], 8)

    def test_create_table_con_storage_secuencial(self):
        self.engine.run(
            "CREATE TABLE seq_tab (id INT PRIMARY KEY, v INT) USING SEQUENTIAL"
        )
        self.engine.import_csv("seq_tab", "id,v\n1,1\n2,2\n3,3\n")

        tabla = self.engine.catalog.get_table("seq_tab")
        self.assertEqual(tabla.storage_kind, "sequential")
        self.assertTrue(Path(tabla.storage.main_path).exists())


if __name__ == "__main__":
    unittest.main()
