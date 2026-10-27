import random
import unittest

from vector.hnsw import HNSWIndex


class TestHNSWKNN(unittest.TestCase):
    def test_empty_index_returns_empty(self):
        index = HNSWIndex(M=4)
        self.assertEqual(index.knn([0.0, 0.0], k=5), [])

    def test_exact_point_is_first(self):
        index = HNSWIndex(M=4, ef_construction=30, ef_search=20, random_seed=1)
        for i in range(20):
            index.insert(i, [float(i), 0.0], level=0)

        result = index.knn([7.0, 0.0], k=5)
        self.assertEqual(result[0][0], 7)
        self.assertAlmostEqual(result[0][1], 0.0)
        self.assertEqual([d for _, d in result], sorted(d for _, d in result))

    def test_known_neighbors_are_ranked_by_distance(self):
        index = HNSWIndex(M=6, ef_construction=50, ef_search=20)
        points = {
            "origin": [0.0, 0.0],
            "a": [1.0, 0.0],
            "b": [2.0, 0.0],
            "c": [4.0, 0.0],
        }
        for node_id, vector in points.items():
            index.insert(node_id, vector, level=0)

        ids = [node_id for node_id, _ in index.knn([0.1, 0.0], k=3)]
        self.assertEqual(ids, ["origin", "a", "b"])

    def test_k_larger_than_collection(self):
        index = HNSWIndex(M=4, ef_construction=20, ef_search=10)
        for i in range(3):
            index.insert(i, [float(i), 0.0], level=0)
        result = index.knn([0.0, 0.0], k=10)
        self.assertEqual(len(result), 3)
        self.assertEqual(len({node_id for node_id, _ in result}), 3)

    def test_non_positive_k_returns_empty(self):
        index = HNSWIndex(M=4)
        index.insert(1, [0.0, 0.0], level=0)
        self.assertEqual(index.knn([0.0, 0.0], k=0), [])
        self.assertEqual(index.knn([0.0, 0.0], k=-5), [])

    def test_invalid_query_dimension_and_ef_are_rejected(self):
        index = HNSWIndex(M=4)
        index.insert(1, [0.0, 0.0], level=0)
        with self.assertRaisesRegex(ValueError, "dimensión"):
            index.knn([0.0, 0.0, 0.0], k=1)
        with self.assertRaisesRegex(ValueError, "ef_search"):
            index.knn([0.0, 0.0], k=1, ef_search=0)

    def test_custom_metric_is_used_by_search(self):
        def manhattan(a, b):
            return sum(abs(x - y) for x, y in zip(a, b))

        index = HNSWIndex(M=4, ef_construction=20, ef_search=10, metric=manhattan)
        index.insert("a", [0.0, 0.0], level=0)
        index.insert("b", [2.0, 2.0], level=0)
        result = index.knn([1.9, 2.0], k=1)
        self.assertEqual(result[0][0], "b")
        self.assertAlmostEqual(result[0][1], 0.1)

    def test_high_ef_search_matches_bruteforce_on_small_dataset(self):
        rng = random.Random(7)
        index = HNSWIndex(M=8, ef_construction=80, ef_search=80, random_seed=42)
        for i in range(80):
            index.insert(i, [rng.random(), rng.random()])

        for _ in range(10):
            query = [rng.random(), rng.random()]
            approx = [node_id for node_id, _ in index.knn(query, k=10, ef_search=80)]
            exact = [node_id for node_id, _ in index.brute_force_knn(query, k=10)]
            self.assertEqual(approx, exact)

    def test_recall_at_10_is_high_on_reproducible_dataset(self):
        rng = random.Random(11)
        index = HNSWIndex(M=8, ef_construction=64, ef_search=32, random_seed=11)
        for i in range(200):
            index.insert(i, [rng.uniform(-1, 1), rng.uniform(-1, 1)])

        recalls = []
        for _ in range(20):
            query = [rng.uniform(-1, 1), rng.uniform(-1, 1)]
            approx = {node_id for node_id, _ in index.knn(query, k=10, ef_search=32)}
            exact = {node_id for node_id, _ in index.brute_force_knn(query, k=10)}
            recalls.append(len(approx & exact) / 10)

        self.assertGreaterEqual(sum(recalls) / len(recalls), 0.90)


if __name__ == "__main__":
    unittest.main()
