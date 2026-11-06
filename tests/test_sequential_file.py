import os
import unittest
import tempfile
from storage.record import Schema
from storage.sequential_file import SequentialFile


class TestSequentialFile(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.file_path = os.path.join(self.test_dir.name, "test_seq")
        self.schema = Schema(
            [("id", "INT"), ("nombre", "VARCHAR(20)"), ("edad", "INT")],
            primary_key="id",
        )
        self.seq = SequentialFile(self.file_path, self.schema)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_insert_y_search(self):
        rec = {"id": 10, "nombre": "Alice", "edad": 25}
        rid = self.seq.insert(rec)
        self.assertEqual(rid.region, "aux")

        found_rid, found_val = self.seq.search(10)
        self.assertIsNotNone(found_rid)
        self.assertEqual(found_val["nombre"], "Alice")
        self.assertEqual(found_val["edad"], 25)

    def test_duplicado_pk_lanza_error(self):
        rec = {"id": 10, "nombre": "Alice", "edad": 25}
        self.seq.insert(rec)
        with self.assertRaises(ValueError):
            self.seq.insert(rec)

    def test_range_search(self):
        for i in [30, 10, 50, 20, 40]:
            self.seq.insert({"id": i, "nombre": f"User{i}", "edad": 20 + i})

        res = self.seq.range_search(15, 45)
        pks = [vals["id"] for _, vals in res]
        self.assertEqual(pks, [20, 30, 40])

    def test_delete_lazy(self):
        self.seq.insert({"id": 1, "nombre": "A", "edad": 20})
        self.assertTrue(self.seq.delete(1))

        rid, vals = self.seq.search(1)
        self.assertIsNone(rid)
        self.assertIsNone(vals)

    def test_reinsertar_tras_eliminacion(self):
        self.seq.insert({"id": 100, "nombre": "Original", "edad": 30})
        self.seq.reorganizar()

        self.assertTrue(self.seq.delete(100))
        rid_deleted, _ = self.seq.search(100)
        self.assertIsNone(rid_deleted)

        self.seq.insert({"id": 100, "nombre": "Reinsertado", "edad": 31})

        rid, vals = self.seq.search(100)
        self.assertIsNotNone(rid)
        self.assertEqual(rid.region, "aux")
        self.assertEqual(vals["nombre"], "Reinsertado")

    def test_reorganizacion_manual(self):
        for i in range(1, 10):
            self.seq.insert({"id": i, "nombre": f"Name{i}", "edad": 20 + i})

        self.seq.reorganizar()

        self.assertEqual(self.seq._num_registros(self.seq.aux_path), 0)

        rid, vals = self.seq.search(5)
        self.assertIsNotNone(rid)
        self.assertEqual(rid.region, "main")
        self.assertEqual(vals["nombre"], "Name5")

    def test_reorganizacion_automatica_por_desperdicio(self):
        for i in range(10):
            self.seq.insert({"id": i, "nombre": f"N{i}", "edad": 20})
        self.seq.reorganizar()
        
        reorg_prev = self.seq.n_reorganizaciones

        # Main tiene 10 registros, insertar 4 detonara reorganizacion (4/10 >= 0.3)
        for i in range(10, 14):
            self.seq.insert({"id": i, "nombre": f"N{i}", "edad": 20})

        self.assertGreater(self.seq.n_reorganizaciones, reorg_prev)


if __name__ == "__main__":
    unittest.main()