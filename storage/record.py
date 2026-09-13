import struct
import re


class Field:
    def __init__(self, name, tipo):
        self.name = name
        self.tipo = tipo.upper().strip()
        self._parse_tipo()

    def _parse_tipo(self):
        m = re.match(r"VARCHAR\((\d+)\)", self.tipo)
        if self.tipo == "INT":
            self.fmt = "i"
            self.size = 4
            self.kind = "INT"
        elif self.tipo == "FLOAT":
            self.fmt = "d"
            self.size = 8
            self.kind = "FLOAT"
        elif m:
            n = int(m.group(1))
            self.fmt = f"{n}s"
            self.size = n
            self.kind = "VARCHAR"
        else:
            raise ValueError(f"Tipo de dato no soportado: {self.tipo}")


class Schema:
    FLAG_EMPTY = 0
    FLAG_USED = 1
    FLAG_DELETED = 2

    def __init__(self, columnas, primary_key):
        self.fields = [Field(n, t) for n, t in columnas]
        self.primary_key = primary_key
        if primary_key not in [f.name for f in self.fields]:
            raise ValueError("La clave primaria debe ser una columna del esquema")

        self.record_size = 1 + sum(f.size for f in self.fields)
        self._fmt = "<B" + "".join(f.fmt for f in self.fields)

    def pk_index(self):
        for i, f in enumerate(self.fields):
            if f.name == self.primary_key:
                return i
        return -1

    def col_names(self):
        return [f.name for f in self.fields]

    def pack(self, values, flag=FLAG_USED):
        packed_vals = []
        for f in self.fields:
            v = values.get(f.name)
            if f.kind == "INT":
                packed_vals.append(int(v))
            elif f.kind == "FLOAT":
                packed_vals.append(float(v))
            else:
                s = str(v).encode("utf-8")[: f.size]
                s = s.ljust(f.size, b"\x00")
                packed_vals.append(s)
        return struct.pack(self._fmt, flag, *packed_vals)

    def unpack(self, raw):
        vals = struct.unpack(self._fmt, raw)
        flag = vals[0]
        registro = {}
        for f, v in zip(self.fields, vals[1:]):
            if f.kind == "VARCHAR":
                registro[f.name] = v.rstrip(b"\x00").decode("utf-8", errors="ignore")
            else:
                registro[f.name] = v
        return flag, registro

    def to_dict(self):
        return {
            "columnas": [(f.name, f.tipo) for f in self.fields],
            "primary_key": self.primary_key,
        }

    @staticmethod
    def from_dict(d):
        return Schema(d["columnas"], d["primary_key"])