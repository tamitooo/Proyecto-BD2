"""Prueba end-to-end de la Parte 1 (issue #37).

Ejercita la cadena completa del motor con la API publica:

    SQL  ->  SQLParser  ->  QueryPlanner  ->  QueryExecutor
                                                   |
             Heap File / Archivo Secuencial  <------+
             + B+ agrupado / B+ no agrupado / Hash
             + External Sort (ORDER BY)
             + External Hashing (GROUP BY y JOIN)

Cada prueba usa `memory_limit_records=2` a proposito: obliga a que el
External Sort y el External Hashing escriban y vuelvan a leer archivos
temporales, es decir, ejercita el camino externo real y no solo el caso
"todo cabe en memoria".
"""

import os
import tempfile
import unittest

from query.executor import (
    Catalog,
    QueryExecutor,
    TableDefinition,
    clustered_index,
    hash_index,
    unclustered_index,
)
from query.sql_parser import SQLParseError
from storage.heap_file import HeapFile
from storage.record import Schema
from storage.sequential_file import SequentialFile


ALUMNOS = Schema(
    [
        ("id", "INT"),
        ("nombre", "VARCHAR(20)"),
        ("nota", "FLOAT"),
        ("carrera", "VARCHAR(10)"),
    ],
    primary_key="id",
)

MATRICULAS = Schema(
    [
        ("matricula", "INT"),
        ("id_alumno", "INT"),
        ("curso", "VARCHAR(10)"),
    ],
    primary_key="matricula",
)


ALUMNOS_DATA = [
    {"id": 1, "nombre": "Ana", "nota": 18.5, "carrera": "CS"},
    {"id": 2, "nombre": "Luis", "nota": 12.0, "carrera": "CS"},
    {"id": 3, "nombre": "Marta", "nota": 15.5, "carrera": "DS"},
    {"id": 4, "nombre": "Ivan", "nota": 9.5, "carrera": "DS"},
    {"id": 5, "nombre": "Rosa", "nota": 19.0, "carrera": "CS"},
    {"id": 6, "nombre": "Hugo", "nota": 14.0, "carrera": "IA"},
]

MATRICULAS_DATA = [
    {"matricula": 100, "id_alumno": 1, "curso": "CS101"},
    {"matricula": 101, "id_alumno": 1, "curso": "CS102"},
    {"matricula": 102, "id_alumno": 2, "curso": "CS101"},
    {"matricula": 103, "id_alumno": 3, "curso": "DS201"},
    {"matricula": 104, "id_alumno": 6, "curso": "IA301"},
    {"matricula": 105, "id_alumno": 99, "curso": "XX999"},
]


def _operators(result):
    return [step.operator for step in result.plan.steps]


