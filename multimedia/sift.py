"""SIFT local image descriptor extraction (Part 4, issue #102).

The output is a ``numpy.float32`` array with shape ``(keypoints, 128)``.
Zero-keypoint images return ``(0, 128)``, not ``None``, so the future visual
vocabulary and histogram stages can consume a consistent interface.

Supported inputs: an image filename (including Windows Unicode paths), encoded
image bytes, or a NumPy grayscale/BGR/BGRA image. Array channels follow
OpenCV's BGR convention. Input images are processed in grayscale.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

DESCRIPTOR_DIMENSION = 128


def _opencv() -> Any:
    """Keep cv2 optional until image feature extraction is actually used."""
    try:
        import cv2
    except ImportError as exc:
        raise ImportError(
            "SIFT extraction requires OpenCV: pip install opencv-python>=4.8"
        ) from exc
    if not hasattr(cv2, "SIFT_create"):
        raise RuntimeError("this OpenCV build does not provide cv2.SIFT_create")
    return cv2


def _uint8_array(image: np.ndarray) -> np.ndarray:
    """Convert supported numeric images without silently clipping values."""
    if image.size == 0:
        raise ValueError("image must not be empty")
    if image.dtype == np.uint8:
        return image

    if np.issubdtype(image.dtype, np.floating):
        if not np.all(np.isfinite(image)):
            raise ValueError("image pixels must be finite")
        low, high = float(image.min()), float(image.max())
        if low < 0 or high > 255:
            raise ValueError("floating pixels must be in [0, 1] or [0, 255]")
        factor = 255.0 if high <= 1.0 else 1.0
        return np.rint(image * factor).astype(np.uint8)

    if np.issubdtype(image.dtype, np.integer):
        if int(image.min()) < 0 or int(image.max()) > 255:
            raise ValueError("integer pixels must be in [0, 255]")
        return image.astype(np.uint8)

    raise TypeError("image array must have a numeric pixel dtype")


class SIFTFeatureExtractor:
    """Reusable OpenCV SIFT extractor, with deterministic descriptor ordering.

    ``max_features=0`` leaves OpenCV's number of features unrestricted.
    ``max_image_side`` optionally bounds the longer image dimension before
    extraction; when used, keypoint coordinates refer to the resized image.
    """

    def __init__(
        self,
        *,
        max_features: int = 0,
        n_octave_layers: int = 3,
        contrast_threshold: float = 0.04,
        edge_threshold: float = 10.0,
        sigma: float = 1.6,
        max_image_side: int | None = None,
    ) -> None:
        if type(max_features) is not int or max_features < 0:
            raise ValueError("max_features must be a nonnegative integer")
        if type(n_octave_layers) is not int or n_octave_layers < 1:
            raise ValueError("n_octave_layers must be a positive integer")
        if max_image_side is not None and (
            type(max_image_side) is not int or max_image_side < 1
        ):
            raise ValueError("max_image_side must be a positive integer")
        for name, value in (
            ("contrast_threshold", contrast_threshold),
            ("edge_threshold", edge_threshold),
            ("sigma", sigma),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive number")

        cv2 = _opencv()
        self.max_features = max_features
        self.max_image_side = max_image_side
        self._cv2 = cv2
        self._sift = cv2.SIFT_create(
            nfeatures=max_features,
            nOctaveLayers=n_octave_layers,
            contrastThreshold=float(contrast_threshold),
            edgeThreshold=float(edge_threshold),
            sigma=float(sigma),
        )

    def _grayscale(self, image: str | Path | bytes | bytearray | memoryview | np.ndarray) -> np.ndarray:
        cv2 = self._cv2
        if isinstance(image, (str, Path)):
            path = Path(image)
            if not path.is_file():
                raise FileNotFoundError(path)
            encoded = np.frombuffer(path.read_bytes(), dtype=np.uint8)
            if encoded.size == 0:
                raise ValueError(f"cannot decode image: {path}")
            try:
                gray = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
            except cv2.error as exc:
                raise ValueError(f"cannot decode image: {path}") from exc
            if gray is None:
                raise ValueError(f"cannot decode image: {path}")
        elif isinstance(image, (bytes, bytearray, memoryview)):
            encoded = np.frombuffer(image, dtype=np.uint8)
            if encoded.size == 0:
                raise ValueError("cannot decode image bytes")
            try:
                gray = cv2.imdecode(encoded, cv2.IMREAD_GRAYSCALE)
            except cv2.error as exc:
                raise ValueError("cannot decode image bytes") from exc
            if gray is None:
                raise ValueError("cannot decode image bytes")
        elif isinstance(image, np.ndarray):
            pixels = _uint8_array(image)
            if pixels.ndim == 2:
                gray = pixels
            elif pixels.ndim == 3 and pixels.shape[2] == 1:
                gray = pixels[:, :, 0]
            elif pixels.ndim == 3 and pixels.shape[2] == 3:
                gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
            elif pixels.ndim == 3 and pixels.shape[2] == 4:
                gray = cv2.cvtColor(pixels, cv2.COLOR_BGRA2GRAY)
            else:
                raise ValueError("image must be HxW, HxWx1, HxWx3 or HxWx4")
        else:
            raise TypeError("image must be a filename, encoded bytes or NumPy array")

        if gray.size == 0:
            raise ValueError("image must not be empty")
        return np.ascontiguousarray(gray)

    def extract_with_keypoints(
        self,
        image: str | Path | bytes | bytearray | memoryview | np.ndarray,
        *,
        mask: np.ndarray | None = None,
    ) -> tuple[list[Any], np.ndarray]:
        """Return (OpenCV keypoints, 128-D descriptors) in stable order.

        A mask, when given, must be a 2-D array matching the original image.
        Its nonzero values indicate the region where detection is permitted.
        """
        cv2 = self._cv2
        gray = self._grayscale(image)
        binary_mask = None
        if mask is not None:
            if not isinstance(mask, np.ndarray) or mask.ndim != 2 or mask.shape != gray.shape:
                raise ValueError("mask must be a 2-D array matching image height and width")
            binary_mask = np.ascontiguousarray((mask != 0).astype(np.uint8) * 255)

        if self.max_image_side is not None and max(gray.shape) > self.max_image_side:
            scale = self.max_image_side / max(gray.shape)
            new_size = (
                max(1, round(gray.shape[1] * scale)),
                max(1, round(gray.shape[0] * scale)),
            )
            gray = cv2.resize(gray, new_size, interpolation=cv2.INTER_AREA)
            if binary_mask is not None:
                binary_mask = cv2.resize(binary_mask, new_size, interpolation=cv2.INTER_NEAREST)

        keypoints, descriptors = self._sift.detectAndCompute(gray, binary_mask)
        if descriptors is None or len(keypoints) == 0:
            return [], np.empty((0, DESCRIPTOR_DIMENSION), dtype=np.float32)

        # The histogram / K-Means stages ignore keypoint order, but sorting
        # makes repeated extractions easier to test and compare reproducibly.
        selected = list(range(len(keypoints)))
        if self.max_features and len(selected) > self.max_features:
            # Preserve the strongest detections before imposing presentation
            # order; several orientations can exist at the same location.
            selected.sort(key=lambda i: (-keypoints[i].response, i))
            selected = selected[:self.max_features]
        ordering = sorted(
            selected,
            key=lambda i: (
                keypoints[i].pt[1], keypoints[i].pt[0],
                keypoints[i].size, keypoints[i].angle, -keypoints[i].response, i,
            ),
        )
        result = np.ascontiguousarray(descriptors[ordering], dtype=np.float32)
        if result.ndim != 2 or result.shape[1] != DESCRIPTOR_DIMENSION:
            raise RuntimeError("unexpected OpenCV SIFT descriptor dimensionality")
        if not np.all(np.isfinite(result)):
            raise RuntimeError("SIFT produced nonfinite descriptors")
        return [keypoints[i] for i in ordering], result

    def extract(
        self, image: str | Path | bytes | bytearray | memoryview | np.ndarray,
        *,
        mask: np.ndarray | None = None,
    ) -> np.ndarray:
        """Descriptor-only interface for quantization and ExtractFeatures."""
        return self.extract_with_keypoints(image, mask=mask)[1]


def extract_sift_descriptors(
    image: str | Path | bytes | bytearray | memoryview | np.ndarray,
    **configuration: Any,
) -> np.ndarray:
    """Convenience API for one-off extraction; reuse a class for batches."""
    return SIFTFeatureExtractor(**configuration).extract(image)
