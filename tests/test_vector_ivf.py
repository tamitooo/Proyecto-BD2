import math
import random
import tempfile
import unittest
from pathlib import Path

from vector import IVFIndex, get_search_metric


def blob(center, count, rng, spread=0.05):
    return [[value + rng.gauss(0.0, spread) for value in center] for _ in range(count)]


class TestConstruction(unittest.TestCase):
    def test_invalid_parameters_are_rejected(self):
        for kwargs in (
            {"n_lists": 0},
            {"n_lists": 2, "max_iterations": 0},
            {"n_lists": 2, "training_points_per_list": 0},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    IVFIndex(**kwargs)

    def test_unsupported_metric_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "métrica no soportada"):
            IVFIndex(n_lists=2, metric_name="manhattan")

    def test_aliases_are_normalized(self):
        self.assertEqual(IVFIndex(n_lists=2, metric_name="cos").metric_name, "cosine")

    def test_new_index_is_empty_and_untrained(self):
        index = IVFIndex(n_lists=2)
        self.assertEqual(len(index), 0)
        self.assertFalse(index.is_trained)
        self.assertTrue(index.validate())


class TestTraining(unittest.TestCase):
    def test_needs_at_least_one_vector_per_list(self):
        with self.assertRaisesRegex(ValueError, "al menos 3 vectores"):
            IVFIndex(n_lists=3).train([[0.0, 0.0], [1.0, 1.0]])

    def test_vectors_must_share_dimension(self):
        with self.assertRaisesRegex(ValueError, "misma dimensión"):
            IVFIndex(n_lists=2).train([[0.0, 0.0], [1.0]])

    def test_empty_and_non_finite_vectors_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "vacío"):
            IVFIndex(n_lists=1).train([[]])
        with self.assertRaisesRegex(ValueError, "finitos"):
            IVFIndex(n_lists=1).train([[math.nan, 1.0]])

    def test_centroids_recover_separated_clusters(self):
        rng = random.Random(1)
        centers = [(0.0, 0.0), (10.0, 0.0), (0.0, 10.0)]
        points = [p for center in centers for p in blob(center, 50, rng)]
        index = IVFIndex(n_lists=3, random_seed=1)
        index.train(points)
        for center in centers:
            nearest = min(
                math.dist(center, centroid) for centroid in index.centroids
            )
            self.assertLess(nearest, 0.2)

    def test_same_seed_gives_same_centroids(self):
        rng = random.Random(2)
        points = blob((0.0, 0.0), 100, rng, spread=1.0)
        first, second = IVFIndex(n_lists=4, random_seed=9), IVFIndex(
            n_lists=4, random_seed=9
        )
        first.train(points)
        second.train(points)
        self.assertEqual(first.centroids, second.centroids)

    def test_repeated_points_do_not_break_training(self):
        index = IVFIndex(n_lists=3, random_seed=1)
        index.train([[1.0, 1.0]] * 10)
        self.assertEqual(len(index.centroids), 3)
        self.assertTrue(index.validate())

    def test_training_sample_is_capped_per_list(self):
        seen = []

        class SpyIndex(IVFIndex):
            def _kmeans(self, points):
                seen.append(len(points))
                return super()._kmeans(points)

        rng = random.Random(3)
        index = SpyIndex(n_lists=2, training_points_per_list=5, random_seed=1)
        index.train(blob((0.0, 0.0), 100, rng))
        self.assertEqual(seen, [10])

    def test_can_retrain_while_empty_but_not_with_vectors(self):
        index = IVFIndex(n_lists=1)
        index.train([[0.0, 0.0]])
        index.train([[1.0, 1.0]])
        index.insert("a", [1.0, 1.0])
        with self.assertRaisesRegex(ValueError, "reentrenar"):
            index.train([[2.0, 2.0]])

    def test_cosine_groups_by_direction_not_by_magnitude(self):
        rng = random.Random(4)
        points = []
        for _ in range(60):
            scale = rng.uniform(0.1, 1000.0)
            points.append([scale, scale * 0.01])
            points.append([scale * 0.01, scale])
        index = IVFIndex(n_lists=2, metric_name="cosine", random_seed=1)
        index.train(points)
        self.assertNotEqual(index.assign([1.0, 0.0]), index.assign([0.0, 1.0]))
        self.assertEqual(index.assign([500.0, 1.0]), index.assign([0.5, 0.001]))

    def test_cosine_centroids_are_unit_vectors(self):
        rng = random.Random(8)
        index = IVFIndex(n_lists=2, metric_name="cosine", random_seed=1)
        index.train(blob((5.0, 5.0), 40, rng, spread=2.0))
        for centroid in index.centroids:
            self.assertAlmostEqual(math.hypot(*centroid), 1.0)

    def test_cosine_accepts_zero_vectors(self):
        index = IVFIndex(n_lists=2, metric_name="cosine", random_seed=1)
        index.train([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 0.1]])
        index.insert("zero", [0.0, 0.0])
        self.assertEqual(len(index), 1)


