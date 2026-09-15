import os

import pytest

from operators.external_sort import ExternalSort


def sample_records():
    return [
        {"id": 7, "name": "Grace", "salary": 3100, "dept": "IT"},
        {"id": 2, "name": "Bruno", "salary": 1800, "dept": "HR"},
        {"id": 9, "name": "Irene", "salary": 4200, "dept": "IT"},
        {"id": 1, "name": "Ana", "salary": 1500, "dept": "HR"},
        {"id": 5, "name": "Elena", "salary": 2500, "dept": "Sales"},
        {"id": 3, "name": "Carla", "salary": 2100, "dept": "IT"},
        {"id": 8, "name": "Hugo", "salary": 3500, "dept": "Sales"},
        {"id": 4, "name": "Diego", "salary": 2300, "dept": "HR"},
        {"id": 6, "name": "Fabio", "salary": 2800, "dept": "IT"},
    ]


def test_sort_ascending_by_field():
    sorter = ExternalSort(memory_limit_records=3, fan_in=3)

    result = sorter.sort(sample_records(), key="salary")

    assert [r["salary"] for r in result] == [
        1500, 1800, 2100, 2300, 2500, 2800, 3100, 3500, 4200
    ]


def test_sort_descending_by_field():
    sorter = ExternalSort(memory_limit_records=3, fan_in=3)

    result = sorter.sort(
        sample_records(),
        key="salary",
        descending=True,
    )

    assert [r["salary"] for r in result] == [
        4200, 3500, 3100, 2800, 2500, 2300, 2100, 1800, 1500
    ]


def test_external_sort_forces_multiple_initial_runs():
    sorter = ExternalSort(
        memory_limit_records=2,
        fan_in=8,
    )

    result = sorter.sort(sample_records(), key="id")

    assert [r["id"] for r in result] == list(range(1, 10))
    assert sorter.last_stats.input_records == 9
    assert sorter.last_stats.initial_runs == 5
    assert sorter.last_stats.merge_passes == 1
    assert sorter.last_stats.output_records == 9


def test_external_sort_forces_multiple_merge_passes():
    records = [{"id": i} for i in range(30, 0, -1)]

    sorter = ExternalSort(
        memory_limit_records=2,
        fan_in=2,
    )

    result = sorter.sort(records, key="id")

    assert [r["id"] for r in result] == list(range(1, 31))
    assert sorter.last_stats.initial_runs == 15
    assert sorter.last_stats.merge_passes >= 4
    assert sorter.last_stats.temporary_files > sorter.last_stats.initial_runs


def test_sort_empty_input():
    sorter = ExternalSort(memory_limit_records=3)

    result = sorter.sort([], key="id")

    assert result == []
    assert sorter.last_stats.input_records == 0
    assert sorter.last_stats.initial_runs == 0
    assert sorter.last_stats.output_records == 0


def test_single_run_still_sorts_correctly():
    sorter = ExternalSort(memory_limit_records=100)

    result = sorter.sort(sample_records(), key="id")

    assert [r["id"] for r in result] == list(range(1, 10))
    assert sorter.last_stats.initial_runs == 1
    assert sorter.last_stats.merge_passes == 0


def test_generator_input_is_supported():
    sorter = ExternalSort(memory_limit_records=2)

    records = ({"id": i} for i in [5, 1, 4, 2, 3])

    result = sorter.sort(records, key="id")

    assert [r["id"] for r in result] == [1, 2, 3, 4, 5]


def test_sort_iter_returns_incremental_iterator():
    sorter = ExternalSort(memory_limit_records=2)

    iterator = sorter.sort_iter(
        [{"id": 3}, {"id": 1}, {"id": 2}],
        key="id",
    )

    assert iter(iterator) is iterator
    assert list(iterator) == [{"id": 1}, {"id": 2}, {"id": 3}]


def test_multiple_fields():
    records = [
        {"id": 1, "dept": "IT", "salary": 3000},
        {"id": 2, "dept": "HR", "salary": 2200},
        {"id": 3, "dept": "IT", "salary": 1800},
        {"id": 4, "dept": "HR", "salary": 1500},
    ]

    sorter = ExternalSort(memory_limit_records=2)

    result = sorter.sort(
        records,
        key=("dept", "salary"),
    )

    assert [(r["dept"], r["salary"]) for r in result] == [
        ("HR", 1500),
        ("HR", 2200),
        ("IT", 1800),
        ("IT", 3000),
    ]


def test_callable_key_supports_storage_scan_shape():
    # Simula exactamente storage.scan(): (RID, record)
    rows = [
        (("page-2", 0), {"id": 20, "salary": 3000}),
        (("page-1", 1), {"id": 10, "salary": 1000}),
        (("page-3", 2), {"id": 30, "salary": 2000}),
    ]

    sorter = ExternalSort(memory_limit_records=1, fan_in=2)

    result = sorter.sort(
        rows,
        key=lambda item: item[1]["salary"],
    )

    assert [row[1]["salary"] for row in result] == [1000, 2000, 3000]
    assert result[0][0] == ("page-1", 1)


