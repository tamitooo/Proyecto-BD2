from .bplus_tree import BPlusTree


class UnclusteredBPlusIndex:
    
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
        if rid is None:
            raise ValueError("rid is required")

        if self.unique and self.tree.search(key):
            raise ValueError(f"duplicate indexed key: {key}")

        self.tree.insert(key, rid)

    def bulk_load(self, entries):
        for record, rid in entries:
            self.insert(record, rid)

    def search(self, key):
        return self.tree.search(key)

    def range_search(
        self,
        start=None,
        end=None,
        include_start=True,
        include_end=True,
        limit=None,
    ):
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
        return self.tree.range_search(
            start=start,
            end=end,
            include_start=include_start,
            include_end=include_end,
            limit=limit,
        )

    def scan(self, limit=None):
        return self.range_search(limit=limit)

    def scan_entries(self, limit=None):
        return self.range_entries(limit=limit)

    def delete(self, key, rid=None):
        return self.tree.delete(key, rid)

    def delete_record(self, record, rid):
        key = self._get_key(record)
        return self.tree.delete(key, rid)

    def update(self, old_record, old_rid, new_record, new_rid=None):
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
