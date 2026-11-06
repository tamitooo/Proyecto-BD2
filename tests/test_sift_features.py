"""SIFT feature extraction — issues #102 and #80."""

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
from multimedia.sift import SIFTFeatureExtractor, extract_sift_descriptors


@pytest.fixture
def textured_image():
    # Seeded synthetic texture avoids external image files and is reproducible.
    return np.random.default_rng(2026).integers(0, 256, (160, 160), dtype=np.uint8)


def test_descriptors_have_correct_dtype_dimension_and_finite_values(textured_image):
    extractor = SIFTFeatureExtractor()
    keypoints, descriptors = extractor.extract_with_keypoints(textured_image)

    assert len(keypoints) > 0
    assert descriptors.shape == (len(keypoints), 128)
    assert descriptors.dtype == np.float32
    assert descriptors.flags.c_contiguous
    assert np.isfinite(descriptors).all()


def test_constant_image_returns_empty_matrix_not_none():
    keypoints, descriptors = SIFTFeatureExtractor().extract_with_keypoints(
        np.zeros((128, 128), dtype=np.uint8)
    )
    assert keypoints == []
    assert descriptors.shape == (0, 128)
    assert descriptors.dtype == np.float32


def test_repeated_extraction_is_deterministic(textured_image):
    extractor = SIFTFeatureExtractor(max_features=40)
    first = extractor.extract(textured_image)
    second = extractor.extract(textured_image)
    assert 0 < first.shape[0] <= 40
    np.testing.assert_array_equal(first, second)


def test_grayscale_and_bgr_arrays_produce_same_descriptors(textured_image):
    bgr = cv2.cvtColor(textured_image, cv2.COLOR_GRAY2BGR)
    extractor = SIFTFeatureExtractor()
    np.testing.assert_array_equal(extractor.extract(textured_image), extractor.extract(bgr))


def test_float_in_zero_one_range_is_supported(textured_image):
    extractor = SIFTFeatureExtractor()
    as_float = textured_image.astype(np.float32) / 255.0
    np.testing.assert_array_equal(extractor.extract(textured_image), extractor.extract(as_float))


def test_path_and_encoded_bytes_are_supported(tmp_path, textured_image):
    destination = tmp_path / "árbol ñ.png"
    encoded_ok, encoded = cv2.imencode(".png", textured_image)
    assert encoded_ok
    # cv2.imwrite itself is not reliable with Unicode Windows filenames.
    destination.write_bytes(encoded.tobytes())

    extractor = SIFTFeatureExtractor(max_features=30)
    expected = extractor.extract(textured_image)
    np.testing.assert_array_equal(expected, extractor.extract(destination))
    np.testing.assert_array_equal(expected, extractor.extract(encoded.tobytes()))
    np.testing.assert_array_equal(expected, extract_sift_descriptors(
        destination, max_features=30,
    ))


def test_mask_can_disable_all_features(textured_image):
    descriptors = SIFTFeatureExtractor().extract(
        textured_image, mask=np.zeros(textured_image.shape, dtype=np.uint8),
    )
    assert descriptors.shape == (0, 128)


def test_resize_option_limits_keypoint_coordinates(textured_image):
    extractor = SIFTFeatureExtractor(max_image_side=64)
    keypoints, descriptors = extractor.extract_with_keypoints(textured_image)
    assert descriptors.shape[1] == 128
    assert all(0 <= kp.pt[0] < 64 and 0 <= kp.pt[1] < 64 for kp in keypoints)


@pytest.mark.parametrize("bad", [
    np.empty((0, 1), dtype=np.uint8),
    np.zeros((8, 8, 2), dtype=np.uint8),
    np.full((8, 8), -1, dtype=np.int16),
    np.full((8, 8), np.nan, dtype=np.float32),
    np.full((8, 8), 300, dtype=np.float32),
])
def test_invalid_image_arrays_are_rejected(bad):
    with pytest.raises((TypeError, ValueError)):
        SIFTFeatureExtractor().extract(bad)


def test_invalid_path_bytes_and_input_type(tmp_path):
    extractor = SIFTFeatureExtractor()
    with pytest.raises(FileNotFoundError):
        extractor.extract(tmp_path / "absent.png")
    with pytest.raises(ValueError):
        extractor.extract(b"not a real image")
    with pytest.raises(ValueError):
        extractor.extract(b"")
    with pytest.raises(TypeError):
        extractor.extract(123)


def test_invalid_mask_dimensions(textured_image):
    with pytest.raises(ValueError, match="mask"):
        SIFTFeatureExtractor().extract(
            textured_image, mask=np.zeros((4, 4), dtype=np.uint8),
        )


@pytest.mark.parametrize("kwargs", [
    {"max_features": -1},
    {"max_features": True},
    {"n_octave_layers": 0},
    {"contrast_threshold": 0},
    {"edge_threshold": float("nan")},
    {"sigma": -1},
    {"max_image_side": 0},
])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        SIFTFeatureExtractor(**kwargs)
