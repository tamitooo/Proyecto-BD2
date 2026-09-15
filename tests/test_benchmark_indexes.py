import csv
import json
from pathlib import Path

import pytest

from benchmarks.benchmark_indexes import (
    BenchmarkConfig,
    BenchmarkResult,
    _make_dataset,
    run_benchmarks,
    write_csv,
    write_json,
)


@pytest.fixture
def tiny_config():
    return BenchmarkConfig(
        sizes=[20],
        seed=123,
        exact_queries=5,
        range_queries=3,
        mutation_operations=4,
        query_repeats=1,
        build_repeats=1,
        bplus_order=4,
        hash_bucket_capacity=4,
        range_fraction=0.20,
    )


@pytest.fixture
def tiny_results(tiny_config):
    return run_benchmarks(tiny_config)


def result_map(results):
    return {
        (row.index_type, row.metric): row
        for row in results
    }


def test_dataset_is_reproducible_with_same_seed():
    first = _make_dataset(50, seed=42)
    second = _make_dataset(50, seed=42)

    assert first == second


def test_dataset_contains_expected_unique_ids():
    records = _make_dataset(100, seed=42)

    ids = [record["id"] for record in records]

    assert len(ids) == 100
    assert sorted(ids) == list(range(100))
    assert len(set(ids)) == 100


def test_run_benchmarks_returns_all_expected_rows(tiny_results):
    # 3 índices x 8 métricas por índice.
    assert len(tiny_results) == 24

    indexes = {
        result.index_type
        for result in tiny_results
    }

    assert indexes == {
        "bplus_clustered",
        "bplus_unclustered",
        "extendible_hash",
    }


def test_all_expected_metrics_are_present(tiny_results):
    expected_metrics = {
        "build",
        "serialized_size",
        "exact_hit",
        "exact_miss",
        "range_search",
        "ordered_scan",
        "insert",
        "delete",
    }

    by_index = {}

    for result in tiny_results:
        by_index.setdefault(
            result.index_type,
            set(),
        ).add(result.metric)

    assert all(
        metrics == expected_metrics
        for metrics in by_index.values()
    )


def test_build_results_are_supported_and_have_timings(tiny_results):
    rows = [
        result
        for result in tiny_results
        if result.metric == "build"
    ]

    assert len(rows) == 3

    for row in rows:
        assert row.supported is True
        assert row.operations == 20
        assert row.total_ms is not None
        assert row.total_ms >= 0
        assert row.avg_us is not None
        assert row.avg_us >= 0


def test_exact_hit_finds_every_requested_key(tiny_results, tiny_config):
    rows = [
        result
        for result in tiny_results
        if result.metric == "exact_hit"
    ]

    assert len(rows) == 3

    expected_operations = (
        tiny_config.exact_queries
        * tiny_config.query_repeats
    )

    for row in rows:
        assert row.supported is True
        assert row.operations == expected_operations
        assert row.result_items == expected_operations


def test_exact_miss_returns_no_items(tiny_results, tiny_config):
    rows = [
        result
        for result in tiny_results
        if result.metric == "exact_miss"
    ]

    expected_operations = (
        tiny_config.exact_queries
        * tiny_config.query_repeats
    )

    for row in rows:
        assert row.supported is True
        assert row.operations == expected_operations
        assert row.result_items == 0


def test_range_search_supported_only_by_bplus(tiny_results):
    rows = result_map(tiny_results)

    assert rows[
        ("bplus_clustered", "range_search")
    ].supported is True

    assert rows[
        ("bplus_unclustered", "range_search")
    ].supported is True

    hash_row = rows[
        ("extendible_hash", "range_search")
    ]

    assert hash_row.supported is False
    assert hash_row.operations == 0
    assert hash_row.avg_us is None


def test_ordered_scan_supported_only_by_bplus(tiny_results):
    rows = result_map(tiny_results)

    assert rows[
        ("bplus_clustered", "ordered_scan")
    ].supported is True

    assert rows[
        ("bplus_unclustered", "ordered_scan")
    ].supported is True

    hash_row = rows[
        ("extendible_hash", "ordered_scan")
    ]

    assert hash_row.supported is False
    assert hash_row.operations == 0
    assert "no garantiza orden" in hash_row.notes


def test_bplus_range_queries_return_rows(tiny_results):
    rows = result_map(tiny_results)

    clustered = rows[
        ("bplus_clustered", "range_search")
    ]
    unclustered = rows[
        ("bplus_unclustered", "range_search")
    ]

    assert clustered.result_items is not None
    assert clustered.result_items > 0

    assert unclustered.result_items is not None
    assert unclustered.result_items > 0

    # Ambos B+ ejecutan exactamente los mismos rangos.
    assert clustered.result_items == unclustered.result_items