class _EndToEndBase:
    """Mixin con las pruebas E2E; se concreta por tipo de almacenamiento."""

    storage_kind = "heap"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.temp_dir = self.temp.name
        self.catalog = Catalog()
        self.alumnos = self._table(
            "alumnos",
            ALUMNOS,
            ALUMNOS_DATA,
            indexes=[
                hash_index("id", bucket_capacity=2),
                unclustered_index("nota", order=4),
                clustered_index("carrera", order=4),
            ],
        )
        self.matriculas = self._table(
            "matriculas",
            MATRICULAS,
            MATRICULAS_DATA,
            indexes=[hash_index("matricula", bucket_capacity=2)],
        )
        self.executor = QueryExecutor(
            self.catalog,
            memory_limit_records=2,
            temp_dir=self.temp_dir,
        )

    def tearDown(self):
        self.temp.cleanup()

    # ---------------------- utilidades ----------------------
    def _table(self, name, schema, data, indexes=()):
        path = os.path.join(self.temp_dir, f"{name}.dat")

        if self.storage_kind == "heap":
            storage = HeapFile(path, schema)
        else:
            storage = SequentialFile(path, schema)

        table = TableDefinition(
            name=name,
            schema=schema,
            storage=storage,
            storage_kind=self.storage_kind,
        )

        for handle in indexes:
            table.add_index(handle)

        for record in data:
            table.insert(record)

        if self.storage_kind == "sequential":
            # Las reorganizaciones automaticas invalidan los RID indexados.
            table.rebuild_indexes()

        return self.catalog.register(table)

    def _sql(self, statement):
        return self.executor.execute_sql(statement)

    def _ids(self, result):
        return [row["id"] for row in result.rows]

    # ---------------------- pruebas ----------------------
    def test_select_all_devuelve_todos_los_registros(self):
        result = self._sql("SELECT * FROM alumnos")

        self.assertEqual(result.statement_kind, "SELECT")
        self.assertEqual(len(result.rows), len(ALUMNOS_DATA))
        self.assertEqual(sorted(self._ids(result)), [1, 2, 3, 4, 5, 6])

    def test_proyeccion_de_columnas(self):
        result = self._sql("SELECT nombre, nota FROM alumnos WHERE id = 3")

        self.assertEqual(len(result.rows), 1)
        self.assertEqual(
            result.rows[0],
            {"nombre": "Marta", "nota": 15.5},
        )

    def test_where_con_igualdad_usa_el_indice_hash(self):
        result = self._sql("SELECT * FROM alumnos WHERE id = 4")

        self.assertIn("HASH_INDEX_LOOKUP", _operators(result))
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["nombre"], "Ivan")

    def test_where_por_rango_usa_el_bplus_no_agrupado(self):
        result = self._sql("SELECT * FROM alumnos WHERE nota >= 15")

        self.assertIn("BPLUS_UNCLUSTERED_RANGE_SCAN", _operators(result))

        esperado = sorted(
            record["id"]
            for record in ALUMNOS_DATA
            if record["nota"] >= 15
        )
        self.assertEqual(sorted(self._ids(result)), esperado)

    def test_where_con_between(self):
        result = self._sql(
            "SELECT * FROM alumnos WHERE nota BETWEEN 12 AND 15.5"
        )

        esperado = sorted(
            record["id"]
            for record in ALUMNOS_DATA
            if 12 <= record["nota"] <= 15.5
        )
        self.assertEqual(sorted(self._ids(result)), esperado)

    def test_where_sin_indice_agrega_filtro(self):
        result = self._sql("SELECT * FROM alumnos WHERE nombre = 'Ana'")

        self.assertIn("FILTER", _operators(result))
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["id"], 1)

    def test_order_by_desc_usa_external_sort(self):
        result = self._sql("SELECT * FROM alumnos ORDER BY nota DESC")

        self.assertIn("EXTERNAL_SORT", _operators(result))

        notas = [row["nota"] for row in result.rows]
        self.assertEqual(notas, sorted(notas, reverse=True))
        self.assertEqual(result.rows[0]["nombre"], "Rosa")

    def test_order_by_cubierto_por_indice_agrupado(self):
        result = self._sql("SELECT * FROM alumnos ORDER BY carrera")

        self.assertIn("BPLUS_CLUSTERED_INDEX_SCAN", _operators(result))
        self.assertNotIn("EXTERNAL_SORT", _operators(result))

        carreras = [row["carrera"] for row in result.rows]
        self.assertEqual(carreras, sorted(carreras))
        self.assertEqual(len(result.rows), len(ALUMNOS_DATA))

    def test_where_y_order_by_sobre_la_misma_columna_indexada(self):
        result = self._sql(
            "SELECT * FROM alumnos WHERE nota >= 12 ORDER BY nota"
        )

        self.assertNotIn("EXTERNAL_SORT", _operators(result))

        notas = [row["nota"] for row in result.rows]
        self.assertEqual(notas, sorted(notas))
        self.assertTrue(all(nota >= 12 for nota in notas))

    def test_group_by_con_count_y_sum(self):
        result = self._sql(
            "SELECT carrera, COUNT(*), SUM(nota) "
            "FROM alumnos GROUP BY carrera"
        )

        self.assertIn("EXTERNAL_HASH_GROUP_BY", _operators(result))

        obtenido = {
            row["carrera"]: (row["COUNT(*)"], round(row["SUM(nota)"], 4))
            for row in result.rows
        }

        self.assertEqual(
            obtenido,
            {
                "CS": (3, round(18.5 + 12.0 + 19.0, 4)),
                "DS": (2, round(15.5 + 9.5, 4)),
                "IA": (1, 14.0),
            },
        )

    def test_join_hash_entre_dos_tablas(self):
        result = self._sql(
            "SELECT * FROM alumnos "
            "JOIN matriculas ON alumnos.id = matriculas.id_alumno"
        )

        self.assertIn("EXTERNAL_HASH_JOIN", _operators(result))

        # 5 matriculas tienen alumno existente; la 105 (id_alumno=99) no.
        self.assertEqual(len(result.rows), 5)

        pares = {(row["id"], row["matricula"]) for row in result.rows}
        self.assertEqual(
            pares,
            {(1, 100), (1, 101), (2, 102), (3, 103), (6, 104)},
        )
        self.assertTrue(all("curso" in row for row in result.rows))

    def test_insert_delete_y_consulta_final(self):
        inserted = self._sql(
            "INSERT INTO alumnos VALUES (7, 'Zoe', 17.0, 'IA')"
        )
        self.assertEqual(inserted.statement_kind, "INSERT")
        self.assertEqual(inserted.affected, 1)

        # El nuevo registro es visible por el indice hash.
        encontrado = self._sql("SELECT * FROM alumnos WHERE id = 7")
        self.assertEqual(len(encontrado.rows), 1)
        self.assertEqual(encontrado.rows[0]["nombre"], "Zoe")

        deleted = self._sql("DELETE FROM alumnos WHERE id = 2")
        self.assertEqual(deleted.affected, 1)

        restantes = self._sql("SELECT * FROM alumnos")
        self.assertEqual(len(restantes.rows), len(ALUMNOS_DATA))

        borrados = self._sql("SELECT * FROM alumnos WHERE id = 2")
        self.assertEqual(borrados.rows, [])

    def test_insert_con_columnas_de_mas_es_error(self):
        with self.assertRaises(ValueError):
            self._sql("INSERT INTO alumnos VALUES (8, 'X')")

    def test_sql_invalido_lanza_error_de_parseo(self):
        with self.assertRaises(SQLParseError):
            self._sql("UPDATE alumnos SET nota = 10")

    def test_tabla_desconocida(self):
        with self.assertRaises(KeyError):
            self._sql("SELECT * FROM profesores")

    def test_explain_muestra_el_plan(self):
        explicacion = self.executor.explain_sql(
            "SELECT * FROM alumnos WHERE id = 1 ORDER BY nota DESC"
        )

        self.assertIn("HASH_INDEX_LOOKUP", explicacion)
        self.assertIn("EXTERNAL_SORT", explicacion)
        self.assertIn("Access path:", explicacion)

    def test_estadisticas_de_los_operadores_externos(self):
        result = self._sql("SELECT * FROM alumnos ORDER BY nota DESC")

        self.assertIn("access_path", result.stats)
        self.assertEqual(len(result.rows), len(ALUMNOS_DATA))

    def test_reorganizacion_no_rompe_las_consultas(self):
        """En el Archivo Secuencial, reorganizar + reconstruir indices."""
        if self.storage_kind != "sequential":
            self.skipTest("solo aplica al Archivo Secuencial")

        for i in range(40):
            self._sql(
                f"INSERT INTO alumnos VALUES "
                f"({100 + i}, 'extra{i}', {float(i % 20)}, 'CS')"
            )

        self.assertGreater(self.alumnos.storage.n_reorganizaciones, 0)

        self.alumnos.rebuild_indexes()

        result = self._sql("SELECT * FROM alumnos WHERE id = 105")
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["nombre"], "extra5")

        todos = self._sql("SELECT * FROM alumnos")
        self.assertEqual(len(todos.rows), len(ALUMNOS_DATA) + 40)


