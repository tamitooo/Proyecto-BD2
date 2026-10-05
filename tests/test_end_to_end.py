"""Prueba end-to-end de la Parte 1 sobre el **ejecutor oficial**.

Ejercita la cadena completa con el mismo camino que usan el API y la interfaz:

    SQL  ->  SQLParser  ->  QueryPlanner  ->  query.query_executor.QueryExecutor
                                                   |
             Heap File / Archivo Secuencial  <------+
             + B+ agrupado / B+ no agrupado / Hash Extendible
             + External Sort (ORDER BY)
             + External Hashing (GROUP BY y JOIN)

Antes estas pruebas usaban ``query/executor.py`` (ejecutor legado, ya
eliminado). Los operadores externos se crean con ``memory_limit_records=2`` a
propósito: obliga a escribir y releer *runs*/particiones en disco, es decir, se
prueba el camino externo real y no sólo el caso "todo cabe en memoria".
"""

import tempfile
import unittest

from operators.external_hashing import ExternalHashing
from operators.external_sort import ExternalSort
from query.catalog import Catalog
from query.query_executor import QueryExecutor

ALUMNOS = [
    (1, "Ana", 18.5, "CS"),
    (2, "Luis", 12.0, "CS"),
    (3, "Marta", 15.5, "DS"),
    (4, "Ivan", 9.5, "DS"),
    (5, "Rosa", 19.0, "CS"),
    (6, "Hugo", 14.0, "IA"),
]
MATRICULAS = [
    (100, 1, "CS101"),
    (101, 1, "CS102"),
    (102, 2, "CS101"),
    (103, 3, "DS201"),
    (104, 6, "IA301"),
    (105, 99, "XX999"),
]


def _operators(result):
    plan = result.execution_plan or {}
    steps = [step["operator"] for step in plan.get("steps", [])]
    steps += [step["operator"] for step in plan.get("runtime_steps", [])]
    return steps


