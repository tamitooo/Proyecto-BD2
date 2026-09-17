"""Pruebas de integracion entre storage e indices (issue #34).

A diferencia de los tests unitarios de cada modulo, aqui se verifica que
las piezas **funcionen juntas**:

    Heap File / Archivo Secuencial  +  B+ agrupado / B+ no agrupado / Hash

Se cubre ademas el detalle de integracion mas importante del proyecto:
la reorganizacion del Archivo Secuencial reescribe `.main` y **invalida
todos los RID**, por lo que el indice debe reconstruirse.
"""

import os
import tempfile
import unittest

from indexes.clustered_bplus import ClusteredBPlusIndex
from indexes.extendible_hash import ExtendibleHash
from indexes.unclustered_bplus import UnclusteredBPlusIndex
from storage.heap_file import HeapFile
from storage.record import Schema
from storage.sequential_file import SequentialFile

from query.executor import (
    Catalog,
    TableDefinition,
    clustered_index,
    hash_index,
    unclustered_index,
)


SCHEMA = Schema(
    [("id", "INT"), ("nombre", "VARCHAR(20)"), ("nota", "FLOAT")],
    primary_key="id",
)


def _records(count, offset=0):
    return [
        {
            "id": i + offset,
            "nombre": f"alumno-{i + offset:03d}",
            "nota": float((i + offset) % 20) + 0.5,
        }
        for i in range(count)
    ]


