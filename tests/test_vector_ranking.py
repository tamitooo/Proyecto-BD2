import math
import unittest

from vector import HNSWIndex, SearchResult, SimilarityRanking


class TestSimilarityRanking(unittest.TestCase):
    def test_euclidean_exposes_distance_and_higher_similarity_score(self):
        ranking = SimilarityRanking("euclidean")
        near = ranking.from_search_distance("near", 0.0)
        far = ranking.from_search_distance("far", 3.0)
        self.assertEqual(near.raw_metric, 0.0)
        self.assertEqual(near.score, 1.0)
        self.assertAlmostEqual(far.score, 0.25)
        self.assertGreater(near.score, far.score)

    def test_cosine_distance_is_converted_back_to_cosine_similarity(self):
        ranking = SimilarityRanking("cosine")
        result = ranking.from_search_distance("x", 0.2)  # 1 - 0.8
        self.assertAlmostEqual(result.raw_metric, 0.8)
        self.assertAlmostEqual(result.score, 0.8)

    def test_dot_search_cost_is_converted_back_to_dot_product(self):
        ranking = SimilarityRanking("dot_product")
        result = ranking.from_search_distance("x", -7.5)
        self.assertAlmostEqual(result.raw_metric, 7.5)
        self.assertAlmostEqual(result.score, 7.5)

    def test_aliases_are_supported(self):
        self.assertEqual(SimilarityRanking("l2").metric, "euclidean")
        self.assertEqual(SimilarityRanking("cos").metric, "cosine")
        self.assertEqual(SimilarityRanking("inner-product").metric, "dot_product")

    def test_unsupported_metric_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "métrica no soportada"):
            SimilarityRanking("manhattan")

    def test_non_finite_and_negative_euclidean_values_are_rejected(self):
        ranking = SimilarityRanking("euclidean")
        with self.assertRaises(ValueError):
            ranking.from_search_distance("x", math.inf)
        with self.assertRaises(ValueError):
            ranking.from_search_distance("x", -0.1)

    def test_ranking_is_score_descending_and_ties_are_deterministic(self):
        ranking = SimilarityRanking("euclidean")
        results = ranking.rank([("b", 1.0), ("a", 1.0), ("near", 0.1)], k=3)
        self.assertEqual([r.vector_id for r in results], ["near", "a", "b"])
        self.assertTrue(all(isinstance(r, SearchResult) for r in results))

    def test_non_positive_k_returns_empty(self):
        self.assertEqual(SimilarityRanking("euclidean").rank([("a", 1.0)], k=0), [])


class TestHNSWSimilarityResults(unittest.TestCase):
    def test_euclidean_search_similar_returns_score_without_recomputing_search(self):
        index = HNSWIndex(M=4, ef_construction=20, ef_search=10, metric_name="euclidean")
        index.insert("origin", [0.0, 0.0], level=0)
        index.insert("one", [1.0, 0.0], level=0)
        results = index.search_similar([0.0, 0.0], k=2)
        self.assertEqual([r.vector_id for r in results], ["origin", "one"])
        self.assertEqual(results[0].score, 1.0)
        self.assertGreater(results[0].score, results[1].score)
        self.assertEqual(results[0].metric, "euclidean")

    def test_cosine_contract_uses_one_minus_similarity_for_navigation(self):
        def cosine_distance(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            if na == 0 or nb == 0:
                return 1.0
            return 1.0 - dot / (na * nb)

        index = HNSWIndex(
            M=4,
            ef_construction=20,
            ef_search=10,
            metric=cosine_distance,
            metric_name="cosine",
        )
        index.insert("same", [1.0, 0.0], level=0)
        index.insert("orthogonal", [0.0, 1.0], level=0)
        results = index.search_similar([1.0, 0.0], k=2)
        self.assertEqual(results[0].vector_id, "same")
        self.assertAlmostEqual(results[0].score, 1.0)
        self.assertAlmostEqual(results[1].score, 0.0)

    def test_dot_product_contract_uses_negative_dot_for_navigation(self):
        def negative_dot(a, b):
            return -sum(x * y for x, y in zip(a, b))

        index = HNSWIndex(
            M=4,
            ef_construction=20,
            ef_search=10,
            metric=negative_dot,
            metric_name="dot_product",
        )
        index.insert("best", [3.0, 0.0], level=0)
        index.insert("mid", [2.0, 0.0], level=0)
        results = index.search_similar([1.0, 0.0], k=2)
        self.assertEqual([r.vector_id for r in results], ["best", "mid"])
        self.assertEqual([r.score for r in results], [3.0, 2.0])

    def test_stats_exposes_metric_contract(self):
        index = HNSWIndex(metric_name="cosine")
        self.assertEqual(index.stats()["metric"], "cosine")


if __name__ == "__main__":
    unittest.main()
