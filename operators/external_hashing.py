import os
import pickle
import tempfile
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Union


KeySpec = Union[str, Sequence[str], Callable[[Any], Any]]
AggregateSpec = Union[
    str,
    tuple,
]


@dataclass(frozen=True)
class ExternalHashStats:
    operation: str = ""
    input_records: int = 0
    left_records: int = 0
    right_records: int = 0
    partitions_created: int = 0
    repartition_passes: int = 0
    temporary_files: int = 0
    max_partition_records: int = 0
    output_records: int = 0


class ExternalHashing:
    """
    Esto implementa el patrón de Grace Hashing:
        input -> hash partitions -> procesamiento por partición

    Las filas pueden ser diccionarios, tuplas `(RID, record)` u otros
    objetos serializables con pickle, siempre que se proporcione una
    especificación de clave válida.
    """

    SUPPORTED_AGGREGATES = {"count", "sum", "min", "max", "avg"}
    SUPPORTED_JOINS = {"inner", "left", "right", "full"}

    def __init__(
        self,
        memory_limit_records: int = 1000,
        partition_count: int = 8,
        temp_dir: Optional[str] = None,
        max_depth: int = 8,
    ):
        if memory_limit_records < 1:
            raise ValueError("memory_limit_records must be >= 1")
        if partition_count < 2:
            raise ValueError("partition_count must be >= 2")
        if max_depth < 0:
            raise ValueError("max_depth must be >= 0")

        if temp_dir is not None:
            os.makedirs(temp_dir, exist_ok=True)

        self.memory_limit_records = memory_limit_records
        self.partition_count = partition_count
        self.temp_dir = temp_dir
        self.max_depth = max_depth
        self.last_stats = ExternalHashStats()

    # ------------------------------------------------------------------
    # GROUP BY
    # ------------------------------------------------------------------

    def group_by(
        self,
        records: Iterable[Any],
        key: KeySpec,
        aggregates: Optional[Mapping[str, AggregateSpec]] = None,
        key_name: Optional[str] = None,
    ):
        """
        Ejecuta GROUP BY usando particionado hash externo.

        `aggregates` es un mapping:
            {
                "rows": "count",
                "total_salary": ("sum", "salary"),
                "avg_salary": ("avg", "salary"),
                "min_salary": ("min", "salary"),
                "max_salary": ("max", "salary"),
            }

        Para COUNT(*):
            "rows": "count"

        Para COUNT(campo):
            "non_null": ("count", "campo")

        El resultado es una lista de diccionarios. No se garantiza orden,
        como corresponde a un operador hash.
        """
        extractor = self._build_key_extractor(key)
        aggregate_defs = self._normalize_aggregates(aggregates)

        all_temp_files = set()
        partitions_created = 0
        repartition_passes = 0
        temp_files_created = 0
        max_partition_records = 0
        input_records = 0
        output = []

        try:
            paths, counts, consumed = self._partition_iterable(
                records,
                extractor,
                depth=0,
            )
            input_records = consumed
            partitions_created += len(paths)
            temp_files_created += len(paths)
            all_temp_files.update(paths)

            if counts:
                max_partition_records = max(counts)

            for path, count in zip(paths, counts):
                groups, created, passes, max_seen = self._group_partition(
                    path=path,
                    count=count,
                    extractor=extractor,
                    aggregate_defs=aggregate_defs,
                    depth=0,
                    all_temp_files=all_temp_files,
                )

                partitions_created += created
                temp_files_created += created
                repartition_passes += passes
                max_partition_records = max(
                    max_partition_records,
                    max_seen,
                )

                for group_key, state in groups.items():
                    row = self._format_group_key(
                        key,
                        group_key,
                        key_name=key_name,
                    )
                    row.update(
                        self._finalize_aggregates(
                            state,
                            aggregate_defs,
                        )
                    )
                    output.append(row)

            self.last_stats = ExternalHashStats(
                operation="group_by",
                input_records=input_records,
                partitions_created=partitions_created,
                repartition_passes=repartition_passes,
                temporary_files=temp_files_created,
                max_partition_records=max_partition_records,
                output_records=len(output),
            )

            return output

        finally:
            for path in list(all_temp_files):
                self._safe_remove(path)

    def _group_partition(
        self,
        path,
        count,
        extractor,
        aggregate_defs,
        depth,
        all_temp_files,
    ):
        """
        Retorna:
            groups, partitions_created, repartition_passes, max_seen
        """
        max_seen = count

        if count <= self.memory_limit_records or depth >= self.max_depth:
            groups = {}

            for record in self._read_partition(path):
                group_key = extractor(record)
                state = groups.setdefault(
                    group_key,
                    self._new_aggregate_state(aggregate_defs),
                )
                self._update_aggregate_state(
                    state,
                    record,
                    aggregate_defs,
                )

            self._safe_remove(path)
            all_temp_files.discard(path)
            return groups, 0, 0, max_seen

        child_paths, child_counts, _ = self._partition_iterable(
            self._read_partition(path),
            extractor,
            depth=depth + 1,
        )
        all_temp_files.update(child_paths)

        self._safe_remove(path)
        all_temp_files.discard(path)

        groups = {}
        created = len(child_paths)
        passes = 1

        if child_counts:
            max_seen = max(max_seen, max(child_counts))

        for child_path, child_count in zip(child_paths, child_counts):
            child_groups, child_created, child_passes, child_max = (
                self._group_partition(
                    path=child_path,
                    count=child_count,
                    extractor=extractor,
                    aggregate_defs=aggregate_defs,
                    depth=depth + 1,
                    all_temp_files=all_temp_files,
                )
            )

            # Una misma clave nunca debe aparecer en dos particiones
            # hermanas porque ambas se calculan con el mismo hash/depth.
            for group_key, state in child_groups.items():
                if group_key in groups:
                    raise AssertionError(
                        "same GROUP BY key appeared in different hash partitions"
                    )
                groups[group_key] = state

            created += child_created
            passes += child_passes
            max_seen = max(max_seen, child_max)

        return groups, created, passes, max_seen

    # ------------------------------------------------------------------
    # HASH JOIN
    # ------------------------------------------------------------------

    def hash_join(
        self,
        left: Iterable[Any],
        right: Iterable[Any],
        left_key: KeySpec,
        right_key: KeySpec,
        join_type: str = "inner",
        merge: Optional[Callable[[Any, Any], Any]] = None,
    ):
        """
        Grace Hash Join externo.

        `join_type`:
            - inner
            - left
            - right
            - full

        Por defecto cada fila de salida es:
            (left_row, right_row)

        Se puede proporcionar `merge(left_row, right_row)` para construir
        otro formato de salida.
        """
        join_type = join_type.lower()
        if join_type not in self.SUPPORTED_JOINS:
            raise ValueError(
                f"join_type must be one of {sorted(self.SUPPORTED_JOINS)}"
            )

        left_extractor = self._build_key_extractor(left_key)
        right_extractor = self._build_key_extractor(right_key)

        if merge is None:
            merge = lambda left_row, right_row: (left_row, right_row)

        all_temp_files = set()
        partitions_created = 0
        repartition_passes = 0
        temp_files_created = 0
        max_partition_records = 0
        output = []

        try:
            left_paths, left_counts, left_total = self._partition_iterable(
                left,
                left_extractor,
                depth=0,
            )
            right_paths, right_counts, right_total = self._partition_iterable(
                right,
                right_extractor,
                depth=0,
            )

            all_temp_files.update(left_paths)
            all_temp_files.update(right_paths)

            partitions_created += len(left_paths) + len(right_paths)
            temp_files_created += len(left_paths) + len(right_paths)

            if left_counts or right_counts:
                max_partition_records = max(
                    left_counts + right_counts
                )

            for index in range(self.partition_count):
                rows, created, passes, max_seen = self._join_partition_pair(
                    left_path=left_paths[index],
                    left_count=left_counts[index],
                    right_path=right_paths[index],
                    right_count=right_counts[index],
                    left_extractor=left_extractor,
                    right_extractor=right_extractor,
                    join_type=join_type,
                    merge=merge,
                    depth=0,
                    all_temp_files=all_temp_files,
                )

                output.extend(rows)
                partitions_created += created
                temp_files_created += created
                repartition_passes += passes
                max_partition_records = max(
                    max_partition_records,
                    max_seen,
                )

            self.last_stats = ExternalHashStats(
                operation="hash_join",
                input_records=left_total + right_total,
                left_records=left_total,
                right_records=right_total,
                partitions_created=partitions_created,
                repartition_passes=repartition_passes,
                temporary_files=temp_files_created,
                max_partition_records=max_partition_records,
                output_records=len(output),
            )

            return output

        finally:
            for path in list(all_temp_files):
                self._safe_remove(path)

    def _join_partition_pair(
        self,
        left_path,
        left_count,
        right_path,
        right_count,
        left_extractor,
        right_extractor,
        join_type,
        merge,
        depth,
        all_temp_files,
    ):
        max_seen = max(left_count, right_count)

        smaller_count = min(left_count, right_count)

        # Si una de las relaciones cabe en memoria podemos construir la
        # hash table con ese lado y hacer streaming del otro.
        if (
            smaller_count <= self.memory_limit_records
            or depth >= self.max_depth
        ):
            rows = self._join_in_memory(
                left_path,
                left_count,
                right_path,
                right_count,
                left_extractor,
                right_extractor,
                join_type,
                merge,
            )

            self._safe_remove(left_path)
            self._safe_remove(right_path)
            all_temp_files.discard(left_path)
            all_temp_files.discard(right_path)

            return rows, 0, 0, max_seen

        left_children, left_counts, _ = self._partition_iterable(
            self._read_partition(left_path),
            left_extractor,
            depth=depth + 1,
        )
        right_children, right_counts, _ = self._partition_iterable(
            self._read_partition(right_path),
            right_extractor,
            depth=depth + 1,
        )

        all_temp_files.update(left_children)
        all_temp_files.update(right_children)

        self._safe_remove(left_path)
        self._safe_remove(right_path)
        all_temp_files.discard(left_path)
        all_temp_files.discard(right_path)

        rows = []
        created = len(left_children) + len(right_children)
        passes = 1

        if left_counts or right_counts:
            max_seen = max(
                max_seen,
                max(left_counts + right_counts),
            )

        for index in range(self.partition_count):
            child_rows, child_created, child_passes, child_max = (
                self._join_partition_pair(
                    left_path=left_children[index],
                    left_count=left_counts[index],
                    right_path=right_children[index],
                    right_count=right_counts[index],
                    left_extractor=left_extractor,
                    right_extractor=right_extractor,
                    join_type=join_type,
                    merge=merge,
                    depth=depth + 1,
                    all_temp_files=all_temp_files,
                )
            )
            rows.extend(child_rows)
            created += child_created
            passes += child_passes
            max_seen = max(max_seen, child_max)

        return rows, created, passes, max_seen

    def _join_in_memory(
        self,
        left_path,
        left_count,
        right_path,
        right_count,
        left_extractor,
        right_extractor,
        join_type,
        merge,
    ):
        # Construimos la tabla hash con el lado más pequeño.
        if right_count <= left_count:
            return self._join_build_right(
                left_path,
                right_path,
                left_extractor,
                right_extractor,
                join_type,
                merge,
            )

        return self._join_build_left(
            left_path,
            right_path,
            left_extractor,
            right_extractor,
            join_type,
            merge,
        )

    def _join_build_right(
        self,
        left_path,
        right_path,
        left_extractor,
        right_extractor,
        join_type,
        merge,
    ):
        table = {}

        for right_row in self._read_partition(right_path):
            key = right_extractor(right_row)
            table.setdefault(key, []).append([right_row, False])

        output = []

        for left_row in self._read_partition(left_path):
            key = left_extractor(left_row)
            matches = table.get(key)

            if matches:
                for match in matches:
                    match[1] = True
                    output.append(merge(left_row, match[0]))
            elif join_type in {"left", "full"}:
                output.append(merge(left_row, None))

        if join_type in {"right", "full"}:
            for matches in table.values():
                for right_row, matched in matches:
                    if not matched:
                        output.append(merge(None, right_row))

        return output

    def _join_build_left(
        self,
        left_path,
        right_path,
        left_extractor,
        right_extractor,
        join_type,
        merge,
    ):
        table = {}

        for left_row in self._read_partition(left_path):
            key = left_extractor(left_row)
            table.setdefault(key, []).append([left_row, False])

        output = []

        for right_row in self._read_partition(right_path):
            key = right_extractor(right_row)
            matches = table.get(key)

            if matches:
                for match in matches:
                    match[1] = True
                    output.append(merge(match[0], right_row))
            elif join_type in {"right", "full"}:
                output.append(merge(None, right_row))

        if join_type in {"left", "full"}:
            for matches in table.values():
                for left_row, matched in matches:
                    if not matched:
                        output.append(merge(left_row, None))

        return output

    # ------------------------------------------------------------------
    # Particionado externo
    # ------------------------------------------------------------------

    def _partition_iterable(self, records, extractor, depth):
        paths = [self._new_temp_path() for _ in range(self.partition_count)]
        files = [open(path, "wb") for path in paths]
        counts = [0] * self.partition_count
        total = 0

        try:
            for record in records:
                key = extractor(record)
                partition = self._partition_index(key, depth)

                pickle.dump(
                    record,
                    files[partition],
                    protocol=pickle.HIGHEST_PROTOCOL,
                )

                counts[partition] += 1
                total += 1
        finally:
            for file in files:
                file.close()

        return paths, counts, total

    def _partition_index(self, key, depth):
        try:
            return hash((depth, key)) % self.partition_count
        except TypeError as exc:
            raise TypeError(
                "hash key must be hashable"
            ) from exc

    def _read_partition(self, path):
        with open(path, "rb") as file:
            while True:
                try:
                    yield pickle.load(file)
                except EOFError:
                    return

    # ------------------------------------------------------------------
    # Agregaciones
    # ------------------------------------------------------------------

    def _normalize_aggregates(self, aggregates):
        if aggregates is None:
            aggregates = {"count": "count"}

        normalized = {}

        for output_name, spec in aggregates.items():
            if isinstance(spec, str):
                operation = spec.lower()
                source = None
            elif (
                isinstance(spec, tuple)
                and len(spec) == 2
            ):
                operation = str(spec[0]).lower()
                source = spec[1]
            else:
                raise TypeError(
                    "aggregate must be an operation string or "
                    "(operation, source) tuple"
                )

            if operation not in self.SUPPORTED_AGGREGATES:
                raise ValueError(
                    f"unsupported aggregate: {operation}"
                )

            if operation != "count" and source is None:
                raise ValueError(
                    f"{operation} requires a source field or callable"
                )

            source_extractor = (
                None
                if source is None
                else self._build_value_extractor(source)
            )

            normalized[output_name] = (
                operation,
                source_extractor,
            )

        return normalized

    @staticmethod
    def _new_aggregate_state(aggregate_defs):
        state = {}

        for output_name, (operation, _) in aggregate_defs.items():
            if operation == "avg":
                state[output_name] = {
                    "sum": 0,
                    "count": 0,
                }
            elif operation == "count":
                state[output_name] = 0
            else:
                state[output_name] = {
                    "value": None,
                    "seen": False,
                }

        return state

    def _update_aggregate_state(
        self,
        state,
        record,
        aggregate_defs,
    ):
        for output_name, (operation, extractor) in aggregate_defs.items():
            if operation == "count":
                if extractor is None:
                    state[output_name] += 1
                else:
                    value = extractor(record)
                    if value is not None:
                        state[output_name] += 1
                continue

            value = extractor(record)

            # SQL-like aggregate semantics: NULL is ignored.
            if value is None:
                continue

            if operation == "sum":
                slot = state[output_name]
                if not slot["seen"]:
                    slot["value"] = value
                    slot["seen"] = True
                else:
                    slot["value"] += value

            elif operation == "min":
                slot = state[output_name]
                if not slot["seen"] or value < slot["value"]:
                    slot["value"] = value
                    slot["seen"] = True

            elif operation == "max":
                slot = state[output_name]
                if not slot["seen"] or value > slot["value"]:
                    slot["value"] = value
                    slot["seen"] = True

            elif operation == "avg":
                state[output_name]["sum"] += value
                state[output_name]["count"] += 1

    @staticmethod
    def _finalize_aggregates(state, aggregate_defs):
        result = {}

        for output_name, (operation, _) in aggregate_defs.items():
            value = state[output_name]

            if operation == "count":
                result[output_name] = value

            elif operation == "avg":
                if value["count"] == 0:
                    result[output_name] = None
                else:
                    result[output_name] = (
                        value["sum"] / value["count"]
                    )

            else:
                result[output_name] = (
                    value["value"]
                    if value["seen"]
                    else None
                )

        return result

    # ------------------------------------------------------------------
    # Extractores y formato
    # ------------------------------------------------------------------

    @staticmethod
    def _build_key_extractor(key: KeySpec):
        if callable(key):
            return key

        if isinstance(key, str):
            def extract_field(record):
                if not isinstance(record, dict):
                    raise TypeError(
                        "string key requires dictionary records"
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

    @staticmethod
    def _build_value_extractor(source):
        if callable(source):
            return source

        if isinstance(source, str):
            def extract(record):
                if not isinstance(record, dict):
                    raise TypeError(
                        "aggregate field requires dictionary records"
                    )
                return record[source]
            return extract

        raise TypeError(
            "aggregate source must be a field name or callable"
        )

    @staticmethod
    def _format_group_key(key_spec, value, key_name=None):
        if isinstance(key_spec, str):
            return {key_name or key_spec: value}

        if isinstance(key_spec, (tuple, list)):
            names = tuple(key_spec)
            return dict(zip(names, value))

        return {key_name or "group_key": value}

    # ------------------------------------------------------------------
    # Temporales
    # ------------------------------------------------------------------

    def _new_temp_path(self):
        file = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix="external_hash_",
            suffix=".part",
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
