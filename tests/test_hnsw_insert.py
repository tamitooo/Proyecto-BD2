import unittest

from vector.hnsw import HNSWIndex


class TestHNSWInsertion(unittest.TestCase):
    def test_first_insert_initializes_index(self):
        index = HNSWIndex(M=4, random_seed=1)
        node = index.insert("a", [0.0, 0.0], level=2)

        self.assertEqual(len(index), 1)
        self.assertEqual(index.dimension, 2)
        self.assertEqual(index.entry_point, "a")
        self.assertEqual(index.max_level, 2)
        self.assertEqual(node.neighbors, {0: set(), 1: set(), 2: set()})
        self.assertTrue(index.validate())

    def test_insertion_creates_bidirectional_links(self):
        index = HNSWIndex(M=3, ef_construction=20, random_seed=2)
        index.insert("a", [0.0, 0.0], level=0)
        index.insert("b", [1.0, 0.0], level=0)
        index.insert("c", [2.0, 0.0], level=0)

        self.assertIn("b", index.nodes["a"].neighbors[0])
        self.assertIn("a", index.nodes["b"].neighbors[0])
        self.assertTrue(index.nodes["c"].neighbors[0])
        self.assertTrue(index.validate())

    def test_higher_level_node_becomes_entry_point(self):
        index = HNSWIndex(M=4, ef_construction=10)
        index.insert("low", [0.0, 0.0], level=0)
        index.insert("high", [0.2, 0.0], level=3)

        self.assertEqual(index.entry_point, "high")
        self.assertEqual(index.max_level, 3)
        self.assertIn("low", index.nodes["high"].neighbors[0])
        self.assertEqual(index.nodes["high"].neighbors[1], set())
        self.assertTrue(index.validate())

    def test_lower_level_insert_does_not_replace_entry_point(self):
        index = HNSWIndex(M=4, ef_construction=10)
        index.insert("top", [10.0, 0.0], level=2)
        index.insert("low", [0.0, 0.0], level=0)

        self.assertEqual(index.entry_point, "top")
        self.assertEqual(index.max_level, 2)
        self.assertTrue(index.validate())

    def test_degree_is_pruned_to_M(self):
        index = HNSWIndex(M=2, ef_construction=20, random_seed=3)
        for i in range(12):
            index.insert(i, [float(i), 0.0], level=0)

        self.assertTrue(index.validate())
        for node in index.nodes.values():
            self.assertLessEqual(len(node.neighbors[0]), 2)

    def test_duplicate_and_dimension_errors_are_rejected(self):
        index = HNSWIndex(M=4)
        index.insert("a", [0.0, 1.0], level=0)
        with self.assertRaisesRegex(ValueError, "duplicado"):
            index.insert("a", [2.0, 3.0], level=0)
        with self.assertRaisesRegex(ValueError, "dimensión"):
            index.insert("b", [1.0, 2.0, 3.0], level=0)

        self.assertEqual(len(index), 1)
        self.assertTrue(index.validate())

    def test_custom_metric_is_used_for_neighbor_selection(self):
        calls = []

        def manhattan(a, b):
            calls.append((tuple(a), tuple(b)))
            return sum(abs(x - y) for x, y in zip(a, b))

        index = HNSWIndex(M=2, ef_construction=10, metric=manhattan)
        index.insert("origin", [0.0, 0.0], level=0)
        index.insert("x", [10.0, 0.0], level=0)
        index.insert("near", [1.0, 1.0], level=0)

        self.assertTrue(calls)
        self.assertIn("origin", index.nodes["near"].neighbors[0])
        self.assertTrue(index.validate())

    def test_many_random_level_insertions_keep_invariants(self):
        index = HNSWIndex(M=4, ef_construction=16, random_seed=42)
        for i in range(100):
            index.insert(i, [float(i % 10), float(i // 10)])

        self.assertEqual(len(index), 100)
        self.assertTrue(index.validate())
        self.assertIsNotNone(index.entry_point)
        self.assertGreaterEqual(index.max_level, 0)


if __name__ == "__main__":
    unittest.main()
