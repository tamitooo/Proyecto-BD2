import random

import pytest

from indexes.bplus_tree import BPlusTree


def assert_valid(tree):
    """Atajo para validar todas las invariantes del B+ Tree."""
    assert tree.validate() is True


def test_order_must_be_at_least_three():
    with pytest.raises(ValueError, match="order must be >= 3"):
        BPlusTree(order=2)


def test_empty_tree():
    tree = BPlusTree(order=4)

    assert len(tree) == 0
    assert tree.search(10) == []
    assert tree.range_search() == []
    assert tree.delete(10) is False
    assert_valid(tree)


def test_insert_and_exact_search():
    tree = BPlusTree(order=4)

    tree.insert(10, "a")
    tree.insert(5, "b")
    tree.insert(20, "c")

    assert len(tree) == 3
    assert tree.search(5) == ["b"]
    assert tree.search(10) == ["a"]
    assert tree.search(20) == ["c"]
    assert tree.search(999) == []
    assert_valid(tree)


def test_duplicate_keys_are_kept_in_one_leaf_entry():
    tree = BPlusTree(order=4)

    tree.insert(10, "rid-1")
    tree.insert(10, "rid-2")
    tree.insert(10, "rid-3")

    assert len(tree) == 3
    assert tree.search(10) == ["rid-1", "rid-2", "rid-3"]
    assert tree.root.is_leaf is True
    assert tree.root.keys == [10]
    assert_valid(tree)


def test_leaf_split_creates_internal_root():
    tree = BPlusTree(order=4)

    for key in [10, 20, 30, 40]:
        tree.insert(key, f"v{key}")

    assert tree.root.is_leaf is False
    assert len(tree.root.children) == 2
    assert tree.root.keys == [30]

    left, right = tree.root.children
    assert left.keys == [10, 20]
    assert right.keys == [30, 40]
    assert left.next is right
    assert right.prev is left
    assert_valid(tree)


def test_multiple_splits_build_multilevel_tree():
    tree = BPlusTree(order=4)

    for key in range(1, 101):
        tree.insert(key, key * 10)

    assert tree.root.is_leaf is False
    assert len(tree) == 100

    for key in range(1, 101):
        assert tree.search(key) == [key * 10]

    assert_valid(tree)


def test_range_search():
    tree = BPlusTree(order=4)
    for key in range(1, 11):
        tree.insert(key, f"v{key}")

    assert tree.range_search(3, 7) == [
        (3, "v3"),
        (4, "v4"),
        (5, "v5"),
        (6, "v6"),
        (7, "v7"),
    ]

    assert tree.range_search(3, 7, include_start=False, include_end=False) == [
        (4, "v4"),
        (5, "v5"),
        (6, "v6"),
    ]

    assert tree.range_search(end=3) == [
        (1, "v1"),
        (2, "v2"),
        (3, "v3"),
    ]

    assert tree.range_search(start=8) == [
        (8, "v8"),
        (9, "v9"),
        (10, "v10"),
    ]
    assert_valid(tree)


def test_range_search_limit():
    tree = BPlusTree(order=4)
    for key in range(10):
        tree.insert(key, key)

    assert tree.range_search(limit=0) == []
    assert tree.range_search(2, 8, limit=3) == [(2, 2), (3, 3), (4, 4)]

    with pytest.raises(ValueError, match="limit must be >= 0"):
        tree.range_search(limit=-1)


def test_delete_single_value_from_duplicate_key():
    tree = BPlusTree(order=4)

    tree.insert(50, "a")
    tree.insert(50, "b")
    tree.insert(50, "c")

    assert tree.delete(50, "b") is True
    assert tree.search(50) == ["a", "c"]
    assert len(tree) == 2

    assert tree.delete(50, "missing") is False
    assert len(tree) == 2
    assert_valid(tree)


def test_delete_key_removes_all_duplicate_values():
    tree = BPlusTree(order=4)

    tree.insert(7, "a")
    tree.insert(7, "b")
    tree.insert(8, "c")

    assert tree.delete(7) is True
    assert tree.search(7) == []
    assert tree.search(8) == ["c"]
    assert len(tree) == 1
    assert_valid(tree)


def test_deletion_rebalances_leaf_nodes():
    tree = BPlusTree(order=4)
    for key in range(1, 13):
        tree.insert(key, key)

    for key in [1, 2, 3, 4, 5]:
        assert tree.delete(key) is True
        assert tree.search(key) == []
        assert_valid(tree)

    assert tree.range_search() == [(key, key) for key in range(6, 13)]


def test_deletion_rebalances_internal_nodes_and_collapses_root():
    tree = BPlusTree(order=4)
    for key in range(1, 80):
        tree.insert(key, key)

    # Fuerza múltiples merges tanto en hojas como en nodos internos.
    for key in range(1, 79):
        assert tree.delete(key) is True
        assert_valid(tree)

    assert tree.search(79) == [79]
    assert len(tree) == 1
    assert tree.root.is_leaf is True
    assert tree.root.keys == [79]

    assert tree.delete(79) is True
    assert len(tree) == 0
    assert tree.root.is_leaf is True
    assert tree.root.keys == []
    assert_valid(tree)


def test_leaf_chain_is_sorted_after_many_mutations():
    tree = BPlusTree(order=5)
    keys = list(range(1, 61))

    for key in keys:
        tree.insert(key, key)

    for key in range(3, 61, 3):
        tree.delete(key)

    expected = [(key, key) for key in keys if key % 3 != 0]
    assert tree.range_search() == expected
    assert_valid(tree)


@pytest.mark.parametrize("order", [3, 4, 5, 6, 8])
def test_randomized_insert_delete_stress(order):
    rng = random.Random(20260914 + order)
    tree = BPlusTree(order=order)

    keys = list(range(200))
    rng.shuffle(keys)

    for key in keys:
        tree.insert(key, ("rid", key))
        assert_valid(tree)

    for key in range(200):
        assert tree.search(key) == [("rid", key)]

    rng.shuffle(keys)
    removed = set()

    for key in keys:
        assert tree.delete(key) is True
        removed.add(key)
        assert tree.search(key) == []
        assert len(tree) == 200 - len(removed)
        assert_valid(tree)

    assert len(tree) == 0
    assert tree.range_search() == []
    assert tree.root.is_leaf is True
