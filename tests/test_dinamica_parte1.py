"""Pruebas de las capacidades dinámicas de la Parte 1.

Cubre lo que la cátedra pidió explícitamente en la demo y lo que faltaba:

* ``CREATE INDEX`` / ``DROP INDEX`` desde SQL, incluidas las tres técnicas y
  los errores previsibles (columna inexistente, técnica desconocida, duplicado).
* Que un índice creado por el usuario **cambia el plan** de la consulta: el
  caso que permite demostrar la mejora de rendimiento.
* ``BEGIN TRANSACTION`` / ``END TRANSACTION`` / ``ROLLBACK`` integrados en el
  mismo ejecutor que usan el API REST y la interfaz, con ROLLBACK de INSERT,
  UPDATE, DELETE y DDL.
* Las mejoras del planner: rango con los dos extremos y unión de índices en OR.

Cada prueba trabaja sobre su **propia copia** de un directorio de datos
plantilla, así que el orden de ejecución no importa y ninguna prueba puede
contaminar a otra.
"""

import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from backend.engine import DemoEngine

CSV_ALUMNOS = Path(__file__).resolve().parent / "fixtures" / "alumnos_prueba_bd2.csv"


class MotorAislado(unittest.TestCase):
    """Motor real sobre una copia limpia del directorio de datos plantilla."""

    #: Directorio de datos compartido, construido una sola vez por proceso.
    _plantilla: str | None = None
    _temporal_plantilla: TemporaryDirectory | None = None

    @classmethod
    def _construir_plantilla(cls) -> str:
        if cls._plantilla is None:
            cls._temporal_plantilla = TemporaryDirectory()
            motor = DemoEngine(data_dir=cls._temporal_plantilla.name, seed=True)
            motor.run("DROP TABLE IF EXISTS alumnos")
            motor.run(
                "CREATE TABLE alumnos ("
                "id INT PRIMARY KEY, "
                "nombre VARCHAR(100), "
                "carrera_id INT, "
                "nota INT)"
            )
            reporte = motor.import_csv("alumnos", CSV_ALUMNOS)
            assert reporte.failed == 0 and reporte.inserted == 12, reporte
            cls._plantilla = cls._temporal_plantilla.name
        return cls._plantilla

    def setUp(self):
        self.datos = TemporaryDirectory()
        self.addCleanup(self.datos.cleanup)
        shutil.copytree(
            self._construir_plantilla(),
            self.datos.name,
            dirs_exist_ok=True,
        )
        self.engine = DemoEngine(data_dir=self.datos.name, seed=True)

    # -------------------------------------------------------------- ayudas

    def contar(self, tabla: str = "alumnos") -> int:
        return self.engine.table_info(tabla)["row_count"]

    def plan(self, sql: str) -> dict:
        resultado = self.engine.run(sql)
        self.assertTrue(resultado.success, resultado.error)
        return resultado.execution_plan

    def indices(self, tabla: str = "alumnos"):
        return [
            index["name"]
            for index in self.engine.table_info(tabla)["indexes"]
        ]


