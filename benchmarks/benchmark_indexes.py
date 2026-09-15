"""
Benchmark reproducible para comparar:

- B+ Tree clustered
- B+ Tree unclustered
- Extendible Hashing

Métricas:
- build time
- exact hit / exact miss
- range search
- ordered scan
- insertion workload
- deletion workload
- serialized index size (aproximación portable al espacio adicional)

Los resultados se exportan en CSV y JSON para alimentar las gráficas del
proyecto sin depender de librerías externas.
"""

import argparse
import csv
import json
import math
import pickle
import random
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from indexes.clustered_bplus import ClusteredBPlusIndex
from indexes.extendible_hash import ExtendibleHash
from indexes.unclustered_bplus import UnclusteredBPlusIndex


@dataclass
class BenchmarkResult:
    dataset_size: int
    index_type: str
    metric: str
    supported: bool
    operations: int
    total_ms: Optional[float] = None
    avg_us: Optional[float] = None
    median_us: Optional[float] = None
    p95_us: Optional[float] = None
    result_items: Optional[int] = None
    size_bytes: Optional[int] = None
    notes: str = ""


@dataclass
class BenchmarkConfig:
    sizes: List[int]
    seed: int = 42
    exact_queries: int = 500
    range_queries: int = 100
    mutation_operations: int = 200
    query_repeats: int = 3
    build_repeats: int = 3
    bplus_order: int = 64
    hash_bucket_capacity: int = 64
    range_fraction: float = 0.01


class _Adapter:
    def __init__(
        self,
        name: str,
        create: Callable[[], object],
        insert: Callable[[object, dict, Tuple[int, int]], None],
        search: Callable[[object, int], list],
        delete: Callable[[object, int, Tuple[int, int]], bool],
        range_search: Optional[Callable[[object, int, int], list]] = None,
        ordered_scan: Optional[Callable[[object], list]] = None,
        notes: str = "",
    ):
        self.name = name
        self.create = create
        self.insert = insert
        self.search = search
        self.delete = delete
        self.range_search = range_search
        self.ordered_scan = ordered_scan
        self.notes = notes

    @property
    def supports_range(self):
        return self.range_search is not None

    @property
    def supports_order(self):
        return self.ordered_scan is not None


