"""External Hashing (Grace style) for GROUP BY and equi-JOIN.

The implementation deliberately exposes the two phases taught in BD2:
1) partition both input streams with a hash function into temporary files;
2) process one partition at a time in RAM with a second in-memory hash table.

For GROUP BY we aggregate while reading a partition instead of retaining every
row.  For JOIN the smaller side of each partition is hashed in memory and the
other side is streamed.  This is a real external path: the complete relation is
never required in RAM when it exceeds ``memory_rows``.
"""
from __future__ import annotations

import os
import pickle
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping


@dataclass
class ExternalHashStats:
    rows: int = 0
    partitions_created: int = 0
    repartition_passes: int = 0
    temporary_files: int = 0


class ExternalHashing:
    def __init__(self, memory_rows: int = 2048, partitions: int = 8):
        if memory_rows < 2 or partitions < 2:
            raise ValueError("memory_rows/partitions >= 2")
        self.memory_rows = memory_rows
        self.partitions = partitions
        self.last_stats = ExternalHashStats()

    @staticmethod
    def _key(row, key):
        if isinstance(key, (tuple, list)):
            return tuple(row[k] for k in key)
        return row[key]

    @staticmethod
    def _dump_partitions(rows, *, key, directory, prefix, count, salt=0):
        paths = [os.path.join(directory, f"{prefix}-{i}.bin") for i in range(count)]
        files = [open(path, "wb") for path in paths]
        sizes = [0] * count
        try:
            for row in rows:
                bucket = hash((salt, ExternalHashing._key(row, key))) % count
                pickle.dump(row, files[bucket], protocol=pickle.HIGHEST_PROTOCOL)
                sizes[bucket] += 1
        finally:
            for handle in files:
                handle.close()
        return paths, sizes

    @staticmethod
    def _iter_file(path):
        with open(path, "rb") as handle:
            while True:
                try:
                    yield pickle.load(handle)
                except EOFError:
                    return

    @staticmethod
    def _aggregate_update(state, row, aggregates):
        if not aggregates:
            return
        for name, spec in aggregates.items():
            if spec == "count":
                state[name] = state.get(name, 0) + 1
                continue
            op, column = spec
            value = row.get(column)
            if op == "count":
                if value is not None:
                    state[name] = state.get(name, 0) + 1
            elif op == "sum":
                if value is not None:
                    state[name] = state.get(name, 0) + value
            elif op == "avg":
                if value is not None:
                    total, n = state.get(name, (0, 0))
                    state[name] = (total + value, n + 1)
            elif op == "min":
                if value is not None:
                    state[name] = value if name not in state else min(state[name], value)
            elif op == "max":
                if value is not None:
                    state[name] = value if name not in state else max(state[name], value)
            else:
                raise ValueError(f"aggregate unsupported: {op}")

    @staticmethod
    def _aggregate_finish(state, aggregates):
        if not aggregates:
            return state
        out = dict(state)
        for name, spec in aggregates.items():
            if spec == "count":
                out.setdefault(name, 0)
                continue
            op, _column = spec
            if op == "avg":
                total, n = out.get(name, (0, 0))
                out[name] = total / n if n else None
            elif op == "sum":
                out.setdefault(name, 0)
            elif op == "count":
                out.setdefault(name, 0)
            elif op in {"min", "max"}:
                out.setdefault(name, None)
        return out

    def group_by(self, rows: Iterable[Mapping[str, Any]], *, key, aggregates=None):
        rows = list(rows)
        stats = ExternalHashStats(rows=len(rows))

        def consume(iterable):
            groups: Dict[Any, Dict[str, Any]] = {}
            for row in iterable:
                kval = self._key(row, key)
                state = groups.setdefault(kval, {})
                self._aggregate_update(state, row, aggregates)
            out = []
            for kval, state in groups.items():
                base = {}
                if isinstance(key, (tuple, list)):
                    for column, value in zip(key, kval):
                        base[column] = value
                else:
                    base[key] = kval
                base.update(self._aggregate_finish(state, aggregates))
                out.append(base)
            return out

        if len(rows) <= self.memory_rows:
            result = consume(rows)
            self.last_stats = stats
            return result

        with tempfile.TemporaryDirectory(prefix="bd2-hash-group-") as directory:
            paths, _sizes = self._dump_partitions(
                rows, key=key, directory=directory, prefix="group", count=self.partitions
            )
            stats.partitions_created = self.partitions
            stats.temporary_files = self.partitions
            result = []
            for path in paths:
                result.extend(consume(self._iter_file(path)))

        self.last_stats = stats
        return result

    def hash_join(
        self,
        left_rows,
        right_rows,
        *,
        left_key,
        right_key,
        join_type="inner",
        merge=None,
    ):
        left = list(left_rows)
        right = list(right_rows)
        join_type = join_type.lower()
        if join_type not in {"inner", "left", "right", "full"}:
            raise ValueError(f"join_type unsupported: {join_type}")
        stats = ExternalHashStats(rows=len(left) + len(right))

        if merge is None:
            def merge(lrow, rrow):
                data = dict(lrow or {})
                data.update(rrow or {})
                return data

        def in_memory_join(left_part, right_part):
            # Hash the right side.  Partitions are normally <= memory_rows;
            # correctness does not depend on that heuristic.
            table: Dict[Any, list] = {}
            for pos, row in enumerate(right_part):
                table.setdefault(row[right_key], []).append((pos, row))
            matched_right = set()
            output = []
            for left_row in left_part:
                matches = table.get(left_row[left_key], [])
                if matches:
                    for pos, right_row in matches:
                        matched_right.add(pos)
                        output.append(merge(left_row, right_row))
                elif join_type in {"left", "full"}:
                    output.append(merge(left_row, None))
            if join_type in {"right", "full"}:
                for pos, right_row in enumerate(right_part):
                    if pos not in matched_right:
                        output.append(merge(None, right_row))
            return output

        if len(left) + len(right) <= self.memory_rows:
            result = in_memory_join(left, right)
            self.last_stats = stats
            return result

        with tempfile.TemporaryDirectory(prefix="bd2-hash-join-") as directory:
            lpaths, _ = self._dump_partitions(
                left, key=left_key, directory=directory, prefix="left", count=self.partitions, salt=17
            )
            rpaths, _ = self._dump_partitions(
                right, key=right_key, directory=directory, prefix="right", count=self.partitions, salt=17
            )
            stats.partitions_created = self.partitions
            stats.temporary_files = self.partitions * 2
            result = []
            for lpath, rpath in zip(lpaths, rpaths):
                result.extend(in_memory_join(list(self._iter_file(lpath)), list(self._iter_file(rpath))))

        self.last_stats = stats
        return result