class TestDinamicaDeIndices(MotorAislado):

    def test_01_la_tabla_del_curso_esta_cargada(self):
        self.assertEqual(self.contar(), 12)

    def test_02_sin_indice_sobre_nota_el_plan_es_un_escaneo(self):
        resultado = self.engine.run(
            "SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id"
        )

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(len(resultado.rows), 6)
        self.assertEqual(resultado.execution_plan["access_path"], "HEAP_SCAN")

    def test_03_create_index_cambia_el_plan_de_la_consulta(self):
        resultado = self.engine.run(
            "CREATE INDEX idx_alumnos_nota ON alumnos (nota)"
        )

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.statement, "CREATE INDEX")
        self.assertEqual(resultado.rows[0]["columna"], "nota")
        self.assertEqual(resultado.rows[0]["filas"], 12)
        self.assertIn("idx_alumnos_nota", self.indices())

        # La MISMA consulta ahora usa el índice: esto es lo demostrable.
        plan = self.plan("SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id")
        self.assertEqual(plan["access_path"], "BPLUS_UNCLUSTERED_RANGE_SCAN")
        self.assertEqual(plan["used_indexes"], ["idx_alumnos_nota"])

    def test_04_el_resultado_no_cambia_al_indexar(self):
        antes = self.engine.run(
            "SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id"
        ).rows

        self.engine.run(
            "CREATE INDEX idx_alumnos_carrera ON alumnos (carrera_id) "
            "USING BPLUS_CLUSTERED"
        )

        despues = self.engine.run(
            "SELECT * FROM alumnos WHERE nota >= 14 ORDER BY id"
        ).rows
        self.assertEqual(antes, despues)

    def test_05_indice_agrupado_para_igualdad_y_rango(self):
        self.engine.run(
            "CREATE INDEX idx_alumnos_carrera ON alumnos (carrera_id) "
            "USING BPLUS_CLUSTERED"
        )

        plan = self.plan("SELECT * FROM alumnos WHERE carrera_id = 2")
        self.assertEqual(plan["access_path"], "BPLUS_CLUSTERED_LOOKUP")

        resultado = self.engine.run(
            "SELECT * FROM alumnos WHERE carrera_id = 2 ORDER BY id"
        )
        self.assertEqual([fila["id"] for fila in resultado.rows], [2, 7, 8, 10])

        plan = self.plan("SELECT * FROM alumnos WHERE carrera_id >= 2")
        self.assertEqual(plan["access_path"], "BPLUS_CLUSTERED_RANGE_SCAN")

    def test_06_indice_hash_unico_respeta_la_unicidad(self):
        resultado = self.engine.run(
            "CREATE UNIQUE INDEX idx_alumnos_nombre ON alumnos (nombre) USING HASH"
        )
        self.assertTrue(resultado.success, resultado.error)

        plan = self.plan("SELECT * FROM alumnos WHERE nombre = 'Ana María'")
        self.assertEqual(plan["access_path"], "HASH_INDEX_LOOKUP")

        duplicado = self.engine.run(
            "INSERT INTO alumnos VALUES (77, 'Pérez, Juan', 1, 15)"
        )
        self.assertFalse(duplicado.success)
        self.assertIsNotNone(duplicado.error)
        self.assertEqual(self.contar(), 12)

    def test_07_errores_de_ddl_de_indices_son_claros(self):
        self.engine.run("CREATE INDEX idx_nota ON alumnos (nota)")

        casos = [
            (
                "CREATE INDEX idx_x ON alumnos (noexiste)",
                "no existe en la tabla",
            ),
            (
                "CREATE INDEX idx_y ON alumnos (nota) USING BITMAP",
                "técnica desconocida",
            ),
            (
                "CREATE INDEX idx_nota2 ON alumnos (nota)",
                "ya tiene el índice",
            ),
            (
                "CREATE INDEX idx_z ON tabla_inexistente (id)",
                "unknown table",
            ),
            (
                "DROP INDEX idx_no_existe",
                "no existe el índice",
            ),
        ]

        for sql, esperado in casos:
            with self.subTest(sql=sql):
                resultado = self.engine.run(sql)
                self.assertFalse(resultado.success)
                self.assertIn(esperado, resultado.error or "")

    def test_08_drop_index_quita_el_indice_y_el_plan_vuelve_al_escaneo(self):
        self.engine.run("CREATE INDEX idx_temp_nota ON alumnos (nota)")
        self.assertIn("idx_temp_nota", self.indices())

        resultado = self.engine.run("DROP INDEX idx_temp_nota ON alumnos")

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(resultado.statement, "DROP INDEX")
        self.assertNotIn("idx_temp_nota", self.indices())

        plan = self.plan("SELECT * FROM alumnos WHERE nota >= 14")
        self.assertEqual(plan["access_path"], "HEAP_SCAN")
        self.assertEqual(plan["used_indexes"], [])

        self.assertFalse(self.engine.run("DROP INDEX idx_temp_nota").success)
        self.assertTrue(
            self.engine.run("DROP INDEX IF EXISTS idx_temp_nota").success
        )

    def test_09_create_index_sobre_tabla_creada_por_sql(self):
        self.engine.run(
            "CREATE TABLE cursos (id INT PRIMARY KEY, nombre VARCHAR(30), creditos INT)"
        )
        self.engine.import_csv("cursos", "id,nombre,creditos\n1,BD2,4\n2,Algo,5\n")

        resultado = self.engine.run(
            "CREATE INDEX idx_cursos_creditos ON cursos (creditos) "
            "USING BPLUS_CLUSTERED"
        )
        self.assertTrue(resultado.success, resultado.error)

        consulta = self.engine.run("SELECT * FROM cursos WHERE creditos >= 5")
        self.assertEqual(
            consulta.execution_plan["access_path"], "BPLUS_CLUSTERED_RANGE_SCAN"
        )
        self.assertEqual([fila["id"] for fila in consulta.rows], [2])

    def test_10_el_indice_se_reconstruye_al_reabrir_el_catalogo(self):
        self.engine.run("CREATE INDEX idx_alumnos_nota ON alumnos (nota)")

        otro = DemoEngine(data_dir=self.datos.name, seed=False)

        self.assertIn("idx_alumnos_nota", self.indices())
        consulta = otro.run("SELECT * FROM alumnos WHERE nota = 20")
        self.assertEqual([fila["id"] for fila in consulta.rows], [11])

    def test_11_el_create_index_reporta_el_tiempo_de_construccion(self):
        resultado = self.engine.run(
            "CREATE INDEX idx_alumnos_nota ON alumnos (nota)"
        )

        self.assertIsNotNone(
            resultado.execution_plan["index_build_time_ms"]
        )
        self.assertGreaterEqual(
            resultado.execution_plan["index_build_time_ms"], 0
        )
        self.assertEqual(
            resultado.execution_plan["runtime_steps"][0]["rows_indexed"], 12
        )