class TestEndToEndHeap(_EndToEndBase, unittest.TestCase):
    storage_kind = "heap"


class TestEndToEndSecuencial(_EndToEndBase, unittest.TestCase):
    storage_kind = "sequential"


class TestCoherenciaEntreTecnicas(unittest.TestCase):
    """Las mismas consultas SQL deben dar el mismo resultado en heap y secuencial."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.catalog = Catalog()

        for kind, suffix in (("heap", "h"), ("sequential", "s")):
            path = os.path.join(self.temp.name, f"alumnos_{suffix}.dat")
            storage = (
                HeapFile(path, ALUMNOS)
                if kind == "heap"
                else SequentialFile(path, ALUMNOS)
            )
            table = TableDefinition(
                name=f"alumnos_{kind}",
                schema=ALUMNOS,
                storage=storage,
                storage_kind=kind,
            )
            table.add_index(hash_index("id", bucket_capacity=2))
            table.add_index(unclustered_index("nota", order=4))

            for record in ALUMNOS_DATA:
                table.insert(record)

            if kind == "sequential":
                table.rebuild_indexes()

            self.catalog.register(table)

        self.executor = QueryExecutor(
            self.catalog,
            memory_limit_records=2,
            temp_dir=self.temp.name,
        )

    def tearDown(self):
        self.temp.cleanup()

    def _normalize(self, rows):
        return sorted(
            (tuple(sorted(row.items())) for row in rows),
        )

    def test_igualdad_rango_y_orden_dan_lo_mismo(self):
        consultas = [
            ("SELECT * FROM {tabla}", False),
            ("SELECT * FROM {tabla} WHERE id = 5", False),
            ("SELECT * FROM {tabla} WHERE nota >= 15", False),
            ("SELECT * FROM {tabla} WHERE nota BETWEEN 12 AND 18.5", False),
            ("SELECT * FROM {tabla} ORDER BY nota", True),
            ("SELECT * FROM {tabla} ORDER BY nota DESC", True),
        ]

        for plantilla, comparar_orden in consultas:
            heap = self.executor.execute_sql(
                plantilla.format(tabla="alumnos_heap")
            )
            secuencial = self.executor.execute_sql(
                plantilla.format(tabla="alumnos_sequential")
            )

            self.assertEqual(
                self._normalize(heap.rows),
                self._normalize(secuencial.rows),
                msg=f"difieren para: {plantilla}",
            )

            if comparar_orden:
                self.assertEqual(
                    [row["id"] for row in heap.rows],
                    [row["id"] for row in secuencial.rows],
                    msg=f"orden distinto para: {plantilla}",
                )

    def test_group_by_igual_en_ambas_tecnicas(self):
        plantilla = (
            "SELECT carrera, COUNT(*) FROM {tabla} GROUP BY carrera"
        )

        heap = self.executor.execute_sql(
            plantilla.format(tabla="alumnos_heap")
        )
        secuencial = self.executor.execute_sql(
            plantilla.format(tabla="alumnos_sequential")
        )

        self.assertEqual(
            self._normalize(heap.rows),
            self._normalize(secuencial.rows),
        )


if __name__ == "__main__":
    unittest.main()