class _EndToEndBase:
    """Mixin con las pruebas; se concreta por tipo de almacenamiento."""

    storage_kind = "heap"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.catalog = Catalog(data_dir=self.temp.name)
        self.executor = QueryExecutor(
            self.catalog,
            external_sort=ExternalSort(memory_limit_records=2, temp_dir=self.temp.name),
            external_hashing=ExternalHashing(
                memory_limit_records=2, temp_dir=self.temp.name
            ),
        )
        using = "SEQUENTIAL" if self.storage_kind == "sequential" else "HEAP"
        self._ok(
            "CREATE TABLE alumnos (id INT PRIMARY KEY, nombre VARCHAR(20), "
            f"nota FLOAT, carrera VARCHAR(10)) USING {using}"
        )
        self._ok(
            "CREATE TABLE matriculas (matricula INT PRIMARY KEY, id_alumno INT, "
            f"curso VARCHAR(10)) USING {using}"
        )
        for row in ALUMNOS:
            self._ok(f"INSERT INTO alumnos VALUES ({row[0]}, '{row[1]}', {row[2]}, '{row[3]}')")
        for row in MATRICULAS:
            self._ok(f"INSERT INTO matriculas VALUES ({row[0]}, {row[1]}, '{row[2]}')")
        # La PK ya tiene su índice Hash; se añaden los dos B+.
        self._ok("CREATE INDEX idx_alumnos_nota ON alumnos (nota) USING BPLUS_UNCLUSTERED")
        self._ok("CREATE INDEX idx_alumnos_carrera ON alumnos (carrera) USING BPLUS_CLUSTERED")

    def tearDown(self):
        self.temp.cleanup()

    def _sql(self, statement):
        return self.executor.execute(statement)

    def _ok(self, statement):
        result = self._sql(statement)
        self.assertTrue(result.success, f"{statement}: {result.error}")
        return result

    @staticmethod
    def _ids(result):
        return [row["id"] for row in result.rows]

    # ------------------------------------------------------------- lectura

    def test_select_all_devuelve_todos_los_registros(self):
        result = self._ok("SELECT * FROM alumnos")
        self.assertEqual(result.statement, "SELECT")
        self.assertEqual(sorted(self._ids(result)), [1, 2, 3, 4, 5, 6])

    def test_proyeccion_de_columnas(self):
        result = self._ok("SELECT nombre, nota FROM alumnos WHERE id = 3")
        self.assertEqual(result.columns, ["nombre", "nota"])
        self.assertEqual(result.rows, [{"nombre": "Marta", "nota": 15.5}])

    def test_where_con_igualdad_usa_el_indice_hash(self):
        result = self._ok("SELECT * FROM alumnos WHERE id = 4")
        self.assertIn("HASH_INDEX_LOOKUP", _operators(result))
        self.assertEqual([r["nombre"] for r in result.rows], ["Ivan"])

    def test_where_por_rango_usa_el_bplus_no_agrupado(self):
        result = self._ok("SELECT * FROM alumnos WHERE nota >= 15")
        self.assertIn("BPLUS_UNCLUSTERED_RANGE_SCAN", _operators(result))
        esperado = sorted(r[0] for r in ALUMNOS if r[2] >= 15)
        self.assertEqual(sorted(self._ids(result)), esperado)

    def test_where_con_between(self):
        result = self._ok("SELECT * FROM alumnos WHERE nota BETWEEN 12 AND 16")
        esperado = sorted(r[0] for r in ALUMNOS if 12 <= r[2] <= 16)
        self.assertEqual(sorted(self._ids(result)), esperado)

    def test_where_sin_indice_agrega_filtro(self):
        result = self._ok("SELECT * FROM alumnos WHERE nombre = 'Ana'")
        self.assertIn("FILTER", _operators(result))
        self.assertEqual(self._ids(result), [1])

    def test_order_by_desc_usa_external_sort(self):
        result = self._ok("SELECT * FROM alumnos ORDER BY id DESC")
        self.assertIn("EXTERNAL_SORT", _operators(result))
        self.assertEqual(self._ids(result), [6, 5, 4, 3, 2, 1])

    def test_order_by_cubierto_por_indice_agrupado(self):
        result = self._ok("SELECT * FROM alumnos ORDER BY carrera")
        self.assertNotIn("EXTERNAL_SORT", _operators(result))
        carreras = [row["carrera"] for row in result.rows]
        self.assertEqual(carreras, sorted(carreras))
        self.assertEqual(len(result.rows), len(ALUMNOS))

    def test_group_by_con_count(self):
        result = self._ok(
            "SELECT carrera, COUNT(*) AS total FROM alumnos GROUP BY carrera"
        )
        self.assertTrue(any("HASH" in op and "GROUP" in op for op in _operators(result)))
        totales = {row["carrera"]: row["total"] for row in result.rows}
        self.assertEqual(totales, {"CS": 3, "DS": 2, "IA": 1})

    def test_join_hash_entre_dos_tablas(self):
        result = self._ok(
            "SELECT alumnos.nombre, matriculas.curso FROM alumnos "
            "JOIN matriculas ON alumnos.id = matriculas.id_alumno"
        )
        self.assertIn("EXTERNAL_HASH_JOIN", _operators(result))
        # La matrícula 105 apunta a un alumno inexistente: no aparece.
        self.assertEqual(len(result.rows), 5)
        self.assertEqual(
            sorted((r["nombre"], r["curso"]) for r in result.rows),
            sorted(
                [
                    ("Ana", "CS101"),
                    ("Ana", "CS102"),
                    ("Luis", "CS101"),
                    ("Marta", "DS201"),
                    ("Hugo", "IA301"),
                ]
            ),
        )

    # --------------------------------------------------------------- DML

    def test_insert_delete_y_consulta_final(self):
        inserted = self._ok("INSERT INTO alumnos VALUES (7, 'Zoe', 17.0, 'IA')")
        self.assertEqual(inserted.affected_rows, 1)
        self.assertEqual(self._ok("SELECT * FROM alumnos WHERE id = 7").rows[0]["nombre"], "Zoe")

        deleted = self._ok("DELETE FROM alumnos WHERE id = 2")
        self.assertEqual(deleted.affected_rows, 1)
        self.assertEqual(len(self._ok("SELECT * FROM alumnos").rows), len(ALUMNOS))
        self.assertEqual(self._ok("SELECT * FROM alumnos WHERE id = 2").rows, [])
        # Los índices siguen coherentes tras el DML.
        rango = self._ok("SELECT * FROM alumnos WHERE nota >= 17")
        self.assertEqual(sorted(self._ids(rango)), [1, 5, 7])

    def test_pk_duplicada_es_error(self):
        result = self._sql("INSERT INTO alumnos VALUES (1, 'Otra', 10.0, 'CS')")
        self.assertFalse(result.success)

    def test_insert_con_columnas_de_menos_es_error(self):
        self.assertFalse(self._sql("INSERT INTO alumnos VALUES (8, 'X')").success)

    def test_sql_invalido_es_error_de_parseo(self):
        result = self._sql("TRUNCATE TABLE alumnos")
        self.assertFalse(result.success)
        self.assertIn("Unsupported", result.error)

    def test_tabla_desconocida(self):
        self.assertFalse(self._sql("SELECT * FROM profesores").success)

    def test_explain_muestra_el_plan_sin_ejecutar(self):
        result = self._ok("EXPLAIN SELECT * FROM alumnos WHERE id = 3")
        self.assertEqual(result.execution_plan["access_path"], "HASH_INDEX_LOOKUP")

    def test_external_sort_escribe_runs_en_disco(self):
        self._ok("SELECT * FROM alumnos ORDER BY nombre")
        stats = self.executor.external_sort.last_stats
        self.assertGreater(stats.initial_runs, 1)
        self.assertGreater(stats.temporary_files, 0)


class TestEndToEndHeap(_EndToEndBase, unittest.TestCase):
    storage_kind = "heap"


class TestEndToEndSecuencial(_EndToEndBase, unittest.TestCase):
    storage_kind = "sequential"


if __name__ == "__main__":
    unittest.main()
