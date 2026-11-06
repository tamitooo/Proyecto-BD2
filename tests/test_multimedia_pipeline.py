"""Unified ExtractFeatures and vector-index integration (#107, #80)."""

import numpy as np
import pytest

from multimedia import ExtractFeatures, MultimediaFeaturePipeline, MultimediaObject
from vector.hnsw import HNSWIndex


class _DescriptorExtractor:
    """Allows deterministic pipeline tests independent of codec versions."""

    def extract(self, source, **kwargs):
        return np.asarray(source, dtype=np.float32)


def test_mixed_corpus_trains_independent_vocabulary_and_idf():
    visual_a = np.array([[0, 0], [0, .1], [2, 2]], dtype=np.float32)
    visual_b = np.array([[3, 3], [3.1, 3.1]], dtype=np.float32)
    audio_a = np.array([[0, 1, 1], [.1, 1, 1]], dtype=np.float32)
    audio_b = np.array([[3, 2, 1], [3.1, 2, 1]], dtype=np.float32)
    objects = [
        MultimediaObject("image", visual_a),
        MultimediaObject("image", visual_b),
        MultimediaObject("audio", audio_a, sample_rate=22050),
        MultimediaObject("audio", audio_b, sample_rate=22050),
    ]
    pipeline = MultimediaFeaturePipeline(
        n_visual_words=2, n_audio_words=3, random_state=9,
        sift=_DescriptorExtractor(), mfcc=_DescriptorExtractor(),
    ).fit(objects)

    visual_vector = ExtractFeatures(objects[0], pipeline=pipeline)
    audio_vector = ExtractFeatures(objects[2], pipeline=pipeline)
    assert visual_vector.shape == (2,)
    assert audio_vector.shape == (3,)
    assert np.isfinite(visual_vector).all() and np.isfinite(audio_vector).all()
    np.testing.assert_array_equal(visual_vector, pipeline.ExtractFeatures(objects[0]))
    np.testing.assert_array_equal(
        audio_vector, pipeline.extract_features({
            "modality": "audio", "data": audio_a, "sample_rate": 22050,
        }),
    )
    assert pipeline.visual_codebook.dimension == 2
    assert pipeline.audio_codebook.dimension == 3


def test_repeatable_training_and_hnsw_vector_compatibility():
    objects = [
        {"modality": "image", "source": np.array([[i, i + .1], [i + .2, i]])}
        for i in range(5)
    ]
    def train():
        return MultimediaFeaturePipeline(
            n_visual_words=3, random_state=5,
            max_training_descriptors=6, sift=_DescriptorExtractor(),
        ).fit(objects)
    first, second = train(), train()
    one = first.extract_features(objects[0])
    np.testing.assert_array_equal(one, second.extract_features(objects[0]))

    index = HNSWIndex(random_seed=7)
    for i, item in enumerate(objects):
        index.insert(i, first.extract_features(item).tolist(), level=0)
    assert index.search_similar(one.tolist(), k=1)[0].vector_id == 0


def test_zero_descriptor_object_is_a_zero_feature_vector():
    objects = [MultimediaObject("image", np.array([[0., 0.], [1., 1.]]))]
    pipeline = MultimediaFeaturePipeline(n_visual_words=2, sift=_DescriptorExtractor()).fit(objects)
    result = pipeline.extract_features(MultimediaObject("image", np.empty((0, 2))))
    np.testing.assert_array_equal(result, np.zeros(2))


def test_audio_only_training_does_not_construct_sift(monkeypatch):
    def forbid_sift():
        raise AssertionError("audio-only training must not initialize OpenCV SIFT")
    monkeypatch.setattr("multimedia.pipeline.SIFTFeatureExtractor", forbid_sift)
    audio = MultimediaObject("audio", np.array([[1., 2.], [3., 4.]]), sample_rate=22050)
    pipe = MultimediaFeaturePipeline(n_audio_words=2, mfcc=_DescriptorExtractor()).fit([audio])
    assert pipe.extract_features(audio).shape == (2,)


def test_pipeline_model_save_load_roundtrip(tmp_path):
    examples = [
        MultimediaObject("image", np.array([[0., 1.], [1., 0.]])),
        MultimediaObject("image", np.array([[5., 4.], [4., 5.]])),
    ]
    original = MultimediaFeaturePipeline(
        n_visual_words=2, sift=_DescriptorExtractor(), random_state=14,
    ).fit(examples)
    path = original.save(tmp_path / "multimedia-model.npz")
    recovered = MultimediaFeaturePipeline.load(path, sift=_DescriptorExtractor())
    np.testing.assert_array_equal(
        original.extract_features(examples[0]),
        recovered.extract_features(examples[0]),
    )
    with pytest.raises(FileExistsError):
        original.save(path)


def test_invalid_objects_and_untrained_pipeline():
    pipe = MultimediaFeaturePipeline(n_visual_words=2, sift=_DescriptorExtractor())
    with pytest.raises(RuntimeError):
        pipe.extract_features(MultimediaObject("image", np.ones((2, 2))))
    with pytest.raises(ValueError):
        pipe.fit([])
    with pytest.raises(ValueError):
        pipe.fit([MultimediaObject("video", np.ones((2, 2)))])
    with pytest.raises(TypeError):
        ExtractFeatures(MultimediaObject("image", np.ones((2, 2))), pipeline=None)


def test_end_to_end_with_real_sift_and_mfcc():
    pytest.importorskip("cv2")
    pytest.importorskip("librosa")
    image = np.random.default_rng(5).integers(0, 256, (160, 160), dtype=np.uint8)
    sample_rate = 16_000
    t = np.arange(sample_rate // 3, dtype=np.float32) / sample_rate
    audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    objects = [
        MultimediaObject("image", image),
        MultimediaObject("audio", audio, sample_rate=sample_rate),
    ]
    pipeline = MultimediaFeaturePipeline(
        n_visual_words=2, n_audio_words=2, random_state=42,
        max_training_descriptors=100,
    ).fit(objects)
    for item in objects:
        vector = ExtractFeatures(item, pipeline=pipeline)
        assert vector.shape == (2,)
        assert vector.dtype == np.float32
        assert np.isfinite(vector).all()