class TestTransaccionesEnElMotor(MotorAislado):

    def test_01_begin_y_end_transaction_confirman(self):
        inicio = self.contar()

        begin = self.engine.run("BEGIN TRANSACTION")
        self.assertTrue(begin.success, begin.error)
        self.assertEqual(begin.statement, "BEGIN TRANSACTION")

        self.assertTrue(
            self.engine.run(
                "INSERT INTO alumnos VALUES (200, 'Commit Ok', 1, 18)"
            ).success
        )
        self.assertEqual(self.contar(), inicio + 1)

        fin = self.engine.run("END TRANSACTION")
        self.assertTrue(fin.success, fin.error)
        self.assertEqual(fin.statement, "END TRANSACTION")
        self.assertEqual(self.contar(), inicio + 1)

    def test_02_rollback_de_insert(self):
        inicio = self.contar()

        self.engine.run("BEGIN TRANSACTION")
        self.engine.run("INSERT INTO alumnos VALUES (201, 'Rollback', 1, 18)")
        self.assertEqual(self.contar(), inicio + 1)

        rollback = self.engine.run("ROLLBACK")

        self.assertTrue(rollback.success, rollback.error)
        self.assertEqual(rollback.statement, "ROLLBACK")
        self.assertEqual(self.contar(), inicio)
        self.assertEqual(
            self.engine.run("SELECT * FROM alumnos WHERE id = 201").rows, []
        )

    def test_03_rollback_de_update_y_delete(self):
        antes = self.engine.run("SELECT * FROM alumnos ORDER BY id").rows

        self.engine.run("BEGIN TRANSACTION")
        self.engine.run("UPDATE alumnos SET nota = 0 WHERE id = 11")
        self.engine.run("DELETE FROM alumnos WHERE nota < 14")
        self.assertTrue(
            self.engine.run("SELECT * FROM alumnos").success
        )
        self.engine.run("ROLLBACK")

        despues = self.engine.run("SELECT * FROM alumnos ORDER BY id").rows
        self.assertEqual(antes, despues)

    def test_04_rollback_de_create_table_y_create_index(self):
        self.engine.run("BEGIN TRANSACTION")
        self.engine.run("CREATE TABLE txn_tabla (id INT PRIMARY KEY, v INT)")
        self.engine.run("INSERT INTO txn_tabla VALUES (1, 1)")
        self.engine.run("CREATE INDEX idx_txn_v ON txn_tabla (v)")
        self.assertTrue(self.engine.catalog.has_table("txn_tabla"))

        self.engine.run("ROLLBACK")

        self.assertFalse(self.engine.catalog.has_table("txn_tabla"))

    def test_05_los_indices_quedan_coherentes_tras_el_rollback(self):
        self.engine.run("CREATE INDEX idx_alumnos_nota ON alumnos (nota)")

        self.engine.run("BEGIN TRANSACTION")
        self.engine.run("DELETE FROM alumnos WHERE nota < 14")
        self.engine.run("ROLLBACK")

        for identificador, nota in ((3, 14), (5, 0), (6, 12)):
            with self.subTest(id=identificador):
                por_clave = self.engine.run(
                    f"SELECT * FROM alumnos WHERE id = {identificador}"
                )
                self.assertEqual(len(por_clave.rows), 1)
                self.assertEqual(por_clave.rows[0]["nota"], nota)

                por_nota = self.engine.run(
                    f"SELECT * FROM alumnos WHERE nota = {nota} ORDER BY id"
                )
                self.assertTrue(por_nota.success, por_nota.error)
                self.assertTrue(
                    all(fila["nota"] == nota for fila in por_nota.rows)
                )

    def test_06_commit_y_rollback_sin_transaccion_activa(self):
        for sql in ("COMMIT", "ROLLBACK", "END TRANSACTION"):
            with self.subTest(sql=sql):
                resultado = self.engine.run(sql)
                self.assertFalse(resultado.success)
                self.assertIn(
                    "no hay una transacción activa", resultado.error or ""
                )

    def test_07_begin_anidado_es_un_error_claro(self):
        self.engine.run("BEGIN TRANSACTION")

        anidado = self.engine.run("BEGIN TRANSACTION")

        self.assertFalse(anidado.success)
        self.assertIn("ya hay una transacción activa", anidado.error or "")

        self.engine.run("ROLLBACK")

    def test_08_rollback_de_drop_table(self):
        self.engine.run("CREATE TABLE por_borrar (id INT PRIMARY KEY, v INT)")
        self.engine.import_csv("por_borrar", "id,v\n1,10\n2,20\n")

        self.engine.run("BEGIN TRANSACTION")
        self.engine.run("DROP TABLE por_borrar")
        self.assertFalse(self.engine.catalog.has_table("por_borrar"))

        self.engine.run("ROLLBACK")

        self.assertTrue(self.engine.catalog.has_table("por_borrar"))
        filas = self.engine.run("SELECT * FROM por_borrar ORDER BY id").rows
        self.assertEqual([fila["v"] for fila in filas], [10, 20])

    def test_09_explain_de_una_transaccion(self):
        resultado = self.engine.run("EXPLAIN BEGIN TRANSACTION")
        self.assertTrue(resultado.success, resultado.error)

        resultado = self.engine.run("EXPLAIN ANALYZE BEGIN TRANSACTION")
        self.assertTrue(resultado.success, resultado.error)
        self.assertIn("analyze", resultado.execution_plan)

        self.engine.run("ROLLBACK")

    def test_10_el_rollback_restaura_tambien_el_archivo_secuencial(self):
        self.engine.run(
            "CREATE TABLE seq_txn (id INT PRIMARY KEY, v INT) USING SEQUENTIAL"
        )
        self.engine.import_csv("seq_txn", "id,v\n1,1\n2,2\n3,3\n")

        self.engine.run("BEGIN TRANSACTION")
        self.engine.run("DELETE FROM seq_txn WHERE id = 2")
        self.engine.run("INSERT INTO seq_txn VALUES (9, 9)")
        self.engine.run("ROLLBACK")

        filas = self.engine.run("SELECT * FROM seq_txn ORDER BY id").rows
        self.assertEqual([fila["id"] for fila in filas], [1, 2, 3])


