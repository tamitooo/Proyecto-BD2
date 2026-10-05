from copy import deepcopy

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

    def _get_key(self, record):
        if not isinstance(record, dict):
            raise TypeError("record must be a dict")

        if self.key_field not in record:
            raise KeyError(
                f"record does not contain clustered key '{self.key_field}'"
            )

        return record[self.key_field]

    def insert(self, record):
        key = self._get_key(record)

        if self.unique and self.tree.search(key):
            raise ValueError(f"duplicate clustered key: {key}")

        self.tree.insert(key, deepcopy(record))

    def bulk_load(self, records):
        for record in records:
            self.insert(record)

    def search(self, key):
        return deepcopy(self.tree.search(key))

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
        return [deepcopy(record) for _, record in pairs]

    def scan(self, limit=None):
        return self.range_search(limit=limit)

    def delete(self, key, record=None):
        if record is None:
            return self.tree.delete(key)

        return self.tree.delete(key, record)

    def update(self, old_key, old_record, new_record):
        new_key = self._get_key(new_record)

        existing = self.tree.search(old_key)
        if old_record not in existing:
            return False

        if self.unique and new_key != old_key and self.tree.search(new_key):
            raise ValueError(f"duplicate clustered key: {new_key}")

        removed = self.tree.delete(old_key, old_record)
        if not removed:
            return False

        try:
            self.tree.insert(new_key, deepcopy(new_record))
        except Exception:
            self.tree.insert(old_key, deepcopy(old_record))
            raise

        return True

    def contains(self, key):
        return bool(self.tree.search(key))

    def validate(self):
        self.tree.validate()

        for key, record in self.tree.range_search():
            if self._get_key(record) != key:
                raise AssertionError(
                    "record stored under a key different from clustered key"
                )

        if self.unique:
            previous_key = None
            first = True

            for key, _ in self.tree.range_search():
                if not first and key == previous_key:
                    raise AssertionError(
                        "duplicate key in unique clustered index"
                    )
                previous_key = key
                first = False

        return True