class TestHeapConIndices(unittest.TestCase):
    """Heap File (sin orden) + indices externos sobre la clave primaria."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "heap.dat")
        self.heap = HeapFile(self.path, SCHEMA)

    def tearDown(self):
        self.temp.cleanup()

    def test_hash_index_encuentra_el_registro_en_el_heap(self):
        hashed = ExtendibleHash(bucket_capacity=8)

        for record in _records(50):
            rid = self.heap.insert(record)
            hashed.insert(record["id"], rid)

        for key in (0, 17, 49):
            rids = hashed.search(key)
            self.assertEqual(len(rids), 1)

            stored = self.heap.read(rids[0])
            self.assertIsNotNone(stored)
            self.assertEqual(stored["id"], key)

    def test_bplus_no_agrupado_recupera_registros_por_rid(self):
        index = UnclusteredBPlusIndex(key_field="id", order=4)

        for record in _records(80):
            rid = self.heap.insert(record)
            index.insert(record, rid)

        index.validate()

        for key in (0, 40, 79):
            rids = index.search(key)
            self.assertEqual(len(rids), 1)
            self.assertEqual(self.heap.read(rids[0])["id"], key)

        rango = index.range_search(10, 19)
        self.assertEqual(len(rango), 10)

        recuperados = sorted(self.heap.read(rid)["id"] for rid in rango)
        self.assertEqual(recuperados, list(range(10, 20)))

    def test_borrado_mantiene_coherentes_heap_e_indice(self):
        hashed = ExtendibleHash(bucket_capacity=8)
        rids = {}

        for record in _records(30):
            rid = self.heap.insert(record)
            rids[record["id"]] = rid
            hashed.insert(record["id"], rid)

        target = 7
        self.assertTrue(self.heap.delete(rids[target]))
        self.assertTrue(hashed.delete(target, rids[target]))

        self.assertEqual(hashed.search(target), [])
        self.assertIsNone(self.heap.read(rids[target]))

        vivos = [values["id"] for _rid, values in self.heap.scan()]
        self.assertEqual(len(vivos), 29)
        self.assertNotIn(target, vivos)

    def test_espacio_se_reutiliza_tras_el_borrado(self):
        rids = [self.heap.insert(record) for record in _records(5)]

        self.heap.delete(rids[2])
        nuevo = self.heap.insert(
            {"id": 999, "nombre": "nuevo", "nota": 5.0}
        )

        self.assertEqual(nuevo.to_tuple(), rids[2].to_tuple())
        self.assertEqual(
            len(list(self.heap.scan())),
            5,
        )


class TestSecuencialConIndices(unittest.TestCase):
    """Archivo Secuencial Paginado + indices."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "seq.dat")
        self.sequential = SequentialFile(self.path, SCHEMA)

    def tearDown(self):
        self.temp.cleanup()

    def test_reorganizacion_deja_main_ordenado(self):
        for record in _records(40):
            self.sequential.insert(record)

        self.sequential.reorganizar()

        claves = [
            values["id"] for _rid, values in self.sequential.scan()
        ]
        self.assertEqual(claves, sorted(claves))

        # .main quedo ordenado y .aux vacio
        self.assertEqual(os.path.getsize(self.sequential.aux_path), 0)
        self.assertEqual(
            os.path.getsize(self.sequential.main_path),
            40 * SCHEMA.record_size,
        )

    def test_insercion_duplicada_lanza_error(self):
        self.sequential.insert({"id": 1, "nombre": "A", "nota": 1.0})

        with self.assertRaises(ValueError):
            self.sequential.insert({"id": 1, "nombre": "B", "nota": 2.0})

    def test_range_search_devuelve_ordenado(self):
        for record in _records(25):
            self.sequential.insert(record)

        resultados = self.sequential.range_search(5, 9)
        claves = [values["id"] for _rid, values in resultados]

        self.assertEqual(claves, [5, 6, 7, 8, 9])

    def test_eliminacion_lazy_y_espacio_desperdiciado(self):
        for record in _records(20):
            self.sequential.insert(record)

        self.sequential.reorganizar()
        self.assertTrue(self.sequential.delete(3))
        self.assertFalse(self.sequential.delete(3))

        vivos = [values["id"] for _rid, values in self.sequential.scan()]
        self.assertNotIn(3, vivos)

    def test_los_rid_cambian_al_reorganizar(self):
        """
        Documenta el contrato de integracion: `reorganizar()` invalida
        cualquier indice construido sobre RIDs anteriores.
        """
        self.sequential.insert({"id": 42, "nombre": "A", "nota": 3.0})

        rid_antes = self.sequential.search(42)[0]
        self.assertEqual(rid_antes.region, "aux")

        index = UnclusteredBPlusIndex(key_field="id", order=4)
        index.insert({"id": 42}, rid_antes)

        self.sequential.reorganizar()

        rid_despues = self.sequential.search(42)[0]
        self.assertEqual(rid_despues.region, "main")
        self.assertNotEqual(rid_antes.to_tuple(), rid_despues.to_tuple())

        # El indice viejo apunta a un RID que ya no existe.
        self.assertIsNone(self.sequential.read_rid(rid_antes))
        self.assertIsNone(self.sequential.read_rid(index.search(42)[0]))

        # Reconstruirlo restablece la consistencia.
        nuevo = UnclusteredBPlusIndex(key_field="id", order=4)
        for rid, record in self.sequential.scan():
            nuevo.insert(record, rid)

        encontrados = nuevo.search(42)
        self.assertEqual(len(encontrados), 1)
        self.assertEqual(self.sequential.read_rid(encontrados[0])["id"], 42)