class TestInsert(unittest.TestCase):
    def setUp(self):
        self.rng = random.Random(5)
        self.points = blob((0.0, 0.0), 40, self.rng) + blob((9.0, 9.0), 40, self.rng)
        self.index = IVFIndex(n_lists=2, random_seed=1)
        self.index.train(self.points)

    def test_insert_requires_training(self):
        with self.assertRaisesRegex(ValueError, "entrenarse"):
            IVFIndex(n_lists=2).insert("a", [1.0, 2.0])

    def test_nearby_vectors_share_a_list(self):
        self.assertEqual(
            self.index.insert("a", [0.1, 0.0]), self.index.insert("b", [0.0, 0.1])
        )
        self.assertNotEqual(
            self.index.insert("c", [9.0, 9.0]), self.index.insert("d", [0.0, 0.0])
        )

    def test_vector_is_stored_in_its_inverted_list(self):
        list_id = self.index.insert("a", [1, 2])
        self.assertEqual(self.index.lists[list_id]["a"], (1.0, 2.0))
        self.assertEqual(len(self.index), 1)
        self.assertTrue(self.index.validate())

    def test_duplicate_id_is_rejected(self):
        self.index.insert("a", [0.0, 0.0])
        with self.assertRaisesRegex(ValueError, "duplicado"):
            self.index.insert("a", [1.0, 1.0])

    def test_wrong_dimension_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "dimensión inválida"):
            self.index.insert("a", [1.0])

    def test_failed_insert_leaves_the_index_unchanged(self):
        with self.assertRaises(ValueError):
            self.index.insert("a", [math.inf, 0.0])
        self.assertEqual(len(self.index), 0)
        self.assertTrue(self.index.validate())

    def test_every_metric_assigns_to_the_lowest_cost_centroid(self):
        for metric_name in ("euclidean", "cosine", "dot_product"):
            with self.subTest(metric=metric_name):
                index = IVFIndex(n_lists=4, metric_name=metric_name, random_seed=1)
                index.build(enumerate(blob((1.0, 2.0), 80, self.rng, spread=3.0)))
                cost = get_search_metric(metric_name)
                for list_id, inverted_list in enumerate(index.lists):
                    for vector in inverted_list.values():
                        best = min(cost(vector, c) for c in index.centroids)
                        self.assertEqual(cost(vector, index.centroids[list_id]), best)


class TestBuild(unittest.TestCase):
    def test_build_trains_and_inserts_everything(self):
        rng = random.Random(6)
        vectors = blob((0.0, 0.0), 50, rng) + blob((5.0, 5.0), 50, rng)
        index = IVFIndex(n_lists=2, random_seed=1)
        index.build(enumerate(vectors))
        self.assertEqual(len(index), 100)
        self.assertEqual(
            sorted(len(inverted_list) for inverted_list in index.lists), [50, 50]
        )
        self.assertTrue(index.validate())

    def test_duplicate_ids_leave_the_index_untouched(self):
        index = IVFIndex(n_lists=1)
        with self.assertRaisesRegex(ValueError, "duplicado"):
            index.build([("a", [0.0]), ("a", [1.0])])
        self.assertFalse(index.is_trained)

    def test_stats_summarize_the_index(self):
        index = IVFIndex(n_lists=2, random_seed=1)
        index.build([("a", [0.0]), ("b", [10.0]), ("c", [10.1])])
        stats = index.stats()
        self.assertEqual(stats["vectors"], 3)
        self.assertEqual(stats["dimension"], 1)
        self.assertEqual(stats["non_empty_lists"], 2)
        self.assertEqual(stats["largest_list"], 2)
        self.assertEqual(stats["metric"], "euclidean")


