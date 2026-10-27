import unittest

from vector.hnsw import HNSWIndex, HNSWNode


class TestHNSWStructure(unittest.TestCase):
    def test_defaults_and_empty_invariants(self):
        index = HNSWIndex(random_seed=7)
        self.assertEqual(index.M, 16)
        self.assertEqual(index.ef_construction, 100)
        self.assertEqual(index.ef_search, 50)
        self.assertIsNone(index.entry_point)
        self.assertEqual(index.max_level, -1)
        self.assertTrue(index.validate())

    def test_invalid_configuration(self):
        with self.assertRaises(ValueError):
            HNSWIndex(M=1)
        with self.assertRaises(ValueError):
            HNSWIndex(ef_construction=0)
        with self.assertRaises(ValueError):
            HNSWIndex(ef_search=0)
        with self.assertRaises(ValueError):
            HNSWIndex(level_multiplier=0)

    def test_node_has_every_level(self):
        node = HNSWNode("a", (1.0, 2.0), level=3)
        self.assertEqual(set(node.neighbors), {0, 1, 2, 3})
        self.assertTrue(all(not values for values in node.neighbors.values()))
        with self.assertRaises(ValueError):
            node.neighbors_at(4)

    def test_random_levels_are_reproducible(self):
        a = HNSWIndex(M=8, random_seed=123)
        b = HNSWIndex(M=8, random_seed=123)
        levels_a = [a.random_level() for _ in range(200)]
        levels_b = [b.random_level() for _ in range(200)]
        self.assertEqual(levels_a, levels_b)
        self.assertTrue(all(level >= 0 for level in levels_a))
        # La distribución debe producir mayormente nivel 0, pero también
        # niveles superiores en una muestra razonable con esta semilla.
        self.assertGreater(levels_a.count(0), 100)
        self.assertTrue(any(level > 0 for level in levels_a))

    def test_structural_registration_sets_dimension_entry_and_max_level(self):
        index = HNSWIndex(M=4, random_seed=1)
        n1 = index.make_node("a", [0, 0, 0], level=0)
        n2 = index.make_node("b", [1, 1, 1], level=2)
        n3 = index.make_node("c", [2, 2, 2], level=1)
        index._register_structural_node(n1)
        index._register_structural_node(n2)
        index._register_structural_node(n3)

        self.assertEqual(index.dimension, 3)
        self.assertEqual(index.entry_point, "b")
        self.assertEqual(index.max_level, 2)
        self.assertEqual(len(index), 3)
        self.assertTrue(index.validate())

    def test_dimension_and_duplicate_id_are_rejected(self):
        index = HNSWIndex(M=4)
        index._register_structural_node(index.make_node(1, [0.0, 1.0], level=0))
        with self.assertRaisesRegex(ValueError, "dimensión"):
            index.make_node(2, [0.0, 1.0, 2.0], level=0)
        with self.assertRaisesRegex(ValueError, "duplicado"):
            index._register_structural_node(HNSWNode(1, (2.0, 3.0), level=0))

    def test_validate_accepts_reciprocal_multilevel_graph(self):
        index = HNSWIndex(M=3)
        a = HNSWNode("a", (0.0, 0.0), level=2)
        b = HNSWNode("b", (1.0, 0.0), level=1)
        c = HNSWNode("c", (2.0, 0.0), level=0)
        for node in (a, b, c):
            index._register_structural_node(node)

        a.neighbors[0].add("b")
        b.neighbors[0].update({"a", "c"})
        c.neighbors[0].add("b")
        a.neighbors[1].add("b")
        b.neighbors[1].add("a")

        self.assertTrue(index.validate())
        self.assertEqual(index.stats()["level_counts"], {0: 3, 1: 2, 2: 1})

    def test_validate_detects_non_reciprocal_link(self):
        index = HNSWIndex(M=4)
        a = HNSWNode("a", (0.0, 0.0), level=0)
        b = HNSWNode("b", (1.0, 0.0), level=0)
        index._register_structural_node(a)
        index._register_structural_node(b)
        a.neighbors[0].add("b")
        with self.assertRaisesRegex(AssertionError, "no recíproco"):
            index.validate()

    def test_validate_detects_degree_over_M(self):
        index = HNSWIndex(M=2)
        nodes = [HNSWNode(str(i), (float(i),), level=0) for i in range(4)]
        for node in nodes:
            index._register_structural_node(node)
        # nodo 0 conectado recíprocamente a 1,2,3 -> grado 3 > M=2
        for other in nodes[1:]:
            nodes[0].neighbors[0].add(other.vector_id)
            other.neighbors[0].add(nodes[0].vector_id)
        with self.assertRaisesRegex(AssertionError, "excede"):
            index.validate()


if __name__ == "__main__":
    unittest.main()
