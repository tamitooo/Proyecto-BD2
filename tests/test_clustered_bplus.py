import pytest

from indexes.clustered_bplus import ClusteredBPlusIndex


def rid(record):
    return ("page", record["id"])


def make_records():
    return [
        {"id": 30, "name": "Carla", "age": 24},
        {"id": 10, "name": "Ana", "age": 20},
        {"id": 50, "name": "Elena", "age": 28},
        {"id": 20, "name": "Bruno", "age": 22},
        {"id": 40, "name": "Diego", "age": 26},
    ]


def loaded(order=4, unique=True):
    index = ClusteredBPlusIndex("id", order=order, unique=unique)
    index.bulk_load((record, rid(record)) for record in make_records())
    return index


def ids(rids):
    return [r[1] for r in rids]


def test_insert_and_search_record():
    index = ClusteredBPlusIndex("id", order=4, unique=True)

    record = {"id": 10, "name": "Ana"}
    index.insert(record, rid(record))

    assert index.search(10) == [rid(record)]
    assert index.search(999) == []
    assert index.contains(10)
    assert not index.contains(999)
    assert index.validate()


def test_insert_requires_rid():
    index = ClusteredBPlusIndex("id")

    with pytest.raises(ValueError, match="rid"):
        index.insert({"id": 1}, None)


def test_records_are_scanned_in_clustered_key_order():
    index = loaded()

    assert ids(index.scan()) == [10, 20, 30, 40, 50]
    assert index.validate()


def test_unique_clustered_index_rejects_duplicate_key():
    index = ClusteredBPlusIndex("id", unique=True)

    index.insert({"id": 10, "name": "Ana"}, ("page", 1))

    with pytest.raises(ValueError, match="duplicate clustered key"):
        index.insert({"id": 10, "name": "Otra persona"}, ("page", 2))

    assert len(index) == 1
    assert index.validate()


def test_non_unique_clustered_index_supports_duplicate_keys():
    index = ClusteredBPlusIndex("age", unique=False)

    index.insert({"id": 1, "age": 20}, ("page", 1))
    index.insert({"id": 2, "age": 20}, ("page", 2))

    assert index.search(20) == [("page", 1), ("page", 2)]
    assert len(index) == 2
    assert index.validate()


def test_range_search_is_ordered_and_inclusive_by_default():
    index = loaded(order=3)

    assert ids(index.range_search(20, 40)) == [20, 30, 40]
    assert index.validate()


def test_range_search_can_exclude_boundaries():
    index = loaded()

    result = index.range_search(10, 50, include_start=False, include_end=False)

    assert ids(result) == [20, 30, 40]


def test_range_search_limit():
    assert ids(loaded().range_search(10, 50, limit=3)) == [10, 20, 30]


def test_range_entries_returns_keys_and_rids():
    entries = loaded().range_entries(start=20, end=30)

    assert entries == [(20, ("page", 20)), (30, ("page", 30))]


def test_delete_entire_key():
    index = loaded(order=3)

    assert index.delete(30) is True
    assert index.search(30) == []
    assert ids(index.scan()) == [10, 20, 40, 50]
    assert len(index) == 4
    assert index.validate()


def test_delete_only_one_rid_from_duplicate_key():
    index = ClusteredBPlusIndex("age", unique=False)

    index.insert({"id": 1, "age": 20}, ("page", 1))
    index.insert({"id": 2, "age": 20}, ("page", 2))

    assert index.delete(20, ("page", 1)) is True
    assert index.search(20) == [("page", 2)]
    assert len(index) == 1
    assert index.validate()


def test_delete_record_uses_its_key():
    index = loaded()
    record = make_records()[0]

    assert index.delete_record(record, rid(record)) is True
    assert not index.contains(record["id"])


def test_invalid_record_types_and_missing_key():
    index = ClusteredBPlusIndex("id")

    with pytest.raises(TypeError):
        index.insert(("id", 10), ("page", 1))

    with pytest.raises(KeyError):
        index.insert({"name": "Ana"}, ("page", 1))


def test_persisted_index_is_reloaded(tmp_path):
    path = tmp_path / "id.bpc"
    index = ClusteredBPlusIndex("id", unique=True, file_path=path)
    index.bulk_load((record, rid(record)) for record in make_records())

    reloaded = ClusteredBPlusIndex("id", unique=True, file_path=path)

    assert ids(reloaded.scan()) == [10, 20, 30, 40, 50]
    assert reloaded.serialized_size_bytes() > 0


def test_large_insertion_forces_multiple_splits_and_preserves_order():
    index = ClusteredBPlusIndex("id", order=4, unique=True)

    for key in range(200, 0, -1):
        index.insert({"id": key}, ("page", key))

    assert ids(index.scan()) == list(range(1, 201))
    assert len(index) == 200
    assert index.validate()


def test_many_deletions_trigger_rebalancing_and_root_collapse():
    index = ClusteredBPlusIndex("id", order=4, unique=True)

    for key in range(1, 101):
        index.insert({"id": key}, ("page", key))

    for key in range(1, 100):
        assert index.delete(key) is True
        assert index.validate()

    assert index.scan() == [("page", 100)]
    assert index.tree.root.is_leaf
    assert len(index) == 1

    assert index.delete(100) is True
    assert index.scan() == []
    assert index.tree.root.is_leaf
    assert index.validate()
