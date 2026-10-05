import pytest

from operators.external_hashing import ExternalHashing


def employee_rows():
    return [
        {"id": 1, "dept": "IT", "salary": 3000},
        {"id": 2, "dept": "HR", "salary": 2000},
        {"id": 3, "dept": "IT", "salary": 4000},
        {"id": 4, "dept": "HR", "salary": None},
        {"id": 5, "dept": "Sales", "salary": 2500},
        {"id": 6, "dept": "IT", "salary": 3500},
    ]


def sort_groups(rows, field):
    return sorted(rows, key=lambda row: row[field])


def test_group_by_count():
    hasher = ExternalHashing(
        memory_limit_records=2,
        partition_count=2,
    )

    result = hasher.group_by(
        employee_rows(),
        key="dept",
        aggregates={"rows": "count"},
    )

    result = sort_groups(result, "dept")

    assert result == [
        {"dept": "HR", "rows": 2},
        {"dept": "IT", "rows": 3},
        {"dept": "Sales", "rows": 1},
    ]


def test_group_by_sum_avg_min_max():
    hasher = ExternalHashing(
        memory_limit_records=2,
        partition_count=2,
    )

    result = hasher.group_by(
        employee_rows(),
        key="dept",
        aggregates={
            "rows": "count",
            "total": ("sum", "salary"),
            "average": ("avg", "salary"),
            "minimum": ("min", "salary"),
            "maximum": ("max", "salary"),
        },
    )

    by_dept = {row["dept"]: row for row in result}

    assert by_dept["IT"] == {
        "dept": "IT",
        "rows": 3,
        "total": 10500,
        "average": 3500,
        "minimum": 3000,
        "maximum": 4000,
    }

    assert by_dept["HR"] == {
        "dept": "HR",
        "rows": 2,
        "total": 2000,
        "average": 2000,
        "minimum": 2000,
        "maximum": 2000,
    }

    assert by_dept["Sales"] == {
        "dept": "Sales",
        "rows": 1,
        "total": 2500,
        "average": 2500,
        "minimum": 2500,
        "maximum": 2500,
    }


def test_group_by_count_field_ignores_null():
    hasher = ExternalHashing(
        memory_limit_records=2,
        partition_count=2,
    )

    result = hasher.group_by(
        employee_rows(),
        key="dept",
        aggregates={
            "rows": "count",
            "salary_count": ("count", "salary"),
        },
    )

    by_dept = {row["dept"]: row for row in result}

    assert by_dept["HR"]["rows"] == 2
    assert by_dept["HR"]["salary_count"] == 1


def test_group_by_multiple_columns():
    records = [
        {"country": "PE", "dept": "IT", "value": 10},
        {"country": "PE", "dept": "IT", "value": 20},
        {"country": "PE", "dept": "HR", "value": 5},
        {"country": "US", "dept": "IT", "value": 30},
    ]

    hasher = ExternalHashing(
        memory_limit_records=1,
        partition_count=2,
    )

    result = hasher.group_by(
        records,
        key=("country", "dept"),
        aggregates={
            "count": "count",
            "total": ("sum", "value"),
        },
    )

    by_key = {
        (row["country"], row["dept"]): row
        for row in result
    }

    assert by_key[("PE", "IT")]["count"] == 2
    assert by_key[("PE", "IT")]["total"] == 30
    assert by_key[("PE", "HR")]["total"] == 5
    assert by_key[("US", "IT")]["total"] == 30


def test_group_by_callable_key_supports_storage_scan_shape():
    # Simula storage.scan(): (RID, record)
    rows = [
        (("main", 0), {"dept": "IT", "salary": 1000}),
        (("main", 1), {"dept": "HR", "salary": 2000}),
        (("aux", 0), {"dept": "IT", "salary": 3000}),
    ]

    hasher = ExternalHashing(
        memory_limit_records=1,
        partition_count=2,
    )

    result = hasher.group_by(
        rows,
        key=lambda item: item[1]["dept"],
        key_name="dept",
        aggregates={
            "rows": "count",
            "total": ("sum", lambda item: item[1]["salary"]),
        },
    )

    by_dept = {row["dept"]: row for row in result}

    assert by_dept["IT"]["rows"] == 2
    assert by_dept["IT"]["total"] == 4000
    assert by_dept["HR"]["rows"] == 1


def test_group_by_forces_external_repartitioning():
    records = [
        {"group": i, "value": i * 10}
        for i in range(40)
    ]

    hasher = ExternalHashing(
        memory_limit_records=2,
        partition_count=2,
        max_depth=6,
    )

    result = hasher.group_by(
        records,
        key="group",
        aggregates={"count": "count"},
    )

    assert len(result) == 40
    assert hasher.last_stats.operation == "group_by"
    assert hasher.last_stats.input_records == 40
    assert hasher.last_stats.partitions_created >= 2
    assert hasher.last_stats.repartition_passes > 0
    assert hasher.last_stats.temporary_files >= 2
    assert hasher.last_stats.output_records == 40