class TestPlannerMejorado(MotorAislado):

    def setUp(self):
        super().setUp()
        self.engine.run("CREATE INDEX idx_alumnos_nota ON alumnos (nota)")

    def test_01_rango_con_los_dos_extremos_usa_un_solo_recorrido(self):
        plan = self.plan(
            "EXPLAIN SELECT * FROM alumnos WHERE nota >= 14 AND nota <= 19"
        )

        self.assertEqual(plan["access_path"], "BPLUS_UNCLUSTERED_RANGE_SCAN")
        self.assertEqual(len(plan["used_indexes"]), 1)
        self.assertNotIn(
            "FILTER", [paso["operator"] for paso in plan["steps"]]
        )

        resultado = self.engine.run(
            "SELECT * FROM alumnos WHERE nota >= 14 AND nota <= 19 ORDER BY id"
        )
        self.assertEqual([fila["id"] for fila in resultado.rows], [3, 4, 8, 9, 10])

    def test_02_or_sobre_la_misma_columna_usa_union_de_indices(self):
        plan = self.plan(
            "EXPLAIN SELECT * FROM alumnos WHERE nota = 14 OR nota = 20"
        )

        self.assertEqual(plan["access_path"], "BPLUS_INDEX_UNION")
        self.assertEqual(plan["used_indexes"], ["idx_alumnos_nota"])

        resultado = self.engine.run(
            "SELECT * FROM alumnos WHERE nota = 14 OR nota = 20 ORDER BY id"
        )
        self.assertEqual(
            [fila["id"] for fila in resultado.rows], [3, 4, 10, 11]
        )

    def test_03_or_sobre_la_clave_primaria_usa_union_del_hash(self):
        resultado = self.engine.run(
            "SELECT * FROM alumnos WHERE id = 1 OR id = 5 ORDER BY id"
        )

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual(
            resultado.execution_plan["access_path"], "HASH_INDEX_UNION"
        )
        self.assertEqual([fila["id"] for fila in resultado.rows], [1, 5])

    def test_04_or_entre_columnas_distintas_no_pierde_filas(self):
        # No hay un índice común a los dos grupos: debe caer a escaneo y aun
        # así devolver todas las filas que cumplen cualquiera de las dos.
        resultado = self.engine.run(
            "SELECT * FROM alumnos WHERE id = 1 OR nota = 20 ORDER BY id"
        )

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual([fila["id"] for fila in resultado.rows], [1, 11])

    def test_05_where_con_predicados_en_columnas_distintas(self):
        resultado = self.engine.run(
            "SELECT * FROM alumnos WHERE carrera_id = 2 AND nota >= 14 ORDER BY id"
        )

        self.assertTrue(resultado.success, resultado.error)
        self.assertEqual([fila["id"] for fila in resultado.rows], [8, 10])


class TestLineaBaseDelBenchmark(unittest.TestCase):

    def test_el_benchmark_incluye_la_busqueda_sin_indice(self):
        from benchmarks.benchmark_indexes import BenchmarkConfig, run_benchmarks

        config = BenchmarkConfig(
            sizes=[16],
            seed=3,
            exact_queries=2,
            range_queries=2,
            mutation_operations=2,
            query_repeats=1,
            build_repeats=1,
            bplus_order=4,
            hash_bucket_capacity=4,
        )
        resultados = run_benchmarks(config)

        lineales = [r for r in resultados if r.metric == "linear_scan"]
        self.assertEqual(len(lineales), 1)
        self.assertEqual(lineales[0].index_type, "linear_scan")
        self.assertTrue(lineales[0].supported)
        self.assertEqual(lineales[0].operations, config.exact_queries)

        # Mide el mismo trabajo que la búsqueda indexada por igualdad.
        indexadas = [r for r in resultados if r.metric == "exact_hit"]
        self.assertTrue(indexadas)
        for fila in indexadas:
            self.assertEqual(fila.result_items, lineales[0].result_items)


if __name__ == "__main__":
    unittest.main()
