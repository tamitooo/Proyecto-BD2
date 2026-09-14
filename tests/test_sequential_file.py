import os
import unittest
import tempfile
from storage.record import Schema
from storage.sequential_file import SequentialFile


class TestSequentialFile(unittest.TestCase):
    def setUp(self):
        """Crea un directorio temporal y un Schema para las pruebas de SequentialFile."""
        self.test_dir = tempfile.TemporaryDirectory()
        self.file_path = os.path.join(self.test_dir.name, "test_seq")
        self.schema = Schema(
            [("id", "INT"), ("nombre", "VARCHAR(20)"), ("edad", "INT")],
            primary_key="id",
        )
        self.seq = SequentialFile(self.file_path, self.schema)

    def tearDown(self):
        """Limpia los archivos temporales generados tras cada prueba."""
        self.test_dir.cleanup()

    def test_insert_y_search(self):
        """Prueba insercion en zona auxiliar (.aux) y busqueda exitosa por clave primaria."""
        rec = {"id": 10, "nombre": "Alice", "edad": 25}
        rid = self.seq.insert(rec)
        self.assertEqual(rid.region, "aux")

        found_rid, found_val = self.seq.search(10)
        self.assertIsNotNone(found_rid)
        self.assertEqual(found_val["nombre"], "Alice")
        self.assertEqual(found_val["edad"], 25)

    def test_duplicado_pk_lanza_error(self):
        """Verifica que intentar insertar una clave primaria repetida lance un ValueError."""
        rec = {"id": 10, "nombre": "Alice", "edad": 25}
        self.seq.insert(rec)
        with self.assertRaises(ValueError):
            self.seq.insert(rec)

    def test_range_search(self):
        """Prueba la busqueda por rango [low_key, high_key] devolviendo registros ordenados."""
        for i in [30, 10, 50, 20, 40]:
            self.seq.insert({"id": i, "nombre": f"User{i}", "edad": 20 + i})

        res = self.seq.range_search(15, 45)
        pks = [vals["id"] for _, vals in res]
        self.assertEqual(pks, [20, 30, 40])

    def test_delete_lazy(self):
        """Prueba la eliminacion marcando como borrado (tombstone)."""
        self.seq.insert({"id": 1, "nombre": "A", "edad": 20})
        self.assertTrue(self.seq.delete(1))

        rid, vals = self.seq.search(1)
        self.assertIsNone(rid)
        self.assertIsNone(vals)

    def test_reinsertar_tras_eliminacion(self):
        """
        Caso Borde: Insertar -> Reorganizar a .main -> Borrar (tombstone en .main) -> 
        Reinsertar mismo ID en .aux -> Búsqueda debe encontrar el nuevo registro en .aux.
        """
        # 1. Insertar y reorganizar para que pase a .main
        self.seq.insert({"id": 100, "nombre": "Original", "edad": 30})
        self.seq.reorganizar()

        # 2. Borrar de .main
        self.assertTrue(self.seq.delete(100))
        rid_deleted, _ = self.seq.search(100)
        self.assertIsNone(rid_deleted)

        # 3. Reinsertar en .aux con el mismo ID
        self.seq.insert({"id": 100, "nombre": "Reinsertado", "edad": 31})

        # 4. Verificar que search lo encuentre en .aux
        rid, vals = self.seq.search(100)
        self.assertIsNotNone(rid)
        self.assertEqual(rid.region, "aux")
        self.assertEqual(vals["nombre"], "Reinsertado")

    def test_reorganizacion_manual(self):
        """Verifica la consolidacion de datos de .aux a .main y la limpieza de tombstones."""
        # Insertar varios registros
        for i in range(1, 10):
            self.seq.insert({"id": i, "nombre": f"Name{i}", "edad": 20 + i})

        # Ejecutar reorganizacion
        self.seq.reorganizar()

        # .aux debe quedar vacio
        self.assertEqual(self.seq._num_registros(self.seq.aux_path), 0)

        # Todos los registros deben buscarse en .main ahora
        rid, vals = self.seq.search(5)
        self.assertIsNotNone(rid)
        self.assertEqual(rid.region, "main")
        self.assertEqual(vals["nombre"], "Name5")

    def test_reorganizacion_automatica_por_desperdicio(self):
        """Prueba que la reorganizacion se dispare de forma automatica al superar el umbral (>30%)."""
        # 1. Cargar archivo y consolidar en main
        for i in range(10):
            self.seq.insert({"id": i, "nombre": f"N{i}", "edad": 20})
        self.seq.reorganizar()
        
        reorg_prev = self.seq.n_reorganizaciones

        # 2. Provocar desbordamiento en .aux (superar el 30% del tamaño de .main)
        # Main tiene 10 registros, insertar 4 detonara reorganizacion (4/10 >= 0.3)
        for i in range(10, 14):
            self.seq.insert({"id": i, "nombre": f"N{i}", "edad": 20})

        # Verificar que el contador de reorganizaciones se incremento
        self.assertGreater(self.seq.n_reorganizaciones, reorg_prev)


if __name__ == "__main__":
    unittest.main()