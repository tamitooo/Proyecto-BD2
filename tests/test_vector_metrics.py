import math
import unittest

try:
    import numpy
except ImportError:
    numpy = None

from vector import (
    HNSWIndex,
    cosine_distance,
    cosine_similarity,
    dot_product,
    euclidean_distance,
    get_search_metric,
    negative_dot_product,
)


class TestEuclideanDistance(unittest.TestCase):
    def test_known_distance(self):
        self.assertAlmostEqual(euclidean_distance([0.0, 0.0], [3.0, 4.0]), 5.0)

    def test_identical_vectors_have_zero_distance(self):
        self.assertEqual(euclidean_distance([1.5, -2.0], [1.5, -2.0]), 0.0)

    def test_is_symmetric(self):
        first, second = [1.0, 2.0, 3.0], [-4.0, 0.5, 9.0]
        self.assertAlmostEqual(
            euclidean_distance(first, second),
            euclidean_distance(second, first),
        )


class TestDotProduct(unittest.TestCase):
    def test_known_value(self):
        self.assertAlmostEqual(dot_product([1.0, 2.0, 3.0], [4.0, -5.0, 6.0]), 12.0)

    def test_orthogonal_vectors(self):
        self.assertEqual(dot_product([1.0, 0.0], [0.0, 5.0]), 0.0)

    def test_grows_with_magnitude(self):
        self.assertAlmostEqual(dot_product([2.0, 0.0], [3.0, 0.0]), 6.0)


class TestCosineSimilarity(unittest.TestCase):
    def test_same_direction_ignores_magnitude(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 2.0], [10.0, 20.0]), 1.0)

    def test_orthogonal_vectors(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_opposite_vectors(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 2.0], [-1.0, -2.0]), -1.0)

    def test_zero_vector_has_no_similarity(self):
        self.assertEqual(cosine_similarity([0.0, 0.0], [1.0, 2.0]), 0.0)
        self.assertEqual(cosine_similarity([1.0, 2.0], [0.0, 0.0]), 0.0)

    def test_extreme_magnitudes_do_not_change_the_result(self):
        for scale in (1e-200, 1e200):
            with self.subTest(scale=scale):
                self.assertAlmostEqual(
                    cosine_similarity([scale, 0.0], [scale, 0.0]), 1.0
                )
                self.assertAlmostEqual(
                    cosine_similarity([scale, scale], [scale, -scale]), 0.0
                )

    def test_rounding_never_leaves_the_valid_range(self):
        vector = [0.1, 0.2, 0.3, 0.7, 1.3]
        self.assertLessEqual(cosine_similarity(vector, vector), 1.0)
        self.assertGreaterEqual(cosine_distance(vector, vector), 0.0)


class TestValidation(unittest.TestCase):
    METRICS = (euclidean_distance, dot_product, cosine_similarity)

    @unittest.skipIf(numpy is None, "numpy no está instalado")
    def test_numpy_arrays_are_accepted(self):
        first, second = numpy.array([1.0, 2.0]), numpy.array([3.0, 4.0])
        for metric in self.METRICS:
            with self.subTest(metric=metric.__name__):
                self.assertAlmostEqual(
                    metric(first, second),
                    metric([1.0, 2.0], [3.0, 4.0]),
                )

    def test_different_dimensions_are_rejected(self):
        for metric in self.METRICS:
            with self.subTest(metric=metric.__name__):
                with self.assertRaisesRegex(ValueError, "misma dimensión"):
                    metric([1.0, 2.0], [1.0])

    def test_empty_vectors_are_rejected(self):
        for metric in self.METRICS:
            with self.subTest(metric=metric.__name__):
                with self.assertRaisesRegex(ValueError, "vacíos"):
                    metric([], [])

    def test_non_finite_values_are_rejected(self):
        for metric in self.METRICS:
            for value in (math.nan, math.inf):
                with self.subTest(metric=metric.__name__, value=value):
                    with self.assertRaisesRegex(ValueError, "finito"):
                        metric([value, 1.0], [1.0, 1.0])


class TestSearchMetrics(unittest.TestCase):
    def test_costs_follow_the_ranking_convention(self):
        first, second = [1.0, 2.0], [3.0, 1.0]
        self.assertEqual(
            get_search_metric("euclidean")(first, second),
            euclidean_distance(first, second),
        )
        self.assertAlmostEqual(
            get_search_metric("cosine")(first, second),
            1.0 - cosine_similarity(first, second),
        )
        self.assertAlmostEqual(
            get_search_metric("dot_product")(first, second),
            -dot_product(first, second),
        )

    def test_aliases_match_similarity_ranking(self):
        self.assertIs(get_search_metric("l2"), euclidean_distance)
        self.assertIs(get_search_metric("cos"), cosine_distance)
        self.assertIs(get_search_metric("inner-product"), negative_dot_product)

    def test_unsupported_metric_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "métrica no soportada"):
            get_search_metric("manhattan")


class TestHNSWIntegration(unittest.TestCase):
    def build_index(self, metric_name):
        index = HNSWIndex(
            M=4,
            ef_construction=20,
            ef_search=10,
            metric=get_search_metric(metric_name),
            metric_name=metric_name,
        )
        index.insert("aligned", [10.0, 0.0], level=0)
        index.insert("diagonal", [1.0, 1.0], level=0)
        index.insert("opposite", [-1.0, 0.0], level=0)
        return index

    def test_cosine_prefers_direction_over_proximity(self):
        results = self.build_index("cosine").search_similar([1.0, 0.0], k=3)
        self.assertEqual(
            [result.vector_id for result in results],
            ["aligned", "diagonal", "opposite"],
        )
        self.assertAlmostEqual(results[0].raw_metric, 1.0)
        self.assertAlmostEqual(results[2].raw_metric, -1.0)

    def test_dot_product_exposes_the_natural_value(self):
        results = self.build_index("dot_product").search_similar([1.0, 0.0], k=1)
        self.assertEqual(results[0].vector_id, "aligned")
        self.assertAlmostEqual(results[0].raw_metric, 10.0)


if __name__ == "__main__":
    unittest.main()
