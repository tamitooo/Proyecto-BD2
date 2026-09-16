"""Pruebas unitarias de `storage/record.py` (Field y Schema).

Cubren la capa mas basica del motor: serializacion de registros en bytes
de tamano fijo, que es la base de Heap File, Archivo Secuencial e indices.
"""

import unittest

from storage.record import Field, Schema


class TestField(unittest.TestCase):
    def test_int(self):
        field = Field("id", "INT")
        self.assertEqual(field.size, 4)
        self.assertEqual(field.fmt, "i")
        self.assertEqual(field.kind, "INT")

    def test_float(self):
        field = Field("nota", "FLOAT")
        self.assertEqual(field.size, 8)
        self.assertEqual(field.fmt, "d")
        self.assertEqual(field.kind, "FLOAT")

    def test_varchar(self):
        field = Field("nombre", "VARCHAR(30)")
        self.assertEqual(field.size, 30)
        self.assertEqual(field.fmt, "30s")
        self.assertEqual(field.kind, "VARCHAR")

    def test_tipo_es_insensible_a_mayusculas_y_espacios(self):
        field = Field("nombre", "  varchar(12) ")
        self.assertEqual(field.kind, "VARCHAR")
        self.assertEqual(field.size, 12)

    def test_tipo_no_soportado(self):
        with self.assertRaises(ValueError):
            Field("fecha", "DATE")


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.schema = Schema(
            [
                ("id", "INT"),
                ("nombre", "VARCHAR(10)"),
                ("nota", "FLOAT"),
            ],
            primary_key="id",
        )

    def test_tamano_de_registro(self):
        # 1 byte de flag + 4 (INT) + 10 (VARCHAR) + 8 (FLOAT)
        self.assertEqual(self.schema.record_size, 23)

    def test_clave_primaria_debe_existir(self):
        with self.assertRaises(ValueError):
            Schema([("id", "INT")], primary_key="inexistente")

    def test_pk_index_y_columnas(self):
        self.assertEqual(self.schema.pk_index(), 0)
        self.assertEqual(
            self.schema.col_names(),
            ["id", "nombre", "nota"],
        )

    def test_pack_unpack_roundtrip(self):
        record = {"id": 7, "nombre": "Ana", "nota": 15.5}
        raw = self.schema.pack(record)

        self.assertEqual(len(raw), self.schema.record_size)

        flag, values = self.schema.unpack(raw)
        self.assertEqual(flag, Schema.FLAG_USED)
        self.assertEqual(values["id"], 7)
        self.assertEqual(values["nombre"], "Ana")
        self.assertAlmostEqual(values["nota"], 15.5)

    def test_flag_por_defecto_y_explicito(self):
        record = {"id": 1, "nombre": "A", "nota": 1.0}

        flag, _ = self.schema.unpack(self.schema.pack(record))
        self.assertEqual(flag, Schema.FLAG_USED)

        flag, _ = self.schema.unpack(
            self.schema.pack(record, flag=Schema.FLAG_DELETED)
        )
        self.assertEqual(flag, Schema.FLAG_DELETED)

        flag, _ = self.schema.unpack(
            self.schema.pack(record, flag=Schema.FLAG_EMPTY)
        )
        self.assertEqual(flag, Schema.FLAG_EMPTY)

    def test_varchar_se_trunca_al_tamano_declarado(self):
        record = {"id": 2, "nombre": "nombre-muy-largo", "nota": 0.0}
        _flag, values = self.schema.unpack(self.schema.pack(record))

        self.assertEqual(len(values["nombre"]), 10)
        self.assertEqual(values["nombre"], "nombre-muy")

    def test_varchar_con_acentos_no_rompe_el_unpack(self):
        record = {"id": 3, "nombre": "José Pérez", "nota": 0.0}
        _flag, values = self.schema.unpack(self.schema.pack(record))

        self.assertTrue(values["nombre"].startswith("Jos"))

    def test_pack_coacciona_tipos_numericos(self):
        record = {"id": "9", "nombre": "B", "nota": "12.25"}
        _flag, values = self.schema.unpack(self.schema.pack(record))

        self.assertEqual(values["id"], 9)
        self.assertAlmostEqual(values["nota"], 12.25)

    def test_to_dict_from_dict(self):
        restored = Schema.from_dict(self.schema.to_dict())

        self.assertEqual(restored.col_names(), self.schema.col_names())
        self.assertEqual(restored.primary_key, self.schema.primary_key)
        self.assertEqual(restored.record_size, self.schema.record_size)


if __name__ == "__main__":
    unittest.main()
