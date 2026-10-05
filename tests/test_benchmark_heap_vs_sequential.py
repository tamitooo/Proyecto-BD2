"""Valida la metodologia del benchmark Heap vs Secuencial (issue #29).

El benchmark usa "carga masiva" (escritura directa del archivo pagina a
pagina) para poder medir 100 000 registros sin pagar el costo de la
insercion uno a uno. Estas pruebas garantizan que el archivo generado por
la carga masiva es **identico** al que produce la API publica, de modo que
las mediciones de busqueda y de espacio siguen siendo validas.
"""

import os
import pickle
import tempfile
import unittest

from benchmarks.benchmark_heap_vs_sequential import (
    DEFAULT_SCHEMA,
    _heap_lookup,
    bulk_build_heap,
    bulk_build_sequential,
)
from storage.heap_file import PAGE_SIZE, HeapFile
from storage.record import Schema
from storage.sequential_file import SequentialFile


SCHEMA = DEFAULT_SCHEMA


def _records(count, offset=0):
    return [
        {
            "id": i + offset,
            "nombre": f"registro-{i + offset:08d}",
            "nota": float((i + offset) % 1000) + 0.5,
        }
        for i in range(count)
    ]


class TestBulkLoadHeap(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_archivo_identico_al_de_insercion_uno_a_uno(self):
        records = _records(250)
        slots_per_page = PAGE_SIZE // SCHEMA.record_size

        # Al menos una pagina completa y una parcial.
        self.assertGreater(250 // slots_per_page, 1)

        incremental = os.path.join(self.temp.name, "incremental.dat")
        heap = HeapFile(incremental, SCHEMA)
        for record in records:
            heap.insert(record)

        bulk = os.path.join(self.temp.name, "bulk.dat")
        bulk_build_heap(bulk, records, SCHEMA)

        with open(incremental, "rb") as handle:
            esperado = handle.read()

        with open(bulk, "rb") as handle:
            obtenido = handle.read()

        self.assertEqual(obtenido, esperado)

        with open(incremental + ".free", "rb") as handle:
            free_esperado = pickle.load(handle)

        with open(bulk + ".free", "rb") as handle:
            free_obtenido = pickle.load(handle)

        self.assertEqual(free_obtenido, free_esperado)

    def test_archivo_identico_cuando_las_paginas_quedan_exactas(self):
        slots_per_page = PAGE_SIZE // SCHEMA.record_size
        total = slots_per_page * 3
        records = _records(total)

        incremental = os.path.join(self.temp.name, "exacto_incremental.dat")
        heap = HeapFile(incremental, SCHEMA)
        for record in records:
            heap.insert(record)

        bulk = os.path.join(self.temp.name, "exacto_bulk.dat")
        bulk_build_heap(bulk, records, SCHEMA)

        with open(incremental, "rb") as handle:
            esperado = handle.read()

        with open(bulk, "rb") as handle:
            obtenido = handle.read()

        self.assertEqual(obtenido, esperado)

        with open(bulk + ".free", "rb") as handle:
            self.assertEqual(pickle.load(handle), set())

    def test_el_archivo_bulk_es_legible_por_la_api(self):
        path = os.path.join(self.temp.name, "legible.dat")
        records = _records(120)
        bulk_build_heap(path, records, SCHEMA)

        heap = HeapFile(path, SCHEMA)
        escaneados = {values["id"]: values for _rid, values in heap.scan()}

        self.assertEqual(len(escaneados), len(records))
        self.assertEqual(escaneados[7], records[7])

    def test_busqueda_lineal_del_benchmark(self):
        path = os.path.join(self.temp.name, "lookup.dat")
        records = _records(40)
        bulk_build_heap(path, records, SCHEMA)
        heap = HeapFile(path, SCHEMA)

        rid, encontrado = _heap_lookup(heap, 25)
        self.assertIsNotNone(rid)
        self.assertEqual(encontrado["id"], 25)

        rid, encontrado = _heap_lookup(heap, 10_000)
        self.assertIsNone(rid)
        self.assertIsNone(encontrado)


class TestBulkLoadSequential(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_main_identico_al_de_insert_mas_reorganizacion(self):
        records = _records(80)

        incremental = os.path.join(self.temp.name, "incremental.dat")
        sequential = SequentialFile(incremental, SCHEMA)
        for record in records:
            sequential.insert(record)
        sequential.reorganizar()

        bulk = os.path.join(self.temp.name, "bulk.dat")
        bulk_build_sequential(bulk, records, SCHEMA)

        with open(incremental + ".main", "rb") as handle:
            esperado = handle.read()

        with open(bulk + ".main", "rb") as handle:
            obtenido = handle.read()

        self.assertEqual(obtenido, esperado)
        self.assertEqual(os.path.getsize(bulk + ".aux"), 0)

    def test_bulk_queda_ordenado_por_clave_primaria(self):
        path = os.path.join(self.temp.name, "ordenado.dat")
        records = list(reversed(_records(30)))
        bulk_build_sequential(path, records, SCHEMA)

        sequential = SequentialFile(path, SCHEMA)
        claves = [values["id"] for _rid, values in sequential.scan()]

        self.assertEqual(claves, sorted(claves))

    def test_busqueda_binaria_sobre_archivo_bulk(self):
        path = os.path.join(self.temp.name, "busqueda.dat")
        records = _records(64)
        bulk_build_sequential(path, records, SCHEMA)

        sequential = SequentialFile(path, SCHEMA)

        for key in (0, 31, 63):
            rid, values = sequential.search(key)
            self.assertIsNotNone(rid)
            self.assertEqual(values["id"], key)

        rid, values = sequential.search(999)
        self.assertIsNone(rid)
        self.assertIsNone(values)


class TestSchemaDelBenchmark(unittest.TestCase):
    def test_tamano_de_registro_estable(self):
        """El benchmark asume un record_size fijo: 1 + 4 + 30 + 8 bytes."""
        self.assertEqual(SCHEMA.record_size, 43)
        self.assertEqual(SCHEMA.primary_key, "id")
        self.assertIsInstance(SCHEMA, Schema)


if __name__ == "__main__":
    unittest.main()