def test_nulls_last_ascending():
    records = [
        {"id": 1, "value": None},
        {"id": 2, "value": 20},
        {"id": 3, "value": 10},
        {"id": 4, "value": None},
    ]

    sorter = ExternalSort(memory_limit_records=2)

    result = sorter.sort(
        records,
        key="value",
        nulls_last=True,
    )

    assert [r["value"] for r in result] == [10, 20, None, None]


def test_nulls_first_ascending():
    records = [
        {"id": 1, "value": 20},
        {"id": 2, "value": None},
        {"id": 3, "value": 10},
    ]

    sorter = ExternalSort(memory_limit_records=1)

    result = sorter.sort(
        records,
        key="value",
        nulls_last=False,
    )

    assert [r["value"] for r in result] == [None, 10, 20]


def test_null_position_is_independent_from_descending():
    records = [
        {"id": 1, "value": None},
        {"id": 2, "value": 20},
        {"id": 3, "value": 10},
    ]

    sorter = ExternalSort(memory_limit_records=1)

    result = sorter.sort(
        records,
        key="value",
        descending=True,
        nulls_last=True,
    )

    assert [r["value"] for r in result] == [20, 10, None]


def test_limit_returns_only_first_ordered_rows():
    sorter = ExternalSort(memory_limit_records=2, fan_in=2)

    result = sorter.sort(
        sample_records(),
        key="salary",
        limit=3,
    )

    assert [r["salary"] for r in result] == [1500, 1800, 2100]
    assert sorter.last_stats.input_records == 9
    assert sorter.last_stats.output_records == 3


def test_limit_zero_does_not_consume_input():
    consumed = []

    def records():
        for i in range(5):
            consumed.append(i)
            yield {"id": i}

    sorter = ExternalSort(memory_limit_records=2)

    result = sorter.sort(
        records(),
        key="id",
        limit=0,
    )

    assert result == []
    assert consumed == []
    assert sorter.last_stats.input_records == 0


def test_duplicate_sort_keys_are_preserved():
    records = [
        {"id": 1, "score": 10},
        {"id": 2, "score": 5},
        {"id": 3, "score": 10},
        {"id": 4, "score": 5},
        {"id": 5, "score": 10},
    ]

    sorter = ExternalSort(memory_limit_records=2, fan_in=2)

    result = sorter.sort(records, key="score")

    assert sorted(r["id"] for r in result) == [1, 2, 3, 4, 5]
    assert [r["score"] for r in result] == [5, 5, 10, 10, 10]


def test_temp_files_are_cleaned_after_success(tmp_path):
    sorter = ExternalSort(
        memory_limit_records=2,
        fan_in=2,
        temp_dir=str(tmp_path),
    )

    result = sorter.sort(sample_records(), key="id")

    assert [r["id"] for r in result] == list(range(1, 10))
    assert list(tmp_path.iterdir()) == []


def test_invalid_configuration():
    with pytest.raises(ValueError, match="memory_limit_records"):
        ExternalSort(memory_limit_records=0)

    with pytest.raises(ValueError, match="fan_in"):
        ExternalSort(fan_in=1)


def test_invalid_limit():
    sorter = ExternalSort()

    with pytest.raises(ValueError, match="limit"):
        sorter.sort(
            [{"id": 1}],
            key="id",
            limit=-1,
        )


def test_invalid_key_specification():
    sorter = ExternalSort()

    with pytest.raises(TypeError, match="key must"):
        sorter.sort([{"id": 1}], key=123)

    with pytest.raises(ValueError, match="cannot be empty"):
        sorter.sort([{"id": 1}], key=[])

    with pytest.raises(TypeError, match="key fields"):
        sorter.sort([{"id": 1}], key=("id", 123))


def test_string_key_requires_dict_records():
    sorter = ExternalSort(memory_limit_records=2)

    with pytest.raises(TypeError, match="dictionaries"):
        sorter.sort([(1, "a"), (2, "b")], key="id")


def test_large_dataset_is_sorted_across_many_runs():
    records = [
        {"id": i, "value": (i * 37) % 997}
        for i in range(1000)
    ]

    sorter = ExternalSort(
        memory_limit_records=17,
        fan_in=4,
    )

    result = sorter.sort(records, key="value")

    values = [r["value"] for r in result]

    assert values == sorted(values)
    assert len(result) == 1000
    assert sorter.last_stats.initial_runs == 59
    assert sorter.last_stats.merge_passes >= 2
