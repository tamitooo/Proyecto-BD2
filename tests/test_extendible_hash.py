import pytest

from indexes.extendible_hash import ExtendibleHash


def deterministic_hash(value):
    return int(value)


def test_insert_and_exact_search():
    index = ExtendibleHash(
        bucket_capacity=2,
        hash_func=deterministic_hash,
    )

    index.insert(10, "rid-10")
    index.insert(20, "rid-20")

    assert index.search(10) == ["rid-10"]
    assert index.search(20) == ["rid-20"]
    assert index.search(999) == []
    assert index.contains(10)
    assert not index.contains(999)
    assert index.validate()


def test_non_unique_key_supports_multiple_values_without_split():
    index = ExtendibleHash(
        bucket_capacity=1,
        unique=False,
        hash_func=deterministic_hash,
    )

    index.insert(10, "rid-a")
    initial_depth = index.global_depth

    index.insert(10, "rid-b")
    index.insert(10, "rid-c")

    assert index.search(10) == ["rid-a", "rid-b", "rid-c"]
    assert len(index) == 3
    assert index.global_depth == initial_depth
    assert index.validate()


def test_unique_index_rejects_duplicate_key():
    index = ExtendibleHash(
        bucket_capacity=2,
        unique=True,
        hash_func=deterministic_hash,
    )

    index.insert(10, "rid-a")

    with pytest.raises(ValueError, match="duplicate hash key"):
        index.insert(10, "rid-b")

    assert index.search(10) == ["rid-a"]
    assert len(index) == 1
    assert index.validate()


def test_bucket_split_occurs_when_capacity_is_exceeded():
    index = ExtendibleHash(
        bucket_capacity=1,
        hash_func=deterministic_hash,
    )

    index.insert(0, "a")
    index.insert(2, "b")

    assert index.search(0) == ["a"]
    assert index.search(2) == ["b"]
    assert index.global_depth >= 2
    assert index.bucket_count() >= 3
    assert index.validate()


def test_directory_doubles_when_local_depth_equals_global_depth():
    index = ExtendibleHash(
        bucket_capacity=1,
        hash_func=deterministic_hash,
    )

    assert index.global_depth == 1
    assert len(index.directory) == 2

    index.insert(0, "a")
    index.insert(2, "b")

    assert index.global_depth == 2
    assert len(index.directory) == 4
    assert index.validate()


def test_multiple_splits_preserve_all_entries():
    index = ExtendibleHash(
        bucket_capacity=2,
        hash_func=deterministic_hash,
    )

    for key in range(40):
        index.insert(key, f"rid-{key}")

    for key in range(40):
        assert index.search(key) == [f"rid-{key}"]

    assert len(index) == 40
    assert index.validate()


def test_bulk_load():
    index = ExtendibleHash(
        bucket_capacity=2,
        hash_func=deterministic_hash,
    )

    entries = [(i, f"rid-{i}") for i in range(12)]
    index.bulk_load(entries)

    assert sorted(index.items()) == entries
    assert len(index) == 12
    assert index.validate()


def test_delete_entire_key():
    index = ExtendibleHash(
        bucket_capacity=2,
        hash_func=deterministic_hash,
    )

    index.insert(10, "a")
    index.insert(10, "b")
    index.insert(20, "c")

    assert index.delete(10) is True
    assert index.search(10) == []
    assert index.search(20) == ["c"]
    assert len(index) == 1
    assert index.validate()


def test_delete_only_one_value_from_duplicate_key():
    index = ExtendibleHash(
        bucket_capacity=2,
        hash_func=deterministic_hash,
    )

    index.insert(10, "a")
    index.insert(10, "b")

    assert index.delete(10, "a") is True
    assert index.search(10) == ["b"]
    assert len(index) == 1
    assert index.validate()


def test_delete_missing_key_returns_false():
    index = ExtendibleHash(hash_func=deterministic_hash)

    assert index.delete(999) is False
    assert index.validate()


def test_delete_missing_value_returns_false():
    index = ExtendibleHash(hash_func=deterministic_hash)

    index.insert(10, "a")

    assert index.delete(10, "not-there") is False
    assert index.search(10) == ["a"]
    assert len(index) == 1
    assert index.validate()


def test_merge_compatible_buddy_buckets_after_delete():
    index = ExtendibleHash(
        bucket_capacity=1,
        hash_func=deterministic_hash,
    )

    index.insert(0, "a")
    index.insert(2, "b")

    before = index.bucket_count()

    assert index.delete(2) is True

    assert index.search(0) == ["a"]
    assert index.bucket_count() < before
    assert index.validate()


def test_directory_shrinks_after_merges():
    index = ExtendibleHash(
        bucket_capacity=1,
        hash_func=deterministic_hash,
    )

    index.insert(0, "a")
    index.insert(2, "b")

    assert index.global_depth == 2

    index.delete(2)

    assert index.global_depth == 1
    assert len(index.directory) == 2
    assert index.validate()


def test_items_contains_every_key_value_pair():
    index = ExtendibleHash(
        bucket_capacity=2,
        hash_func=deterministic_hash,
    )

    expected = [
        (1, "a"),
        (1, "b"),
        (2, "c"),
        (7, "d"),
    ]

    for key, value in expected:
        index.insert(key, value)

    assert sorted(index.items()) == sorted(expected)
    assert index.validate()


def test_keys_returns_distinct_keys():
    index = ExtendibleHash(hash_func=deterministic_hash)

    index.insert(1, "a")
    index.insert(1, "b")
    index.insert(2, "c")
    index.insert(3, "d")

    assert sorted(index.keys()) == [1, 2, 3]
    assert index.validate()


def test_stats_are_consistent():
    index = ExtendibleHash(
        bucket_capacity=2,
        hash_func=deterministic_hash,
    )

    index.insert(1, "a")
    index.insert(2, "b")
    index.insert(2, "c")

    stats = index.stats()

    assert stats["directory_size"] == 2 ** stats["global_depth"]
    assert stats["bucket_capacity"] == 2
    assert stats["distinct_keys"] == 2
    assert stats["entries"] == 3
    assert stats["bucket_count"] == index.bucket_count()
    assert 0.0 <= stats["load_factor"] <= 1.0
    assert index.validate()


def test_invalid_configuration():
    with pytest.raises(ValueError, match="bucket_capacity"):
        ExtendibleHash(bucket_capacity=0)

    with pytest.raises(ValueError, match="max_depth"):
        ExtendibleHash(max_depth=0)


def test_max_depth_protects_against_unseparable_hash_collisions():
    index = ExtendibleHash(
        bucket_capacity=1,
        hash_func=lambda _: 0,
        max_depth=4,
    )

    index.insert("a", "rid-a")

    with pytest.raises(OverflowError):
        index.insert("b", "rid-b")

    assert index.search("a") == ["rid-a"]
    assert index.search("b") == []
    assert len(index) == 1
    assert index.validate()


def test_large_insert_delete_cycle_keeps_structure_valid():
    index = ExtendibleHash(
        bucket_capacity=4,
        hash_func=deterministic_hash,
    )

    for key in range(200):
        index.insert(key, f"rid-{key}")

    assert len(index) == 200
    assert index.validate()

    for key in range(0, 200, 2):
        assert index.delete(key) is True
        assert index.validate()

    for key in range(200):
        if key % 2 == 0:
            assert index.search(key) == []
        else:
            assert index.search(key) == [f"rid-{key}"]

    assert len(index) == 100
    assert index.validate()