def test_group_by_default_aggregate_is_count():
    hasher = ExternalHashing(
        memory_limit_records=2,
        partition_count=2,
    )

    result = hasher.group_by(
        employee_rows(),
        key="dept",
    )

    by_dept = {row["dept"]: row["count"] for row in result}

    assert by_dept == {
        "IT": 3,
        "HR": 2,
        "Sales": 1,
    }


def test_group_by_empty_input():
    hasher = ExternalHashing()

    result = hasher.group_by([], key="id")

    assert result == []
    assert hasher.last_stats.input_records == 0
    assert hasher.last_stats.output_records == 0


def test_inner_hash_join():
    employees = [
        {"id": 1, "dept_id": 10, "name": "Ana"},
        {"id": 2, "dept_id": 20, "name": "Bruno"},
        {"id": 3, "dept_id": 99, "name": "Carla"},
    ]

    departments = [
        {"id": 10, "dept": "IT"},
        {"id": 20, "dept": "HR"},
        {"id": 30, "dept": "Sales"},
    ]

    hasher = ExternalHashing(
        memory_limit_records=1,
        partition_count=2,
    )

    result = hasher.hash_join(
        employees,
        departments,
        left_key="dept_id",
        right_key="id",
        join_type="inner",
    )

    pairs = sorted(
        (left["name"], right["dept"])
        for left, right in result
    )

    assert pairs == [
        ("Ana", "IT"),
        ("Bruno", "HR"),
    ]


def test_left_hash_join():
    left = [
        {"id": 1, "fk": 10},
        {"id": 2, "fk": 99},
    ]
    right = [
        {"id": 10, "name": "match"},
    ]

    hasher = ExternalHashing(
        memory_limit_records=1,
        partition_count=2,
    )

    result = hasher.hash_join(
        left,
        right,
        left_key="fk",
        right_key="id",
        join_type="left",
    )

    assert len(result) == 2

    matched = [
        pair for pair in result
        if pair[0]["id"] == 1
    ][0]
    unmatched = [
        pair for pair in result
        if pair[0]["id"] == 2
    ][0]

    assert matched[1]["name"] == "match"
    assert unmatched[1] is None


def test_right_hash_join():
    left = [
        {"id": 1, "fk": 10},
    ]
    right = [
        {"id": 10, "name": "match"},
        {"id": 20, "name": "unmatched"},
    ]

    hasher = ExternalHashing(
        memory_limit_records=1,
        partition_count=2,
    )

    result = hasher.hash_join(
        left,
        right,
        left_key="fk",
        right_key="id",
        join_type="right",
    )

    assert len(result) == 2

    assert any(
        l is not None and r["id"] == 10
        for l, r in result
    )
    assert any(
        l is None and r["id"] == 20
        for l, r in result
    )


def test_full_hash_join():
    left = [
        {"id": 1, "fk": 10},
        {"id": 2, "fk": 99},
    ]
    right = [
        {"id": 10, "name": "match"},
        {"id": 20, "name": "right-only"},
    ]

    hasher = ExternalHashing(
        memory_limit_records=1,
        partition_count=2,
    )

    result = hasher.hash_join(
        left,
        right,
        left_key="fk",
        right_key="id",
        join_type="full",
    )

    assert len(result) == 3

    assert any(
        l is not None
        and l["id"] == 1
        and r is not None
        and r["id"] == 10
        for l, r in result
    )

    assert any(
        l is not None
        and l["id"] == 2
        and r is None
        for l, r in result
    )

    assert any(
        l is None
        and r is not None
        and r["id"] == 20
        for l, r in result
    )


def test_join_duplicate_keys_produce_cartesian_matches():
    left = [
        {"id": "L1", "key": 1},
        {"id": "L2", "key": 1},
    ]
    right = [
        {"id": "R1", "key": 1},
        {"id": "R2", "key": 1},
        {"id": "R3", "key": 1},
    ]

    hasher = ExternalHashing(
        memory_limit_records=2,
        partition_count=2,
    )

    result = hasher.hash_join(
        left,
        right,
        left_key="key",
        right_key="key",
    )

    assert len(result) == 6

    pairs = {
        (left_row["id"], right_row["id"])
        for left_row, right_row in result
    }

    assert pairs == {
        ("L1", "R1"),
        ("L1", "R2"),
        ("L1", "R3"),
        ("L2", "R1"),
        ("L2", "R2"),
        ("L2", "R3"),
    }


def test_hash_join_custom_merge():
    left = [{"fk": 10, "name": "Ana"}]
    right = [{"id": 10, "dept": "IT"}]

    hasher = ExternalHashing(
        memory_limit_records=1,
        partition_count=2,
    )

    result = hasher.hash_join(
        left,
        right,
        left_key="fk",
        right_key="id",
        merge=lambda l, r: {
            "name": l["name"],
            "dept": r["dept"],
        },
    )

    assert result == [{"name": "Ana", "dept": "IT"}]


