import pytest

from indexes.unclustered_bplus import UnclusteredBPlusIndex


def rid(page, slot):
    """RID simple para probar el indice sin acoplarlo al storage."""
    return (page, slot)


def make_entries():
    return [
        ({"id": 30, "age": 24, "name": "Carla"}, rid(3, 0)),
        ({"id": 10, "age": 20, "name": "Ana"}, rid(1, 0)),
        ({"id": 50, "age": 28, "name": "Elena"}, rid(5, 0)),
        ({"id": 20, "age": 22, "name": "Bruno"}, rid(2, 0)),
        ({"id": 40, "age": 26, "name": "Diego"}, rid(4, 0)),
    ]


def test_insert_and_exact_search_returns_rid():
    index = UnclusteredBPlusIndex("id", order=4, unique=True)

    record = {"id": 10, "name": "Ana"}
    record_rid = rid(1, 3)

    index.insert(record, record_rid)

    assert index.search(10) == [record_rid]
    assert index.search(999) == []
    assert index.contains(10)
    assert not index.contains(999)
    assert index.validate()


def test_index_stores_rid_not_full_record():
    index = UnclusteredBPlusIndex("id", unique=True)

    record = {"id": 10, "name": "Ana"}
    record_rid = rid(2, 7)
    index.insert(record, record_rid)

    record["name"] = "Nombre modificado"

    # El indice depende solo de la clave y el RID.
    assert index.search(10) == [record_rid]
    assert index.scan_entries() == [(10, record_rid)]


def test_bulk_load_and_scan_follow_indexed_key_order():
    index = UnclusteredBPlusIndex("id", order=4, unique=True)
    index.bulk_load(make_entries())

    assert index.scan() == [
        rid(1, 0),
        rid(2, 0),
        rid(3, 0),
        rid(4, 0),
        rid(5, 0),
    ]

    assert [key for key, _ in index.scan_entries()] == [10, 20, 30, 40, 50]
    assert index.validate()


def test_unique_index_rejects_duplicate_key():
    index = UnclusteredBPlusIndex("id", unique=True)

    index.insert({"id": 10}, rid(1, 0))

    with pytest.raises(ValueError, match="duplicate indexed key"):
        index.insert({"id": 10}, rid(9, 9))

    assert index.search(10) == [rid(1, 0)]
    assert len(index) == 1
    assert index.validate()


def test_non_unique_index_supports_multiple_rids_per_key():
    index = UnclusteredBPlusIndex("age", unique=False)

    first_rid = rid(1, 0)
    second_rid = rid(8, 4)

    index.insert({"id": 1, "age": 20}, first_rid)
    index.insert({"id": 2, "age": 20}, second_rid)

    assert index.search(20) == [first_rid, second_rid]
    assert len(index) == 2
    assert index.validate()


def test_insert_key_low_level_api():
    index = UnclusteredBPlusIndex("id", unique=False)

    index.insert_key(42, rid(4, 2))

    assert index.search(42) == [rid(4, 2)]
    assert index.validate()


def test_range_search_returns_rids_in_key_order():
    index = UnclusteredBPlusIndex("id", order=3, unique=True)
    index.bulk_load(make_entries())

    result = index.range_search(20, 40)

    assert result == [rid(2, 0), rid(3, 0), rid(4, 0)]
    assert index.validate()


def test_range_entries_preserves_keys_and_rids():
    index = UnclusteredBPlusIndex("id", unique=True)
    index.bulk_load(make_entries())

    result = index.range_entries(20, 40)

    assert result == [
        (20, rid(2, 0)),
        (30, rid(3, 0)),
        (40, rid(4, 0)),
    ]


def test_range_search_can_exclude_boundaries_and_apply_limit():
    index = UnclusteredBPlusIndex("id", unique=True)
    index.bulk_load(make_entries())

    result = index.range_search(
        10,
        50,
        include_start=False,
        include_end=False,
        limit=2,
    )

    assert result == [rid(2, 0), rid(3, 0)]


