from .bplus_tree import BPlusTree


class UnclusteredBPlusIndex:
    """
    Indice B+ no agrupado (unclustered).

    Los registros permanecen en el archivo de datos. Las hojas del B+ Tree
    almacenan referencias (RIDs) hacia esos registros:

        key -> [RID, RID, ...]

    Esto desacopla el orden fisico de los registros del orden del indice.
    """

    def __init__(self, key_field, order=4, unique=False):
        if not key_field:
            raise ValueError("key_field is required")

        self.key_field = key_field
        self.unique = unique
        self.tree = BPlusTree(order=order)

    def __len__(self):
        return len(self.tree)

    @property
    def order(self):
        return self.tree.order

    def _get_key(self, record):
        if not isinstance(record, dict):
            raise TypeError("record must be a dict")

        if self.key_field not in record:
            raise KeyError(
                f"record does not contain indexed key '{self.key_field}'"
            )

        return record[self.key_field]

    def insert(self, record, rid):
        """
        Indexa un registro existente.

        El registro NO se almacena en el indice. Solo se guarda su RID bajo
        el valor de `key_field`.
        """
        if rid is None:
            raise ValueError("rid is required")

        key = self._get_key(record)

        if self.unique and self.tree.search(key):
            raise ValueError(f"duplicate indexed key: {key}")

        self.tree.insert(key, rid)

    def insert_key(self, key, rid):
        """
        Variante de bajo nivel para indexar directamente una clave y un RID.
        Util para integracion con operadores del motor.
        """
        if rid is None:
            raise ValueError("rid is required")

        if self.unique and self.tree.search(key):
            raise ValueError(f"duplicate indexed key: {key}")

        self.tree.insert(key, rid)

    def bulk_load(self, entries):
        """
        Carga pares (record, rid).

        Ejemplo:
            index.bulk_load([
                ({"id": 10, "name": "Ana"}, rid_1),
                ({"id": 20, "name": "Luis"}, rid_2),
            ])
        """
        for record, rid in entries:
            self.insert(record, rid)

    def search(self, key):
        """
        Retorna los RIDs asociados a una clave exacta.
        """
        return self.tree.search(key)

    def range_search(
        self,
        start=None,
        end=None,
        include_start=True,
        include_end=True,
        limit=None,
    ):
        """
        Retorna RIDs ordenados por la clave indexada.

        El indice no lee los registros. La resolucion RID -> registro
        corresponde al storage engine.
        """
        pairs = self.tree.range_search(
            start=start,
            end=end,
            include_start=include_start,
            include_end=include_end,
            limit=limit,
        )
        return [rid for _, rid in pairs]

    def range_entries(
        self,
        start=None,
        end=None,
        include_start=True,
        include_end=True,
        limit=None,
    ):
        """
        Retorna pares (key, RID). Es util para debugging, benchmarks y
        operadores que necesitan conservar la clave junto con la referencia.
        """
        return self.tree.range_search(
            start=start,
            end=end,
            include_start=include_start,
            include_end=include_end,
            limit=limit,
        )

    def scan(self, limit=None):
        """
        Recorre todos los RIDs en orden de la clave indexada.
        """
        return self.range_search(limit=limit)

    def scan_entries(self, limit=None):
        """
        Recorre todas las entradas como pares (key, RID).
        """
        return self.range_entries(limit=limit)

    def delete(self, key, rid=None):
        """
        Elimina entradas del indice.

        - delete(key): elimina todos los RIDs asociados a la clave.
        - delete(key, rid): elimina solo esa referencia.
        """
        return self.tree.delete(key, rid)

    def delete_record(self, record, rid):
        """
        Elimina la referencia correspondiente a un registro concreto.
        """
        key = self._get_key(record)
        return self.tree.delete(key, rid)

    def update(self, old_record, old_rid, new_record, new_rid=None):
        """
        Actualiza una entrada del indice cuando cambia el registro o su RID.

        Si cambia el valor de la columna indexada, la referencia se mueve a
        la nueva clave. Si cambia solamente el RID, se reemplaza la referencia.
        """
        old_key = self._get_key(old_record)
        new_key = self._get_key(new_record)
        target_rid = old_rid if new_rid is None else new_rid

        existing = self.tree.search(old_key)
        if old_rid not in existing:
            return False

        if self.unique and new_key != old_key and self.tree.search(new_key):
            raise ValueError(f"duplicate indexed key: {new_key}")

        removed = self.tree.delete(old_key, old_rid)
        if not removed:
            return False

        try:
            self.tree.insert(new_key, target_rid)
        except Exception:
            # Rollback simple para no perder la referencia original.
            self.tree.insert(old_key, old_rid)
            raise

        return True

    def contains(self, key):
        return bool(self.tree.search(key))

    def validate(self):
        """
        Valida las invariantes estructurales del B+ Tree y, para indices
        unicos, que cada clave tenga como maximo un RID.
        """
        self.tree.validate()

        if self.unique:
            previous_key = None
            first = True

            for key, _ in self.tree.range_search():
                if not first and key == previous_key:
                    raise AssertionError(
                        "duplicate key in unique unclustered index"
                    )
                previous_key = key
                first = False

        return True