class TestSearch(unittest.TestCase):
    METRICS = ("euclidean", "cosine", "dot_product")

    def setUp(self):
        self.rng = random.Random(10)
        centers = [
            [self.rng.gauss(0.0, 4.0) for _ in range(8)] for _ in range(10)
        ]
        self.vectors = [
            [value + self.rng.gauss(0.0, 1.0) for value in self.rng.choice(centers)]
            for _ in range(600)
        ]
        self.queries = [
            [value + self.rng.gauss(0.0, 1.0) for value in self.rng.choice(centers)]
            for _ in range(30)
        ]

    def build(self, metric_name="euclidean", **kwargs):
        index = IVFIndex(n_lists=16, metric_name=metric_name, random_seed=1, **kwargs)
        index.build(enumerate(self.vectors))
        return index

    def test_invalid_n_probe_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "n_probe"):
            IVFIndex(n_lists=2, n_probe=0)
        with self.assertRaisesRegex(ValueError, "n_probe"):
            self.build().knn(self.queries[0], n_probe=0)

    def test_default_n_probe_is_sqrt_of_lists(self):
        self.assertEqual(IVFIndex(n_lists=16).n_probe, 4)
        self.assertEqual(IVFIndex(n_lists=17).n_probe, 5)
        self.assertEqual(IVFIndex(n_lists=16, n_probe=2).n_probe, 2)

    def test_non_positive_k_returns_empty(self):
        self.assertEqual(self.build().knn(self.queries[0], k=0), [])

    def test_empty_index_returns_empty(self):
        self.assertEqual(IVFIndex(n_lists=2).knn([1.0, 2.0]), [])
        self.assertEqual(IVFIndex(n_lists=2).brute_force_knn([1.0, 2.0]), [])

    def test_wrong_query_dimension_is_rejected(self):
        index = self.build()
        with self.assertRaisesRegex(ValueError, "dimensión inválida"):
            index.knn([1.0])
        with self.assertRaisesRegex(ValueError, "dimensión inválida"):
            index.brute_force_knn([1.0])

    def test_non_finite_query_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "finitos"):
            self.build().knn([math.nan] * 8)

    def test_results_are_sorted_by_cost(self):
        results = self.build().knn(self.queries[0], k=10)
        costs = [cost for _, cost in results]
        self.assertEqual(len(results), 10)
        self.assertEqual(costs, sorted(costs))

    def test_finds_an_inserted_vector(self):
        index = self.build()
        results = index.knn(self.vectors[42], k=1)
        self.assertEqual(results, [(42, 0.0)])

    def test_probing_every_list_matches_brute_force(self):
        for metric_name in self.METRICS:
            index = self.build(metric_name)
            for query in self.queries:
                with self.subTest(metric=metric_name):
                    self.assertEqual(
                        index.knn(query, k=10, n_probe=index.n_lists),
                        index.brute_force_knn(query, k=10),
                    )

    def test_brute_force_matches_an_independent_scan(self):
        index = self.build()
        for query in self.queries:
            expected = sorted(
                range(len(self.vectors)),
                key=lambda item: math.dist(query, self.vectors[item]),
            )[:10]
            found = [vector_id for vector_id, _ in index.brute_force_knn(query)]
            self.assertEqual(found, expected)

    def test_recall_is_high_with_a_few_lists(self):
        for metric_name in self.METRICS:
            with self.subTest(metric=metric_name):
                index = self.build(metric_name)
                hits = 0
                for query in self.queries:
                    exact = {item for item, _ in index.brute_force_knn(query)}
                    hits += len(exact & {item for item, _ in index.knn(query)})
                self.assertGreaterEqual(hits / (10 * len(self.queries)), 0.9)

    def test_more_lists_never_reduce_the_candidates_inspected(self):
        index = self.build()
        query = self.queries[0]
        exact = {item for item, _ in index.brute_force_knn(query, k=20)}
        previous = 0
        for n_probe in (1, 4, 16):
            found = {item for item, _ in index.knn(query, k=20, n_probe=n_probe)}
            self.assertGreaterEqual(len(exact & found), previous)
            previous = len(exact & found)

    def test_k_larger_than_probed_lists_keeps_probing(self):
        index = IVFIndex(n_lists=2, n_probe=1, random_seed=1)
        index.build(
            [("a", [0.0]), ("b", [0.1]), ("c", [10.0]), ("d", [10.1])]
        )
        self.assertEqual(
            [vector_id for vector_id, _ in index.knn([0.0], k=3)], ["a", "b", "c"]
        )

    def test_k_larger_than_the_index_returns_everything(self):
        index = IVFIndex(n_lists=2, random_seed=1)
        index.build([("a", [0.0]), ("b", [10.0])])
        self.assertEqual(len(index.knn([0.0], k=50)), 2)

    def test_empty_lists_do_not_consume_probes(self):
        index = IVFIndex(n_lists=3, n_probe=1, random_seed=1)
        index.train([[0.0], [5.0], [10.0]])
        index.insert("far", [10.0])
        nearest_empty_centroid_query = [0.0]
        self.assertEqual(
            index.knn(nearest_empty_centroid_query, k=1)[0][0], "far"
        )

    def test_ties_are_deterministic(self):
        index = IVFIndex(n_lists=1, random_seed=1)
        index.build([("b", [1.0]), ("a", [1.0]), (3, [1.0])])
        self.assertEqual(
            [vector_id for vector_id, _ in index.knn([1.0], k=3)], ["a", "b", 3]
        )

    def test_search_similar_exposes_the_public_contract(self):
        vectors = [("aligned", [10.0, 0.0]), ("opposite", [-1.0, 0.0])]
        expected = {
            "euclidean": ([1.0, 0.0], "opposite", 2.0, 1.0 / 3.0),
            "cosine": ([1.0, 0.0], "aligned", 1.0, 1.0),
            "dot_product": ([1.0, 0.0], "aligned", 10.0, 10.0),
        }
        for metric_name, (query, best, raw, score) in expected.items():
            with self.subTest(metric=metric_name):
                index = IVFIndex(n_lists=2, metric_name=metric_name, random_seed=1)
                index.build(vectors)
                results = index.search_similar(query, k=2)
                self.assertEqual(results[0].vector_id, best)
                self.assertEqual(results[0].metric, metric_name)
                self.assertAlmostEqual(results[0].raw_metric, raw)
                self.assertAlmostEqual(results[0].score, score)
                self.assertGreater(results[0].score, results[1].score)

    def test_search_finds_vectors_after_reloading(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "idx.idx"
            index = IVFIndex(n_lists=4, n_probe=2, random_seed=1)
            index.attach_file(path)
            index.build(enumerate(self.vectors))

            restored = IVFIndex(n_lists=1)
            restored.attach_file(path)
            self.assertEqual(restored.n_probe, 2)
            self.assertEqual(
                restored.knn(self.queries[0]), index.knn(self.queries[0])
            )


class TestPersistence(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "indexes" / "idx_vector.idx"
        self.rng = random.Random(7)
        self.items = list(enumerate(blob((0.0, 0.0), 30, self.rng, spread=2.0)))

    def build(self, metric_name="euclidean"):
        index = IVFIndex(n_lists=3, metric_name=metric_name, random_seed=1)
        index.attach_file(self.path)
        index.build(self.items)
        return index

    def test_build_writes_a_real_file(self):
        index = self.build()
        self.assertTrue(self.path.exists())
        self.assertEqual(index.serialized_size_bytes(), self.path.stat().st_size)
        self.assertGreater(index.serialized_size_bytes(), 0)

    def test_restart_restores_the_index_without_training(self):
        original = self.build("cosine")
        restored = IVFIndex(n_lists=1)
        restored.train = None  # Cualquier reentrenamiento haría fallar la prueba.
        self.assertTrue(restored.attach_file(self.path))
        self.assertEqual(restored.metric_name, "cosine")
        self.assertEqual(restored.centroids, original.centroids)
        self.assertEqual(restored.lists, original.lists)
        self.assertEqual(len(restored), len(original))

    def test_restored_index_keeps_inserting_and_detects_duplicates(self):
        self.build()
        restored = IVFIndex(n_lists=3)
        restored.attach_file(self.path)
        with self.assertRaisesRegex(ValueError, "duplicado"):
            restored.insert(0, [0.0, 0.0])
        restored.insert("new", [0.0, 0.0])

        reopened = IVFIndex(n_lists=3)
        reopened.attach_file(self.path)
        self.assertEqual(len(reopened), len(self.items) + 1)

    def test_attach_without_file_leaves_the_index_empty(self):
        index = IVFIndex(n_lists=3)
        self.assertFalse(index.attach_file(self.path))
        self.assertFalse(index.is_trained)

    def test_load_existing_false_ignores_the_file(self):
        self.build()
        index = IVFIndex(n_lists=3)
        self.assertFalse(index.attach_file(self.path, load_existing=False))
        self.assertFalse(index.is_trained)

    def test_incompatible_file_is_rejected(self):
        from indexes.persistence import atomic_pickle_write

        atomic_pickle_write(self.path, {"kind": "extendible_hash"})
        with self.assertRaisesRegex(ValueError, "IVF incompatible"):
            IVFIndex(n_lists=3).attach_file(self.path)

    def test_drop_removes_the_file(self):
        index = self.build()
        index.drop_persistent_file()
        self.assertFalse(self.path.exists())
        self.assertEqual(index.serialized_size_bytes(), 0)


class TestValidate(unittest.TestCase):
    def test_detects_a_vector_in_the_wrong_list(self):
        index = IVFIndex(n_lists=2, random_seed=1)
        index.build([("a", [0.0]), ("b", [10.0])])
        source = index._assignments["a"]
        index.lists[1 - source]["a"] = index.lists[source].pop("a")
        with self.assertRaisesRegex(AssertionError, "asignación inconsistente"):
            index.validate()


if __name__ == "__main__":
    unittest.main()