def test_ordered_scan_returns_entire_dataset(tiny_results, tiny_config):
    rows = result_map(tiny_results)

    expected = (
        tiny_config.sizes[0]
        * tiny_config.query_repeats
    )

    assert rows[
        ("bplus_clustered", "ordered_scan")
    ].result_items == expected

    assert rows[
        ("bplus_unclustered", "ordered_scan")
    ].result_items == expected


def test_insert_workload_executes_requested_operations(
    tiny_results,
    tiny_config,
):
    rows = [
        result
        for result in tiny_results
        if result.metric == "insert"
    ]

    for row in rows:
        assert row.supported is True
        assert row.operations == tiny_config.mutation_operations
        assert row.avg_us is not None
        assert row.avg_us >= 0


def test_delete_workload_executes_requested_operations(
    tiny_results,
    tiny_config,
):
    rows = [
        result
        for result in tiny_results
        if result.metric == "delete"
    ]

    for row in rows:
        assert row.supported is True
        assert row.operations == tiny_config.mutation_operations
        assert row.avg_us is not None
        assert row.avg_us >= 0


def test_serialized_size_is_positive_for_every_index(tiny_results):
    rows = [
        result
        for result in tiny_results
        if result.metric == "serialized_size"
    ]

    assert len(rows) == 3

    for row in rows:
        assert row.supported is True
        assert row.size_bytes is not None
        assert row.size_bytes > 0
        assert "aproximación" in row.notes


def test_every_result_uses_requested_dataset_size(tiny_results):
    assert {
        result.dataset_size
        for result in tiny_results
    } == {20}


def test_csv_export_contains_all_results(
    tiny_results,
    tmp_path,
):
    output = tmp_path / "results.csv"

    write_csv(tiny_results, output)

    assert output.exists()

    with output.open(
        newline="",
        encoding="utf-8",
    ) as file:
        rows = list(csv.DictReader(file))

    assert len(rows) == len(tiny_results)

    assert set(rows[0].keys()) == set(
        BenchmarkResult.__dataclass_fields__.keys()
    )

    metrics = {
        row["metric"]
        for row in rows
    }

    assert "exact_hit" in metrics
    assert "serialized_size" in metrics


def test_json_export_contains_config_and_results(
    tiny_results,
    tiny_config,
    tmp_path,
):
    output = tmp_path / "results.json"

    write_json(
        tiny_results,
        tiny_config,
        output,
    )

    assert output.exists()

    payload = json.loads(
        output.read_text(encoding="utf-8")
    )

    assert payload["config"]["sizes"] == [20]
    assert payload["config"]["seed"] == 123
    assert len(payload["results"]) == len(tiny_results)

    first = payload["results"][0]

    assert "dataset_size" in first
    assert "index_type" in first
    assert "metric" in first
    assert "supported" in first


def test_multiple_dataset_sizes_generate_independent_results():
    config = BenchmarkConfig(
        sizes=[10, 15],
        seed=7,
        exact_queries=2,
        range_queries=2,
        mutation_operations=2,
        query_repeats=1,
        build_repeats=1,
        bplus_order=4,
        hash_bucket_capacity=4,
    )

    results = run_benchmarks(config)

    # 2 tamaños x 3 índices x 8 métricas.
    assert len(results) == 48

    assert {
        result.dataset_size
        for result in results
    } == {10, 15}


def test_dataset_size_must_be_positive():
    config = BenchmarkConfig(
        sizes=[0],
        exact_queries=1,
        range_queries=1,
        mutation_operations=1,
        query_repeats=1,
        build_repeats=1,
    )

    with pytest.raises(
        ValueError,
        match="dataset sizes must be >= 1",
    ):
        run_benchmarks(config)


def test_small_dataset_caps_requested_query_counts():
    config = BenchmarkConfig(
        sizes=[3],
        seed=5,
        exact_queries=100,
        range_queries=100,
        mutation_operations=100,
        query_repeats=1,
        build_repeats=1,
        bplus_order=4,
        hash_bucket_capacity=4,
    )

    results = run_benchmarks(config)
    rows = result_map(results)

    assert rows[
        ("extendible_hash", "exact_hit")
    ].operations == 3

    assert rows[
        ("bplus_clustered", "range_search")
    ].operations == 3

    # mutation_count = min(100, max(1, 3 // 2)) = 1
    assert rows[
        ("extendible_hash", "insert")
    ].operations == 1

    assert rows[
        ("extendible_hash", "delete")
    ].operations == 1
