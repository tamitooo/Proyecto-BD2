import heapq
import os
import pickle
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, Optional, Sequence, Union


KeySpec = Union[str, Sequence[str], Callable[[Any], Any]]


@dataclass(frozen=True)
class ExternalSortStats:
    input_records: int = 0
    initial_runs: int = 0
    merge_passes: int = 0
    temporary_files: int = 0
    output_records: int = 0


class _SortAtom:
    __slots__ = ("value", "descending", "nulls_last")

    def __init__(self, value, descending=False, nulls_last=True):
        self.value = value
        self.descending = descending
        self.nulls_last = nulls_last

    def __eq__(self, other):
        if not isinstance(other, _SortAtom):
            return NotImplemented
        return self.value == other.value

    def __lt__(self, other):
        if self.value is None or other.value is None:
            if self.value is None and other.value is None:
                return False
            if self.nulls_last:
                return self.value is not None
            return self.value is None

        if self.descending:
            return self.value > other.value
        return self.value < other.value


class ExternalSort:
    """
    `memory_limit_records` limita cuántos registros se ordenan en RAM por run.
    `fan_in` limita cuántos runs se combinan simultáneamente.
    """

    def __init__(
        self,
        memory_limit_records: int = 1000,
        fan_in: int = 8,
        temp_dir: Optional[str] = None,
    ):
        if memory_limit_records < 1:
            raise ValueError("memory_limit_records must be >= 1")
        if fan_in < 2:
            raise ValueError("fan_in must be >= 2")

        if temp_dir is not None:
            os.makedirs(temp_dir, exist_ok=True)

        self.memory_limit_records = memory_limit_records
        self.fan_in = fan_in
        self.temp_dir = temp_dir
        self.last_stats = ExternalSortStats()

    def sort(
        self,
        records: Iterable[Any],
        key: KeySpec,
        descending: bool = False,
        nulls_last: bool = True,
        limit: Optional[int] = None,
    ):
        return list(
            self.sort_iter(
                records,
                key=key,
                descending=descending,
                nulls_last=nulls_last,
                limit=limit,
            )
        )

    def sort_iter(
        self,
        records: Iterable[Any],
        key: KeySpec,
        descending: bool = False,
        nulls_last: bool = True,
        limit: Optional[int] = None,
    ) -> Iterator[Any]:
        if limit is not None and limit < 0:
            raise ValueError("limit must be >= 0")

        extractor = self._build_key_extractor(key)

        return self._sort_generator(
            records,
            extractor,
            descending,
            nulls_last,
            limit,
        )

    def _sort_generator(
        self,
        records,
        extractor,
        descending,
        nulls_last,
        limit,
    ):
        all_temp_files = set()
        input_records = 0
        initial_runs = 0
        merge_passes = 0
        temp_files_created = 0
        output_records = 0
        final_iter = None

        try:
            if limit == 0:
                self.last_stats = ExternalSortStats()
                return

            runs = []
            batch = []

            for record in records:
                batch.append(record)
                input_records += 1

                if len(batch) >= self.memory_limit_records:
                    path = self._write_sorted_run(
                        batch,
                        extractor,
                        descending,
                        nulls_last,
                    )
                    runs.append(path)
                    all_temp_files.add(path)
                    temp_files_created += 1
                    initial_runs += 1
                    batch = []

            if batch:
                path = self._write_sorted_run(
                    batch,
                    extractor,
                    descending,
                    nulls_last,
                )
                runs.append(path)
                all_temp_files.add(path)
                temp_files_created += 1
                initial_runs += 1

            if not runs:
                self.last_stats = ExternalSortStats()
                return

            while len(runs) > self.fan_in:
                merge_passes += 1
                next_runs = []

                for start in range(0, len(runs), self.fan_in):
                    group = runs[start:start + self.fan_in]

                    merged_path = self._write_merged_run(
                        group,
                        extractor,
                        descending,
                        nulls_last,
                    )

                    next_runs.append(merged_path)
                    all_temp_files.add(merged_path)
                    temp_files_created += 1

                    for path in group:
                        self._safe_remove(path)
                        all_temp_files.discard(path)

                runs = next_runs

            if len(runs) > 1:
                merge_passes += 1
                final_iter = self._merge_runs(
                    runs,
                    extractor,
                    descending,
                    nulls_last,
                )
            else:
                final_iter = self._read_run(runs[0])

            for record in final_iter:
                if limit is not None and output_records >= limit:
                    break

                output_records += 1
                yield record

        finally:
            # Si LIMIT corta el consumo antes de terminar, los generadores
            # de _merge_runs() / _read_run() pueden seguir manteniendo
            # archivos abiertos. En Windows eso impide borrar los .run.
            if final_iter is not None and hasattr(final_iter, "close"):
                final_iter.close()

            for path in list(all_temp_files):
                self._safe_remove(path)

            self.last_stats = ExternalSortStats(
                input_records=input_records,
                initial_runs=initial_runs,
                merge_passes=merge_passes,
                temporary_files=temp_files_created,
                output_records=output_records,
            )

    def _write_sorted_run(
        self,
        records,
        extractor,
        descending,
        nulls_last,
    ):
        records.sort(
            key=lambda record: self._wrapped_key(
                extractor(record),
                descending,
                nulls_last,
            )
        )

        path = self._new_temp_path()

        with open(path, "wb") as file:
            for record in records:
                pickle.dump(record, file, protocol=pickle.HIGHEST_PROTOCOL)

        return path

    def _merge_runs(
        self,
        paths,
        extractor,
        descending,
        nulls_last,
    ):
        files = []
        heap = []

        try:
            for run_index, path in enumerate(paths):
                file = open(path, "rb")
                files.append(file)

                record = self._load_next(file)
                if record is None:
                    continue

                wrapped_key = self._wrapped_key(
                    extractor(record),
                    descending,
                    nulls_last,
                )

                heapq.heappush(
                    heap,
                    (wrapped_key, run_index, record),
                )

            while heap:
                _, run_index, record = heapq.heappop(heap)
                yield record

                next_record = self._load_next(files[run_index])
                if next_record is None:
                    continue

                wrapped_key = self._wrapped_key(
                    extractor(next_record),
                    descending,
                    nulls_last,
                )

                heapq.heappush(
                    heap,
                    (wrapped_key, run_index, next_record),
                )

        finally:
            for file in files:
                file.close()

    def _write_merged_run(
        self,
        paths,
        extractor,
        descending,
        nulls_last,
    ):
        output_path = self._new_temp_path()

        with open(output_path, "wb") as output:
            for record in self._merge_runs(
                paths,
                extractor,
                descending,
                nulls_last,
            ):
                pickle.dump(
                    record,
                    output,
                    protocol=pickle.HIGHEST_PROTOCOL,
                )

        return output_path

    def _read_run(self, path):
        with open(path, "rb") as file:
            while True:
                record = self._load_next(file)
                if record is None:
                    return
                yield record

    @staticmethod
    def _load_next(file):
        try:
            return pickle.load(file)
        except EOFError:
            return None

    @staticmethod
    def _build_key_extractor(key: KeySpec):
        if callable(key):
            return key

        if isinstance(key, str):
            def extract_field(record):
                if not isinstance(record, dict):
                    raise TypeError(
                        "string key requires records to be dictionaries"
                    )
                return record[key]
            return extract_field

        if isinstance(key, (tuple, list)):
            if not key:
                raise ValueError("key field sequence cannot be empty")

            fields = tuple(key)

            if not all(isinstance(field, str) for field in fields):
                raise TypeError("all key fields must be strings")

            def extract_fields(record):
                if not isinstance(record, dict):
                    raise TypeError(
                        "field sequence requires dictionary records"
                    )
                return tuple(record[field] for field in fields)

            return extract_fields

        raise TypeError(
            "key must be a field name, sequence of field names, or callable"
        )

    @classmethod
    def _wrapped_key(cls, value, descending, nulls_last):
        if isinstance(value, tuple):
            return tuple(
                _SortAtom(
                    item,
                    descending=descending,
                    nulls_last=nulls_last,
                )
                for item in value
            )

        return _SortAtom(
            value,
            descending=descending,
            nulls_last=nulls_last,
        )

    def _new_temp_path(self):
        file = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix="external_sort_",
            suffix=".run",
            dir=self.temp_dir,
            delete=False,
        )
        path = file.name
        file.close()
        return path

    @staticmethod
    def _safe_remove(path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
