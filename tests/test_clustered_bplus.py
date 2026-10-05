import pytest

from indexes.clustered_bplus import ClusteredBPlusIndex


def make_records():
    return [
        {"id": 30, "name": "Carla", "age": 24},
        {"id": 10, "name": "Ana", "age": 20},
        {"id": 50, "name": "Elena", "age": 28},
        {"id": 20, "name": "Bruno", "age": 22},
        {"id": 40, "name": "Diego", "age": 26},
    ]


def test_insert_and_search_record():
    index = ClusteredBPlusIndex("id", order=4, unique=True)

    record = {"id": 10, "name": "Ana"}
    index.insert(record)

    assert index.search(10) == [record]
    assert index.search(999) == []
    assert index.contains(10)
    assert not index.contains(999)
    assert index.validate()


def test_records_are_scanned_in_clustered_key_order():
    index = ClusteredBPlusIndex("id", order=4, unique=True)
    index.bulk_load(make_records())

    result = index.scan()

    assert [record["id"] for record in result] == [10, 20, 30, 40, 50]
    assert index.validate()


def test_unique_clustered_index_rejects_duplicate_key():
    index = ClusteredBPlusIndex("id", unique=True)

    index.insert({"id": 10, "name": "Ana"})

    with pytest.raises(ValueError, match="duplicate clustered key"):
        index.insert({"id": 10, "name": "Otra persona"})

    assert len(index) == 1
    assert index.validate()


def test_non_unique_clustered_index_supports_duplicate_keys():
    index = ClusteredBPlusIndex("age", unique=False)

    first = {"id": 1, "age": 20, "name": "Ana"}
    second = {"id": 2, "age": 20, "name": "Bruno"}

    index.insert(first)
    index.insert(second)

    assert index.search(20) == [first, second]
    assert len(index) == 2
    assert index.validate()


def test_range_search_is_ordered_and_inclusive_by_default():
    index = ClusteredBPlusIndex("id", order=3, unique=True)
    index.bulk_load(make_records())

    result = index.range_search(20, 40)

    assert [record["id"] for record in result] == [20, 30, 40]
    assert index.validate()


def test_range_search_can_exclude_boundaries():
    index = ClusteredBPlusIndex("id", unique=True)
    index.bulk_load(make_records())

    result = index.range_search(
        10,
        50,
        include_start=False,
        include_end=False,
    )

    assert [record["id"] for record in result] == [20, 30, 40]


def test_range_search_limit():
    index = ClusteredBPlusIndex("id", unique=True)
    index.bulk_load(make_records())

    result = index.range_search(10, 50, limit=3)

    assert [record["id"] for record in result] == [10, 20, 30]


def test_delete_entire_key():
    index = ClusteredBPlusIndex("id", order=3, unique=True)
    index.bulk_load(make_records())

    assert index.delete(30) is True
    assert index.search(30) == []
    assert [r["id"] for r in index.scan()] == [10, 20, 40, 50]
    assert len(index) == 4
    assert index.validate()


def test_delete_only_one_record_from_duplicate_key():
    index = ClusteredBPlusIndex("age", unique=False)

    first = {"id": 1, "age": 20, "name": "Ana"}
    second = {"id": 2, "age": 20, "name": "Bruno"}

    index.insert(first)
    index.insert(second)

    assert index.delete(20, first) is True
    assert index.search(20) == [second]
    assert len(index) == 1
    assert index.validate()


def test_update_record_without_changing_clustered_key():
    index = ClusteredBPlusIndex("id", unique=True)

    old_record = {"id": 10, "name": "Ana"}
    new_record = {"id": 10, "name": "Ana Maria"}

    index.insert(old_record)

    assert index.update(10, old_record, new_record) is True
    assert index.search(10) == [new_record]
    assert len(index) == 1
    assert index.validate()


def test_update_record_moves_it_when_clustered_key_changes():
    index = ClusteredBPlusIndex("id", order=3, unique=True)

    old_record = {"id": 30, "name": "Carla"}
    index.bulk_load([
        {"id": 10, "name": "Ana"},
        old_record,
        {"id": 50, "name": "Elena"},
    ])

    new_record = {"id": 20, "name": "Carla"}

    assert index.update(30, old_record, new_record) is True
    assert index.search(30) == []
    assert index.search(20) == [new_record]
    assert [r["id"] for r in index.scan()] == [10, 20, 50]
    assert index.validate()


def test_update_unique_collision_does_not_remove_original():
    index = ClusteredBPlusIndex("id", unique=True)

    first = {"id": 10, "name": "Ana"}
    second = {"id": 20, "name": "Bruno"}

    index.insert(first)
    index.insert(second)

    with pytest.raises(ValueError, match="duplicate clustered key"):
        index.update(
            10,
            first,
            {"id": 20, "name": "Ana"},
        )

    assert index.search(10) == [first]
    assert index.search(20) == [second]
    assert len(index) == 2
    assert index.validate()


def test_insert_uses_copy_of_record():
    index = ClusteredBPlusIndex("id", unique=True)

    record = {"id": 10, "name": "Ana"}
    index.insert(record)

    record["name"] = "Modificado afuera"

    assert index.search(10) == [{"id": 10, "name": "Ana"}]


def test_search_returns_copy_and_does_not_expose_internal_record():
    index = ClusteredBPlusIndex("id", unique=True)
    index.insert({"id": 10, "name": "Ana"})

    result = index.search(10)
    result[0]["name"] = "Modificado"

    assert index.search(10) == [{"id": 10, "name": "Ana"}]


def test_invalid_record_types_and_missing_key():
    index = ClusteredBPlusIndex("id")

    with pytest.raises(TypeError):
        index.insert(("id", 10))

    with pytest.raises(KeyError):
        index.insert({"name": "Ana"})


def test_large_insertion_forces_multiple_splits_and_preserves_order():
    index = ClusteredBPlusIndex("id", order=4, unique=True)

    for key in range(200, 0, -1):
        index.insert({"id": key, "value": f"row-{key}"})

    result = index.scan()

    assert [record["id"] for record in result] == list(range(1, 201))
    assert len(index) == 200
    assert index.validate()


def test_many_deletions_trigger_rebalancing_and_root_collapse():
    index = ClusteredBPlusIndex("id", order=4, unique=True)

    for key in range(1, 101):
        index.insert({"id": key})

    for key in range(1, 100):
        assert index.delete(key) is True
        assert index.validate()

    assert index.scan() == [{"id": 100}]
    assert index.tree.root.is_leaf
    assert len(index) == 1

    assert index.delete(100) is True
    assert index.scan() == []
    assert index.tree.root.is_leaf
    assert index.validate()
