import os
import unittest
import tempfile
from storage.record import Schema
from storage.heap_file import HeapFile


def _get_page(rid):
    for attr in ("page_num", "page_index", "page", "page_id", "page_no"):
        if hasattr(rid, attr):
            return getattr(rid, attr)
    raise AttributeError(f"RID no tiene atributo de página reconocido: {dir(rid)}")


def _get_slot(rid):
    for attr in ("slot_num", "slot_index", "slot", "slot_id", "slot_no"):
        if hasattr(rid, attr):
            return getattr(rid, attr)
    raise AttributeError(f"RID no tiene atributo de slot reconocido: {dir(rid)}")


class TestHeapFile(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.file_path = os.path.join(self.test_dir.name, "test_heap.dat")
        self.schema = Schema(
            [("id", "INT"), ("nombre", "VARCHAR(20)"), ("nota", "FLOAT")],
            primary_key="id",
        )
        self.heap = HeapFile(self.file_path, self.schema)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_insert_y_read(self):
        rec = {"id": 1, "nombre": "Alice", "nota": 15.5}
        rid = self.heap.insert(rec)
        self.assertIsNotNone(rid)

        read_rec = self.heap.read(rid)
        self.assertIsNotNone(read_rec)
        self.assertEqual(read_rec["id"], 1)
        self.assertEqual(read_rec["nombre"], "Alice")
        self.assertAlmostEqual(read_rec["nota"], 15.5)

    def test_delete(self):
        rec = {"id": 2, "nombre": "Bob", "nota": 12.0}
        rid = self.heap.insert(rec)

        self.assertIsNotNone(self.heap.read(rid))

        res = self.heap.delete(rid)
        self.assertTrue(res)

        self.assertIsNone(self.heap.read(rid))

    def test_update(self):
        rec = {"id": 3, "nombre": "Charlie", "nota": 10.0}
        rid = self.heap.insert(rec)

        rec_updated = {"id": 3, "nombre": "Charlie", "nota": 18.5}
        success = self.heap.update(rid, rec_updated)
        self.assertTrue(success)

        read_rec = self.heap.read(rid)
        self.assertAlmostEqual(read_rec["nota"], 18.5)

    def test_scan(self):
        recs = [
            {"id": 10, "nombre": "User1", "nota": 11.0},
            {"id": 20, "nombre": "User2", "nota": 14.0},
            {"id": 30, "nombre": "User3", "nota": 19.0},
        ]
        for r in recs:
            self.heap.insert(r)

        scanned = list(self.heap.scan())
        self.assertEqual(len(scanned), 3)

        pks = [vals["id"] for _, vals in scanned]
        self.assertIn(10, pks)
        self.assertIn(20, pks)
        self.assertIn(30, pks)

    def test_reuso_espacio_libre(self):
        r1 = self.heap.insert({"id": 1, "nombre": "A", "nota": 10.0})
        self.heap.insert({"id": 2, "nombre": "B", "nota": 10.0})

        self.heap.delete(r1)

        r3 = self.heap.insert({"id": 3, "nombre": "C", "nota": 10.0})
        self.assertEqual(_get_page(r3), _get_page(r1))
        self.assertEqual(_get_slot(r3), _get_slot(r1))

    def test_desbordamiento_multiples_paginas(self):
        n_registros = 200
        rids = []
        for i in range(n_registros):
            rid = self.heap.insert(
                {"id": i, "nombre": f"Nombre_{i}", "nota": 10.0 + (i % 10)}
            )
            rids.append(rid)

        max_page = max(_get_page(r) for r in rids)
        self.assertGreater(max_page, 0)

        for i, rid in enumerate(rids):
            rec = self.heap.read(rid)
            self.assertIsNotNone(rec)
            self.assertEqual(rec["id"], i)


if __name__ == "__main__":
    unittest.main()