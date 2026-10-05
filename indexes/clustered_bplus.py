"""B+ Tree agrupado.

El árbol mantiene ``clave -> RID`` igual que un índice de disco real. La
propiedad *clustered* no se obtiene duplicando registros en las hojas: la
impone el catálogo reorganizando físicamente el archivo de datos por
``key_field`` antes de construir/reconstruir este índice. Solo puede existir un
índice agrupado por tabla.
"""
from .bplus_tree import BPlusTree


class ClusteredBPlusIndex:
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

    def _key(self, record):
        if not isinstance(record, dict):
            raise TypeError("record must be a dict")
        if self.key_field not in record:
            raise KeyError(f"record does not contain clustered key '{self.key_field}'")
        return record[self.key_field]

    def insert(self, record, rid):
        if rid is None:
            raise ValueError("rid is required")
        key = self._key(record)
        if self.unique and self.tree.search(key):
            raise ValueError(f"duplicate clustered key: {key}")
        self.tree.insert(key, rid)

    def insert_key(self, key, rid):
        if self.unique and self.tree.search(key):
            raise ValueError(f"duplicate clustered key: {key}")
        self.tree.insert(key, rid)

    def bulk_load(self, entries):
        for record, rid in entries:
            self.insert(record, rid)

    def search(self, key):
        return self.tree.search(key)

    def range_search(self, start=None, end=None, include_start=True, include_end=True, limit=None):
        return [rid for _, rid in self.tree.range_search(
            start=start, end=end, include_start=include_start,
            include_end=include_end, limit=limit,
        )]

    def range_entries(self, **kwargs):
        return self.tree.range_search(**kwargs)

    def scan(self, limit=None):
        return self.range_search(limit=limit)

    def delete(self, key, rid=None):
        return self.tree.delete(key, rid)

    def delete_record(self, record, rid):
        return self.tree.delete(self._key(record), rid)

    def contains(self, key):
        return bool(self.tree.search(key))

    def validate(self):
        return self.tree.validate()