def test_hash_join_callable_keys_support_storage_scan_shape():
    left = [
        (("main", 0), {"fk": 10, "name": "Ana"}),
        (("main", 1), {"fk": 20, "name": "Bruno"}),
    ]
    right = [
        (("main", 0), {"id": 10, "dept": "IT"}),
        (("main", 1), {"id": 20, "dept": "HR"}),
    ]

    hasher = ExternalHashing(
        memory_limit_records=1,
        partition_count=2,
    )

    result = hasher.hash_join(
        left,
        right,
        left_key=lambda item: item[1]["fk"],
        right_key=lambda item: item[1]["id"],
    )

    pairs = sorted(
        (l[1]["name"], r[1]["dept"])
        for l, r in result
    )

    assert pairs == [
        ("Ana", "IT"),
        ("Bruno", "HR"),
    ]


def test_hash_join_forces_repartitioning():
    left = [
        {"id": i, "key": i}
        for i in range(40)
    ]
    right = [
        {"id": i, "key": i}
        for i in range(40)
    ]

    hasher = ExternalHashing(
        memory_limit_records=2,
        partition_count=2,
        max_depth=6,
    )

    result = hasher.hash_join(
        left,
        right,
        left_key="key",
        right_key="key",
    )

    assert len(result) == 40
    assert hasher.last_stats.operation == "hash_join"
    assert hasher.last_stats.left_records == 40
    assert hasher.last_stats.right_records == 40
    assert hasher.last_stats.input_records == 80
    assert hasher.last_stats.repartition_passes > 0
    assert hasher.last_stats.output_records == 40


def test_hash_join_empty_relations():
    hasher = ExternalHashing(
        memory_limit_records=1,
        partition_count=2,
    )

    assert hasher.hash_join(
        [],
        [],
        left_key="id",
        right_key="id",
    ) == []


def test_temporary_files_are_cleaned_after_group_by(tmp_path):
    hasher = ExternalHashing(
        memory_limit_records=1,
        partition_count=2,
        temp_dir=str(tmp_path),
    )

    hasher.group_by(
        employee_rows(),
        key="dept",
        aggregates={"count": "count"},
    )

    assert list(tmp_path.iterdir()) == []


def test_temporary_files_are_cleaned_after_join(tmp_path):
    hasher = ExternalHashing(
        memory_limit_records=1,
        partition_count=2,
        temp_dir=str(tmp_path),
    )

    hasher.hash_join(
        [{"id": 1}],
        [{"id": 1}],
        left_key="id",
        right_key="id",
    )

    assert list(tmp_path.iterdir()) == []


def test_invalid_configuration():
    with pytest.raises(ValueError, match="memory_limit_records"):
        ExternalHashing(memory_limit_records=0)

    with pytest.raises(ValueError, match="partition_count"):
        ExternalHashing(partition_count=1)

    with pytest.raises(ValueError, match="max_depth"):
        ExternalHashing(max_depth=-1)


def test_invalid_join_type():
    hasher = ExternalHashing()

    with pytest.raises(ValueError, match="join_type"):
        hasher.hash_join(
            [],
            [],
            left_key="id",
            right_key="id",
            join_type="cross",
        )


def test_invalid_aggregate_operation():
    hasher = ExternalHashing()

    with pytest.raises(ValueError, match="unsupported aggregate"):
        hasher.group_by(
            [{"id": 1, "value": 10}],
            key="id",
            aggregates={
                "x": ("median", "value"),
            },
        )


def test_sum_requires_source():
    hasher = ExternalHashing()

    with pytest.raises(ValueError, match="requires a source"):
        hasher.group_by(
            [{"id": 1}],
            key="id",
            aggregates={"total": "sum"},
        )


def test_large_group_by_dataset():
    records = [
        {
            "group": i % 25,
            "value": i,
        }
        for i in range(1000)
    ]

    hasher = ExternalHashing(
        memory_limit_records=10,
        partition_count=4,
        max_depth=6,
    )

    result = hasher.group_by(
        records,
        key="group",
        aggregates={
            "count": "count",
            "total": ("sum", "value"),
        },
    )

    by_group = {
        row["group"]: row
        for row in result
    }

    assert len(by_group) == 25

    for group in range(25):
        expected_values = [
            i for i in range(1000)
            if i % 25 == group
        ]

        assert by_group[group]["count"] == len(expected_values)
        assert by_group[group]["total"] == sum(expected_values)


def test_large_hash_join_dataset():
    left = [
        {"id": i, "key": i % 100}
        for i in range(500)
    ]

    right = [
        {"id": i, "key": i}
        for i in range(100)
    ]

    hasher = ExternalHashing(
        memory_limit_records=10,
        partition_count=4,
        max_depth=6,
    )

    result = hasher.hash_join(
        left,
        right,
        left_key="key",
        right_key="key",
    )

    assert len(result) == 500

    assert all(
        left_row["key"] == right_row["key"]
        for left_row, right_row in result
    )
