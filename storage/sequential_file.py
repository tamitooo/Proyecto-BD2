import os


class RID:
    """Identifica un registro en el Archivo Secuencial por region ('main' o 'aux') y posicion."""

    def __init__(self, region, pos):
        self.region = region  # "main" o "aux"
        self.pos = pos        # indice del registro dentro de esa region

    def __repr__(self):
        return f"RID({self.region},{self.pos})"

    def to_tuple(self):
        return (self.region, self.pos)


class SequentialFile:
    """
    Estructura de Archivo Secuencial Paginado:
      - Archivo PRINCIPAL (.main): registros almacenados en disco ordenados por clave primaria.
      - Archivo AUXILIAR (.aux): zona de overflow donde se insertan los nuevos registros en orden de llegada.
    """

    def __init__(self, path, schema):
        self.schema = schema
        self.main_path = path + ".main"
        self.aux_path = path + ".aux"

        # Crear archivos binarios si no existen
        for p in (self.main_path, self.aux_path):
            if not os.path.exists(p):
                open(p, "wb").close()

        self.n_reorganizaciones = 0

    # ----------------------------- utilidades internas -----------------------------
    def _leer_todos(self, path):
        """Lee todos los registros raw de un archivo y los desempaca."""
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
        """Retorna el valor de la clave primaria para un registro."""
        return values[self.schema.primary_key]

    def _num_registros(self, path):
        """Retorna la cantidad total de slots (usados/borrados) en la region indicada."""
        return os.path.getsize(path) // self.schema.record_size

    # ----------------------------- acceso por RID -----------------------------
    def read_rid(self, rid):
        """Lee un registro a partir de un RID(region, pos). Retorna None si esta borrado."""
        path = self.main_path if rid.region == "main" else self.aux_path
        rsize = self.schema.record_size
        with open(path, "rb") as f:
            f.seek(rid.pos * rsize)
            raw = f.read(rsize)
        if len(raw) < rsize:
            return None
        flag, values = self.schema.unpack(raw)
        return values if flag == self.schema.FLAG_USED else None

    # ----------------------------- busqueda e insercion -----------------------------
    def _busqueda_binaria_main(self, target_pk):
        """Busqueda binaria directa en el archivo .main (asume que .main esta ordenado)."""
        n = self._num_registros(self.main_path)
        low = 0
        high = n - 1
        rsize = self.schema.record_size

        with open(self.main_path, "rb") as f:
            while low <= high:
                mid = (low + high) // 2
                f.seek(mid * rsize)
                raw = f.read(rsize)
                flag, values = self.schema.unpack(raw)
                pk = self._clave(values)

                if pk == target_pk:
                    if flag == self.schema.FLAG_USED:
                        return RID("main", mid), values
                    return None, None  # Registro marcado como eliminado
                elif pk < target_pk:
                    low = mid + 1
                else:
                    high = mid - 1
        return None, None

    def search(self, target_pk):
        """Busca por clave primaria: primero en .main (binaria) y luego en .aux (lineal)."""
        # 1. Busqueda binaria en .main
        rid, vals = self._busqueda_binaria_main(target_pk)
        if rid is not None:
            return rid, vals

        # 2. Busqueda lineal en .aux
        aux_regs = self._leer_todos(self.aux_path)
        for idx, (flag, vals) in enumerate(aux_regs):
            if flag == self.schema.FLAG_USED and self._clave(vals) == target_pk:
                return RID("aux", idx), vals

        return None, None

    def insert(self, values):
        """Inserta un registro nuevo. Se escribe en la zona auxiliar (.aux)."""
        pk = self._clave(values)
        # Verificar duplicados antes de insertar
        rid_exist, _ = self.search(pk)
        if rid_exist is not None:
            raise ValueError(f"Clave primaria duplicada: {pk}")

        pos = self._num_registros(self.aux_path)
        with open(self.aux_path, "ab") as f:
            f.write(self.schema.pack(values, flag=self.schema.FLAG_USED))

        return RID("aux", pos)

    def range_search(self, low_key, high_key):
        """Busqueda por rango [low_key, high_key] combinando .main y .aux."""
        resultados = []

        # Recorrer .main
        for idx, (flag, vals) in enumerate(self._leer_todos(self.main_path)):
            if flag == self.schema.FLAG_USED:
                pk = self._clave(vals)
                if low_key <= pk <= high_key:
                    resultados.append((RID("main", idx), vals))

        # Recorrer .aux
        for idx, (flag, vals) in enumerate(self._leer_todos(self.aux_path)):
            if flag == self.schema.FLAG_USED:
                pk = self._clave(vals)
                if low_key <= pk <= high_key:
                    resultados.append((RID("aux", idx), vals))

        # Ordenar los resultados por la clave primaria
        resultados.sort(key=lambda x: self._clave(x[1]))
        return resultados

    def espacio_utilizado_bytes(self):
        """Devuelve el peso total combinado de ambos archivos en disco."""
        return os.path.getsize(self.main_path) + os.path.getsize(self.aux_path)