class TestTableDefinitionYCAtalogo(unittest.TestCase):
    """Integracion storage + indices + catalogo del ejecutor."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def _table(self, kind="heap"):
        path = os.path.join(self.temp.name, f"{kind}.dat")

        if kind == "heap":
            storage = HeapFile(path, SCHEMA)
        else:
            storage = SequentialFile(path, SCHEMA)

        table = TableDefinition(
            name="alumnos",
            schema=SCHEMA,
            storage=storage,
            storage_kind=kind,
        )
        table.add_index(hash_index("id", bucket_capacity=8))
        table.add_index(unclustered_index("nota", order=4))
        return table

    def _revisar_tabla(self, table, rebuild=False):
        for record in _records(60):
            table.insert(record)

        if rebuild:
            # En el Archivo Secuencial las reorganizaciones automaticas
            # invalidan los RID ya indexados: hay que reconstruir.
            table.rebuild_indexes()

        for handle in table.indexes.values():
            if hasattr(handle.index, "validate"):
                handle.index.validate()

        record = {
            "id": 3,
            "nombre": "alumno-003",
            "nota": 3.5,
        }

        # El hash resuelve la igualdad exacta.
        rids = table.indexes["id"].index.search(3)
        self.assertEqual(len(rids), 1)
        self.assertEqual(table.read_rid(rids[0]), record)

        # El B+ no agrupado sigue devolviendo RIDs validos.
        rids_nota = table.indexes["nota"].index.search(3.5)
        self.assertTrue(rids_nota)
        self.assertEqual(table.read_rid(rids_nota[0])["nota"], 3.5)

        # Borrado coherente en storage e indices.
        self.assertTrue(table.delete(record, rids[0]))
        self.assertEqual(table.indexes["id"].index.search(3), [])
        self.assertIsNone(table.read_rid(rids[0]))

    def test_tabla_sobre_heap(self):
        self._revisar_tabla(self._table("heap"))

    def test_tabla_sobre_secuencial(self):
        table = self._table("sequential")
        self._revisar_tabla(table, rebuild=True)

        # Tras reorganizar, reconstruir los indices mantiene las busquedas.
        table.storage.reorganizar()
        reconstruidos = table.rebuild_indexes()
        self.assertEqual(reconstruidos, 2)

    def test_indice_agrupado_sobre_tabla(self):
        table = self._table("heap")
        handle = clustered_index("id", order=4)
        table.add_index(handle)

        for record in _records(30):
            table.insert(record)

        handle.index.validate()

        encontrados = handle.index.search(10)
        self.assertEqual(len(encontrados), 1)
        self.assertEqual(encontrados[0]["id"], 10)

        rango = handle.index.range_search(4, 6)
        self.assertEqual([row["id"] for row in rango], [4, 5, 6])

    def test_catalogo_expone_metadatos_e_storage(self):
        catalog = Catalog()
        catalog.register(self._table("heap"))

        metadata = catalog.index_metadata()
        columnas = {(item.column, item.kind) for item in metadata}

        self.assertEqual(
            columnas,
            {
                ("id", "hash"),
                ("nota", "bplus_unclustered"),
            },
        )
        self.assertEqual(catalog.storage_map(), {"alumnos": "heap"})


class TestEquivalenciaEntreTecnicas(unittest.TestCase):
    """El mismo dataset debe producir el mismo contenido en ambas tecnicas."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def test_heap_y_secuencial_guardan_lo_mismo(self):
        records = _records(120)

        heap = HeapFile(os.path.join(self.temp.name, "h.dat"), SCHEMA)
        for record in records:
            heap.insert(record)

        sequential = SequentialFile(
            os.path.join(self.temp.name, "s.dat"),
            SCHEMA,
        )
        for record in records:
            sequential.insert(record)
        sequential.reorganizar()

        desde_heap = {values["id"]: values for _rid, values in heap.scan()}
        desde_secuencial = {
            values["id"]: values for _rid, values in sequential.scan()
        }

        self.assertEqual(len(desde_heap), len(records))
        self.assertEqual(set(desde_heap), set(desde_secuencial))

        for key, record in desde_heap.items():
            self.assertEqual(record, desde_secuencial[key])

    def test_misma_busqueda_en_ambas_tecnicas(self):
        records = _records(50)

        heap = HeapFile(os.path.join(self.temp.name, "h2.dat"), SCHEMA)
        for record in records:
            heap.insert(record)

        sequential = SequentialFile(
            os.path.join(self.temp.name, "s2.dat"),
            SCHEMA,
        )
        for record in records:
            sequential.insert(record)
        sequential.reorganizar()

        for key in (0, 13, 49):
            encontrado_heap = [
                values for _rid, values in heap.scan() if values["id"] == key
            ]
            _rid, encontrado_seq = sequential.search(key)

            self.assertEqual(len(encontrado_heap), 1)
            self.assertEqual(encontrado_heap[0], encontrado_seq)


if __name__ == "__main__":
    unittest.main()