def _percentile(values: Sequence[int], percentile: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    index = max(
        0,
        min(
            len(ordered) - 1,
            math.ceil(percentile * len(ordered)) - 1,
        ),
    )
    return ordered[index] / 1_000.0


def _timing_summary(
    durations_ns: Sequence[int],
    result_items: Optional[int] = None,
):
    total_ns = sum(durations_ns)

    return {
        "total_ms": total_ns / 1_000_000.0,
        "avg_us": (
            statistics.fmean(durations_ns) / 1_000.0
            if durations_ns
            else 0.0
        ),
        "median_us": (
            statistics.median(durations_ns) / 1_000.0
            if durations_ns
            else 0.0
        ),
        "p95_us": _percentile(durations_ns, 0.95),
        "result_items": result_items,
    }


def _make_dataset(size: int, seed: int) -> List[dict]:
    rng = random.Random(seed + size)

    records = [
        {
            "id": i,
            "group": i % 100,
            "value": (i * 37) % 100_003,
            "payload": f"record-{i:08d}",
        }
        for i in range(size)
    ]

    # Misma distribución y mismo orden de inserción para todos los índices.
    rng.shuffle(records)
    return records


def _rid_for(record: dict) -> Tuple[int, int]:
    # RID sintético, estable y liviano.
    return (record["id"] // 128, record["id"] % 128)


def _make_adapters(config: BenchmarkConfig) -> List[_Adapter]:
    return [
        _Adapter(
            name="bplus_clustered",
            create=lambda: ClusteredBPlusIndex(
                key_field="id",
                order=config.bplus_order,
                unique=True,
            ),
            insert=lambda index, record, rid: index.insert(record),
            search=lambda index, key: index.search(key),
            delete=lambda index, key, rid: index.delete(key),
            range_search=lambda index, low, high: index.range_search(
                low,
                high,
            ),
            ordered_scan=lambda index: index.scan(),
            notes=(
                "Las hojas almacenan registros completos; exact/range/scan "
                "incluyen materialización de registros."
            ),
        ),
        _Adapter(
            name="bplus_unclustered",
            create=lambda: UnclusteredBPlusIndex(
                key_field="id",
                order=config.bplus_order,
                unique=True,
            ),
            insert=lambda index, record, rid: index.insert(record, rid),
            search=lambda index, key: index.search(key),
            delete=lambda index, key, rid: index.delete(key, rid),
            range_search=lambda index, low, high: index.range_search(
                low,
                high,
            ),
            ordered_scan=lambda index: index.scan(),
            notes=(
                "Las hojas almacenan RIDs; no incluye el costo posterior "
                "de recuperar el registro desde storage."
            ),
        ),
        _Adapter(
            name="extendible_hash",
            create=lambda: ExtendibleHash(
                bucket_capacity=config.hash_bucket_capacity,
                unique=True,
                hash_func=int,
            ),
            insert=lambda index, record, rid: index.insert(
                record["id"],
                rid,
            ),
            search=lambda index, key: index.search(key),
            delete=lambda index, key, rid: index.delete(key, rid),
            range_search=None,
            ordered_scan=None,
            notes=(
                "Optimizado para igualdad exacta. Range search y ordered "
                "scan no son capacidades nativas del hash."
            ),
        ),
    ]


def _build_index(adapter: _Adapter, records: Sequence[dict]):
    index = adapter.create()

    for record in records:
        adapter.insert(index, record, _rid_for(record))

    return index


def _benchmark_build(
    adapter: _Adapter,
    records: Sequence[dict],
    config: BenchmarkConfig,
):
    durations = []
    last_index = None

    for _ in range(config.build_repeats):
        start = time.perf_counter_ns()
        index = _build_index(adapter, records)
        elapsed = time.perf_counter_ns() - start

        durations.append(elapsed)
        last_index = index

    # Validación fuera del timing.
    if hasattr(last_index, "validate"):
        last_index.validate()

    stats = _timing_summary(durations)

    return BenchmarkResult(
        dataset_size=len(records),
        index_type=adapter.name,
        metric="build",
        supported=True,
        operations=len(records),
        **stats,
        notes=adapter.notes,
    ), last_index


def _benchmark_serialized_size(
    adapter: _Adapter,
    index,
    dataset_size: int,
):
    payload = pickle.dumps(
        index,
        protocol=pickle.HIGHEST_PROTOCOL,
    )

    return BenchmarkResult(
        dataset_size=dataset_size,
        index_type=adapter.name,
        metric="serialized_size",
        supported=True,
        operations=1,
        size_bytes=len(payload),
        notes=(
            "Tamaño de pickle del índice; se usa como aproximación portable "
            "al espacio adicional de la estructura, no como tamaño físico "
            "de páginas en disco."
        ),
    )


def _benchmark_exact(
    adapter: _Adapter,
    index,
    keys: Sequence[int],
    metric: str,
    config: BenchmarkConfig,
):
    durations = []
    result_items = 0

    for _ in range(config.query_repeats):
        for key in keys:
            start = time.perf_counter_ns()
            result = adapter.search(index, key)
            durations.append(time.perf_counter_ns() - start)
            result_items += len(result)

    stats = _timing_summary(
        durations,
        result_items=result_items,
    )

    return BenchmarkResult(
        dataset_size=len(index),
        index_type=adapter.name,
        metric=metric,
        supported=True,
        operations=len(durations),
        **stats,
        notes=adapter.notes,
    )


def _benchmark_range(
    adapter: _Adapter,
    index,
    ranges: Sequence[Tuple[int, int]],
    dataset_size: int,
    config: BenchmarkConfig,
):
    if not adapter.supports_range:
        return BenchmarkResult(
            dataset_size=dataset_size,
            index_type=adapter.name,
            metric="range_search",
            supported=False,
            operations=0,
            notes="No soportado nativamente por Extendible Hashing.",
        )

    durations = []
    result_items = 0

    for _ in range(config.query_repeats):
        for low, high in ranges:
            start = time.perf_counter_ns()
            result = adapter.range_search(index, low, high)
            durations.append(time.perf_counter_ns() - start)
            result_items += len(result)

    stats = _timing_summary(
        durations,
        result_items=result_items,
    )

    return BenchmarkResult(
        dataset_size=dataset_size,
        index_type=adapter.name,
        metric="range_search",
        supported=True,
        operations=len(durations),
        **stats,
        notes=adapter.notes,
    )


def _benchmark_ordered_scan(
    adapter: _Adapter,
    index,
    dataset_size: int,
    config: BenchmarkConfig,
):
    if not adapter.supports_order:
        return BenchmarkResult(
            dataset_size=dataset_size,
            index_type=adapter.name,
            metric="ordered_scan",
            supported=False,
            operations=0,
            notes=(
                "Extendible Hashing no garantiza orden. Para ORDER BY "
                "se requiere External Sort."
            ),
        )

    durations = []
    result_items = 0

    for _ in range(config.query_repeats):
        start = time.perf_counter_ns()
        result = adapter.ordered_scan(index)
        durations.append(time.perf_counter_ns() - start)
        result_items += len(result)

    stats = _timing_summary(
        durations,
        result_items=result_items,
    )

    return BenchmarkResult(
        dataset_size=dataset_size,
        index_type=adapter.name,
        metric="ordered_scan",
        supported=True,
        operations=len(durations),
        **stats,
        notes=adapter.notes,
    )


def _benchmark_insert_workload(
    adapter: _Adapter,
    records: Sequence[dict],
    new_records: Sequence[dict],
):
    index = _build_index(adapter, records)

    durations = []

    for record in new_records:
        rid = _rid_for(record)
        start = time.perf_counter_ns()
        adapter.insert(index, record, rid)
        durations.append(time.perf_counter_ns() - start)

    if hasattr(index, "validate"):
        index.validate()

    stats = _timing_summary(durations)

    return BenchmarkResult(
        dataset_size=len(records),
        index_type=adapter.name,
        metric="insert",
        supported=True,
        operations=len(durations),
        **stats,
        notes=adapter.notes,
    )


def _benchmark_delete_workload(
    adapter: _Adapter,
    records: Sequence[dict],
    delete_records: Sequence[dict],
):
    index = _build_index(adapter, records)

    durations = []

    for record in delete_records:
        rid = _rid_for(record)
        start = time.perf_counter_ns()
        deleted = adapter.delete(
            index,
            record["id"],
            rid,
        )
        durations.append(time.perf_counter_ns() - start)

        if not deleted:
            raise AssertionError(
                f"{adapter.name} failed to delete existing key "
                f"{record['id']}"
            )

    if hasattr(index, "validate"):
        index.validate()

    stats = _timing_summary(durations)

    return BenchmarkResult(
        dataset_size=len(records),
        index_type=adapter.name,
        metric="delete",
        supported=True,
        operations=len(durations),
        **stats,
        notes=adapter.notes,
    )


def run_benchmarks(config: BenchmarkConfig) -> List[BenchmarkResult]:
    rng = random.Random(config.seed)
    results = []

    for size in config.sizes:
        if size < 1:
            raise ValueError("dataset sizes must be >= 1")

        records = _make_dataset(size, config.seed)
        adapters = _make_adapters(config)

        query_count = min(config.exact_queries, size)
        range_count = min(config.range_queries, size)
        mutation_count = min(
            config.mutation_operations,
            max(1, size // 2),
        )

        existing_keys = rng.sample(
            range(size),
            query_count,
        )

        # Claves que deliberadamente no existen.
        missing_keys = [
            size + 1_000_000 + i
            for i in range(query_count)
        ]

        width = max(
            1,
            int(size * config.range_fraction),
        )

        range_starts = rng.sample(
            range(size),
            range_count,
        )

        ranges = [
            (
                start,
                min(size - 1, start + width),
            )
            for start in range_starts
        ]

        new_records = [
            {
                "id": size + i,
                "group": (size + i) % 100,
                "value": ((size + i) * 37) % 100_003,
                "payload": f"record-{size + i:08d}",
            }
            for i in range(mutation_count)
        ]

        delete_ids = set(
            rng.sample(range(size), mutation_count)
        )
        delete_records = [
            record
            for record in records
            if record["id"] in delete_ids
        ]

        for adapter in adapters:
            build_result, built_index = _benchmark_build(
                adapter,
                records,
                config,
            )
            results.append(build_result)

            results.append(
                _benchmark_serialized_size(
                    adapter,
                    built_index,
                    size,
                )
            )

            results.append(
                _benchmark_exact(
                    adapter,
                    built_index,
                    existing_keys,
                    "exact_hit",
                    config,
                )
            )

            results.append(
                _benchmark_exact(
                    adapter,
                    built_index,
                    missing_keys,
                    "exact_miss",
                    config,
                )
            )

            results.append(
                _benchmark_range(
                    adapter,
                    built_index,
                    ranges,
                    size,
                    config,
                )
            )

            results.append(
                _benchmark_ordered_scan(
                    adapter,
                    built_index,
                    size,
                    config,
                )
            )

            results.append(
                _benchmark_insert_workload(
                    adapter,
                    records,
                    new_records,
                )
            )

            results.append(
                _benchmark_delete_workload(
                    adapter,
                    records,
                    delete_records,
                )
            )

    return results


def write_csv(results: Sequence[BenchmarkResult], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(
        BenchmarkResult.__dataclass_fields__.keys()
    )

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )
        writer.writeheader()

        for result in results:
            writer.writerow(asdict(result))


def write_json(
    results: Sequence[BenchmarkResult],
    config: BenchmarkConfig,
    path: Path,
):
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "config": asdict(config),
        "results": [
            asdict(result)
            for result in results
        ],
    }

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            payload,
            file,
            indent=2,
            ensure_ascii=False,
        )


def _print_summary(results: Sequence[BenchmarkResult]):
    print()
    print("=== Benchmark B+ / Extendible Hash ===")

    for result in results:
        if not result.supported:
            value = "N/A"
        elif result.metric == "serialized_size":
            value = f"{result.size_bytes:,} bytes"
        elif result.avg_us is not None:
            value = f"{result.avg_us:,.3f} us/op"
        else:
            value = "-"

        print(
            f"N={result.dataset_size:<8} "
            f"{result.index_type:<20} "
            f"{result.metric:<18} "
            f"{value}"
        )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Benchmark B+ clustered/unclustered vs Extendible Hash"
    )

    parser.add_argument(
        "--sizes",
        nargs="+",
        type=int,
        default=[1_000, 10_000, 50_000],
        help="Tamaños de dataset",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
    )
    parser.add_argument(
        "--exact-queries",
        type=int,
        default=500,
    )
    parser.add_argument(
        "--range-queries",
        type=int,
        default=100,
    )
    parser.add_argument(
        "--mutation-operations",
        type=int,
        default=200,
    )
    parser.add_argument(
        "--query-repeats",
        type=int,
        default=3,
    )
    parser.add_argument(
        "--build-repeats",
        type=int,
        default=3,
    )
    parser.add_argument(
        "--bplus-order",
        type=int,
        default=64,
    )
    parser.add_argument(
        "--hash-bucket-capacity",
        type=int,
        default=64,
    )
    parser.add_argument(
        "--output-dir",
        default="benchmark_results",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    config = BenchmarkConfig(
        sizes=args.sizes,
        seed=args.seed,
        exact_queries=args.exact_queries,
        range_queries=args.range_queries,
        mutation_operations=args.mutation_operations,
        query_repeats=args.query_repeats,
        build_repeats=args.build_repeats,
        bplus_order=args.bplus_order,
        hash_bucket_capacity=args.hash_bucket_capacity,
    )

    results = run_benchmarks(config)

    output_dir = Path(args.output_dir)

    csv_path = output_dir / "index_benchmark.csv"
    json_path = output_dir / "index_benchmark.json"

    write_csv(results, csv_path)
    write_json(results, config, json_path)
    _print_summary(results)

    print()
    print(f"CSV : {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()
