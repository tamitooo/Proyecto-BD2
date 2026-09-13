import os

PAGE_SIZE = 4096  #bytes por pagina


class RID:
    """Record ID: identifica un registro por (num_pagina, num_slot)"""

    def __init__(self, page, slot):
        self.page = page
        self.slot = slot

    def __repr__(self):
        return f"RID({self.page},{self.slot})"

    def __eq__(self, other):
        return isinstance(other, RID) and self.page == other.page and self.slot == other.slot

    def __hash__(self):
        return hash((self.page, self.slot))

    def to_tuple(self):
        return (self.page, self.slot)


class HeapFile:
    """
    Estructura fisica del archivo .dat:
        [Pagina 0][Pagina 1][Pagina 2]...
        cada Pagina tiene un tamano fijo (PAGE_SIZE bytes) y contiene
        N = PAGE_SIZE // record_size slots para registros.
    """

    def __init__(self, path, schema):
        self.path = path
        self.schema = schema
        self.slots_per_page = max(1, PAGE_SIZE // schema.record_size)

        if not os.path.exists(path):
            open(path, "wb").close()

    # ---------------------- utilidades de paginacion ----------------------
    def _num_paginas(self):
        size = os.path.getsize(self.path)
        page_bytes = self.slots_per_page * self.schema.record_size
        return size // page_bytes if page_bytes else 0

    def _offset(self, page, slot):
        page_bytes = self.slots_per_page * self.schema.record_size
        return page * page_bytes + slot * self.schema.record_size

    def _leer_slot(self, f, page, slot):
        f.seek(self._offset(page, slot))
        raw = f.read(self.schema.record_size)
        if len(raw) < self.schema.record_size:
            return None, None
        return self.schema.unpack(raw)

    def _escribir_slot(self, f, page, slot, values, flag):
        f.seek(self._offset(page, slot))
        f.write(self.schema.pack(values, flag=flag))

    def _crear_pagina_nueva(self, f):
        """Agrega una pagina vacia al final del archivo y retorna su numero."""
        num_pag = self._num_paginas()
        f.seek(0, os.SEEK_END)
        vacio = self.schema.pack(
            {c: self._valor_por_defecto(c) for c in self.schema.col_names()},
            flag=self.schema.FLAG_EMPTY,
        )
        for _ in range(self.slots_per_page):
            f.write(vacio)
        return num_pag

    def _valor_por_defecto(self, colname):
        for fcol in self.schema.fields:
            if fcol.name == colname:
                return 0 if fcol.kind in ("INT", "FLOAT") else ""
        return ""

    def espacio_utilizado_bytes(self):
        return os.path.getsize(self.path)