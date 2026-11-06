"""K-Means quantization, histograms and TF-IDF (#104-#106, #80)."""

import numpy as np
import pytest

from multimedia.histograms import word_histogram
from multimedia.quantization import KMeansCodebook
from multimedia.tfidf import HistogramTFIDF


def test_kmeans_finds_separated_centers_and_predicts():
    rng = np.random.default_rng(7)
    points = np.vstack((rng.normal(-3, 0.05, (50, 3)), rng.normal(3, 0.05, (50, 3))))
    codebook = KMeansCodebook(2, random_state=4).fit(points)
    centers = codebook.centers_
    assert centers.shape == (2, 3)
    assert np.isfinite(centers).all() and codebook.inertia_ >= 0
    ids = codebook.predict(points)
    assert len(set(ids[:50])) == len(set(ids[50:])) == 1
    assert ids[0] != ids[50]


def test_kmeans_reproducibility_and_save_load(tmp_path):
    data = np.random.default_rng(11).normal(size=(60, 13)).astype(np.float32)
    first = KMeansCodebook(5, random_state=12, batch_size=7).fit(data)
    second = KMeansCodebook(5, random_state=12, batch_size=7).fit(data)
    np.testing.assert_array_equal(first.centers_, second.centers_)
    path = first.save(tmp_path / "vocabulary.npz")
    restored = KMeansCodebook.load(path)
    np.testing.assert_array_equal(first.predict(data), restored.predict(data))
    with pytest.raises(FileExistsError):
        first.save(path)


def test_kmeans_identical_descriptors_and_empty_predict():
    data = np.zeros((8, 128), dtype=np.float32)
    model = KMeansCodebook(4).fit(data)
    assert model.predict(data).shape == (8,)
    assert model.predict(np.empty((0, 128), dtype=np.float32)).shape == (0,)


def test_kmeans_invalid_training_and_dimensions():
    with pytest.raises(ValueError):
        KMeansCodebook(4).fit(np.ones((3, 13)))
    with pytest.raises(RuntimeError):
        KMeansCodebook(2).predict(np.ones((1, 3)))
    model = KMeansCodebook(2).fit(np.ones((4, 13)))
    with pytest.raises(ValueError):
        model.predict(np.ones((1, 128)))
    with pytest.raises(ValueError):
        model.predict(np.full((1, 13), np.nan))


def test_histogram_counts_and_normalizations():
    ids = np.array([0, 2, 2, 3, 3, 3], dtype=np.int32)
    np.testing.assert_array_equal(word_histogram(ids, 5, normalization=None), [1, 0, 2, 3, 0])
    np.testing.assert_allclose(word_histogram(ids, 5).sum(), 1.0)
    np.testing.assert_allclose(np.linalg.norm(word_histogram(ids, 5, normalization="l2")), 1.0)
    np.testing.assert_array_equal(word_histogram([], 5), np.zeros(5))


def test_histogram_rejects_invalid_assignments():
    with pytest.raises(ValueError):
        word_histogram(np.array([5]), 5)
    with pytest.raises(ValueError):
        word_histogram(np.array([0.2]), 5)


def test_tfidf_rare_words_weight_more_and_norms():
    documents = np.array([[2, 1, 0], [1, 0, 0], [2, 0, 1]], dtype=np.float32)
    model = HistogramTFIDF().fit(documents)
    assert model.idf_[1] > model.idf_[0]
    transformed = model.transform(documents)
    np.testing.assert_allclose(np.linalg.norm(transformed, axis=1), np.ones(3), atol=1e-6)
    np.testing.assert_array_equal(model.transform([0, 0, 0]), np.zeros(3))
    assert transformed.shape == documents.shape and transformed.dtype == np.float32


def test_tfidf_validation():
    with pytest.raises(RuntimeError):
        HistogramTFIDF().transform([1, 2])
    with pytest.raises(ValueError):
        HistogramTFIDF().fit(np.zeros((0, 3)))
    model = HistogramTFIDF().fit(np.ones((2, 3)))
    with pytest.raises(ValueError):
        model.transform([1, 2])
    with pytest.raises(ValueError):
        model.transform([-1, 0, 1])
