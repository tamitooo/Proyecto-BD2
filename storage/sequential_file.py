import os

REORG_AUX_RATIO = 0.3
REORG_WASTE_RATIO = 0.3


class RID:
    """Identifica un registro en el Archivo Secuencial por region ('main' o 'aux') y posicion."""

    def __init__(self, region, pos):
        self.region = region
        self.pos = pos

    def __repr__(self):
        return f"RID({self.region},{self.pos})"

    def __eq__(self, other):
        return isinstance(other, RID) and self.region == other.region and self.pos == other.pos

    def __hash__(self):
        return hash((self.region, self.pos))

    def to_tuple(self):
        return (self.region, self.pos)


class SequentialFile:
    """
    Archivo Secuencial Paginado con un archivo principal ordenado por PK y una
    zona auxiliar de overflow. La reorganización integra ambas regiones,
    elimina tombstones y vuelve a dejar el principal físicamente ordenado.
    """

    def __init__(self, path, schema):
        self.schema = schema
        self.main_path = path + ".main"
        self.aux_path = path + ".aux"
        for p in (self.main_path, self.aux_path):
            if not os.path.exists(p):
                open(p, "wb").close()
        self.n_reorganizaciones = 0
        self._tombstones_main = sum(
            1 for flag, _ in self._leer_todos(self.main_path)
            if flag == self.schema.FLAG_DELETED
        )

    def _leer_todos(self, path):
        registros = []
        rsize = self.schema.record_size
        with open(path, "rb") as f:
            data = f.read()
        n = len(data) // rsize
        for i in range(n):
            raw = data[i * rsize : (i + 1) * rsize]
            flag, values = self.schema.unpack(raw)
            registros.append((flag, values))
        return registros

    def _clave(self, values):
        return values[self.schema.primary_key]

    def _num_registros(self, path):
        return os.path.getsize(path) // self.schema.record_size

    def read_rid(self, rid):
        path = self.main_path if rid.region == "main" else self.aux_path
        rsize = self.schema.record_size
        with open(path, "rb") as f:
            f.seek(rid.pos * rsize)
            raw = f.read(rsize)
        if len(raw) < rsize:
            return None
        flag, values = self.schema.unpack(raw)
        return values if flag == self.schema.FLAG_USED else None

    def scan(self):
        for i, (flag, values) in enumerate(self._leer_todos(self.main_path)):
            if flag == self.schema.FLAG_USED:
                yield RID("main", i), values
        for i, (flag, values) in enumerate(self._leer_todos(self.aux_path)):
            if flag == self.schema.FLAG_USED:
                yield RID("aux", i), values

    def _busqueda_binaria_main(self, target_pk):
        n = self._num_registros(self.main_path)
        low, high = 0, n - 1
        rsize = self.schema.record_size
        with open(self.main_path, "rb") as f:
            while low <= high:
                mid = (low + high) // 2
                f.seek(mid * rsize)
                raw = f.read(rsize)
                flag, values = self.schema.unpack(raw)
                pk = self._clave(values)
                if pk == target_pk:
                    return mid, flag, values
                if pk < target_pk:
                    low = mid + 1
                else:
                    high = mid - 1
        return None

    def search(self, target_pk):
        res = self._busqueda_binaria_main(target_pk)
        if res is not None:
            pos, flag, values = res
            if flag == self.schema.FLAG_USED:
                return RID("main", pos), values
            return None, None
        for idx, (flag, vals) in enumerate(self._leer_todos(self.aux_path)):
            if flag == self.schema.FLAG_USED and self._clave(vals) == target_pk:
                return RID("aux", idx), vals
        return None, None

    def insert(self, values):
        pk = self._clave(values)
        rid_exist, _ = self.search(pk)
        if rid_exist is not None:
            raise ValueError(f"Clave primaria duplicada: {pk}")
        pos = self._num_registros(self.aux_path)
        with open(self.aux_path, "ab") as f:
            f.write(self.schema.pack(values, flag=self.schema.FLAG_USED))
        if self._necesita_reorganizar():
            self.reorganizar()
        return RID("aux", pos)

    def range_search(self, low_key, high_key):
        resultados = []
        for idx, (flag, vals) in enumerate(self._leer_todos(self.main_path)):
            if flag == self.schema.FLAG_USED:
                pk = self._clave(vals)
                if low_key <= pk <= high_key:
                    resultados.append((RID("main", idx), vals))
        for idx, (flag, vals) in enumerate(self._leer_todos(self.aux_path)):
            if flag == self.schema.FLAG_USED:
                pk = self._clave(vals)
                if low_key <= pk <= high_key:
                    resultados.append((RID("aux", idx), vals))
        resultados.sort(key=lambda x: self._clave(x[1]))
        return resultados

    def delete(self, target_pk):
        rsize = self.schema.record_size
        deleted = False
        res = self._busqueda_binaria_main(target_pk)
        if res is not None:
            pos, flag, values = res
            if flag == self.schema.FLAG_USED:
                with open(self.main_path, "r+b") as f:
                    f.seek(pos * rsize)
                    f.write(self.schema.pack(values, flag=self.schema.FLAG_DELETED))
                self._tombstones_main += 1
                deleted = True
        if not deleted:
            aux = self._leer_todos(self.aux_path)
            for i, (flag, values) in enumerate(aux):
                if flag == self.schema.FLAG_USED and self._clave(values) == target_pk:
                    with open(self.aux_path, "r+b") as f:
                        f.seek(i * rsize)
                        f.write(self.schema.pack(values, flag=self.schema.FLAG_DELETED))
                    deleted = True
                    break
        if deleted and self._necesita_reorganizar():
            self.reorganizar()
        return deleted

    def _necesita_reorganizar(self):
        n_main = self._num_registros(self.main_path)
        n_aux = self._num_registros(self.aux_path)
        if n_main == 0:
            return n_aux > 10
        ratio_aux = n_aux / float(n_main)
        ratio_tombstones = self._tombstones_main / float(n_main)
        return ratio_aux >= REORG_AUX_RATIO or ratio_tombstones >= REORG_WASTE_RATIO

    def reorganizar(self):
        validos = [vals for _, vals in self.scan()]
        validos.sort(key=self._clave)
        with open(self.main_path, "wb") as f:
            for vals in validos:
                f.write(self.schema.pack(vals, flag=self.schema.FLAG_USED))
        open(self.aux_path, "wb").close()
        self._tombstones_main = 0
        self.n_reorganizaciones += 1

    def replace_all(self, rows, *, key=None):
        """Reescribe todo el archivo en orden.

        Por defecto usa la clave primaria, que es la organización natural del
        archivo secuencial. ``key`` permite que el catálogo materialice un
        clustered B+ real cuando esa tabla se agrupa por otra columna.
        """
        rows = list(rows)
        rows.sort(key=key or self._clave)
        with open(self.main_path, "wb") as f:
            for row in rows:
                f.write(self.schema.pack(row, flag=self.schema.FLAG_USED))
        open(self.aux_path, "wb").close()
        self._tombstones_main = 0
        return len(rows)

    def espacio_utilizado_bytes(self):
        return os.path.getsize(self.main_path) + os.path.getsize(self.aux_path)