def test_delete_entire_key():
    index = UnclusteredBPlusIndex("id", order=3, unique=True)
    index.bulk_load(make_entries())

    assert index.delete(30) is True
    assert index.search(30) == []
    assert [key for key, _ in index.scan_entries()] == [10, 20, 40, 50]
    assert len(index) == 4
    assert index.validate()


def test_delete_only_one_rid_from_duplicate_key():
    index = UnclusteredBPlusIndex("age", unique=False)

    first_rid = rid(1, 0)
    second_rid = rid(2, 0)

    index.insert({"id": 1, "age": 20}, first_rid)
    index.insert({"id": 2, "age": 20}, second_rid)

    assert index.delete(20, first_rid) is True
    assert index.search(20) == [second_rid]
    assert len(index) == 1
    assert index.validate()


def test_delete_record_extracts_key_from_record():
    index = UnclusteredBPlusIndex("age", unique=False)

    record = {"id": 1, "age": 20}
    record_rid = rid(3, 5)
    index.insert(record, record_rid)

    assert index.delete_record(record, record_rid) is True
    assert index.search(20) == []
    assert index.validate()


def test_update_moves_rid_when_indexed_key_changes():
    index = UnclusteredBPlusIndex("age", unique=False)

    old_record = {"id": 1, "age": 20}
    new_record = {"id": 1, "age": 25}
    record_rid = rid(1, 0)

    index.insert(old_record, record_rid)

    assert index.update(old_record, record_rid, new_record) is True
    assert index.search(20) == []
    assert index.search(25) == [record_rid]
    assert index.validate()


def test_update_can_replace_rid_without_changing_key():
    index = UnclusteredBPlusIndex("id", unique=True)

    old_record = {"id": 10, "name": "Ana"}
    new_record = {"id": 10, "name": "Ana Maria"}
    old_rid = rid(1, 0)
    new_rid = rid(7, 2)

    index.insert(old_record, old_rid)

    assert index.update(old_record, old_rid, new_record, new_rid) is True
    assert index.search(10) == [new_rid]
    assert len(index) == 1
    assert index.validate()


def test_unique_update_collision_keeps_original_entries():
    index = UnclusteredBPlusIndex("id", unique=True)

    first = {"id": 10}
    second = {"id": 20}
    first_rid = rid(1, 0)
    second_rid = rid(2, 0)

    index.insert(first, first_rid)
    index.insert(second, second_rid)

    with pytest.raises(ValueError, match="duplicate indexed key"):
        index.update(first, first_rid, {"id": 20})

    assert index.search(10) == [first_rid]
    assert index.search(20) == [second_rid]
    assert len(index) == 2
    assert index.validate()


def test_invalid_record_missing_key_and_missing_rid():
    index = UnclusteredBPlusIndex("id")

    with pytest.raises(TypeError):
        index.insert(("id", 10), rid(1, 0))

    with pytest.raises(KeyError):
        index.insert({"name": "Ana"}, rid(1, 0))

    with pytest.raises(ValueError, match="rid is required"):
        index.insert({"id": 10}, None)

    with pytest.raises(ValueError, match="rid is required"):
        index.insert_key(10, None)


def test_large_insertion_forces_multiple_splits_and_preserves_order():
    index = UnclusteredBPlusIndex("id", order=4, unique=True)

    for key in range(200, 0, -1):
        index.insert({"id": key}, rid(key // 10, key % 10))

    entries = index.scan_entries()

    assert [key for key, _ in entries] == list(range(1, 201))
    assert len(index) == 200
    assert index.validate()


def test_many_deletions_trigger_rebalancing_and_root_collapse():
    index = UnclusteredBPlusIndex("id", order=4, unique=True)

    for key in range(1, 101):
        index.insert({"id": key}, rid(key, 0))

    for key in range(1, 100):
        assert index.delete(key) is True
        assert index.validate()

    assert index.scan_entries() == [(100, rid(100, 0))]
    assert index.tree.root.is_leaf
    assert len(index) == 1

    assert index.delete(100) is True
    assert index.scan() == []
    assert index.tree.root.is_leaf
    assert index.validate()
