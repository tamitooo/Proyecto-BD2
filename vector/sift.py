"""SIFT con backend OpenCV opcional y fallback denso propio.

Si ``opencv-python-headless`` está instalado se usa ``cv2.SIFT_create()``, que
es el SIFT estándar (DoG + keypoints). Si no, se implementa el descriptor SIFT
clásico sobre una rejilla densa de keypoints:

* se construye una pirámide de escalas (1, 1/2, 1/4) para conservar la
  invariancia de escala;
* en cada keypoint se calcula la orientación dominante con un histograma de
  gradientes de 36 bins;
* el parche se muestrea rotado según esa orientación;
* se divide en 4x4 celdas con 8 orientaciones por celda (128 dimensiones);
* el descriptor se normaliza en L2, se recorta a 0.2 y se vuelve a normalizar,
  igual que en SIFT (Lowe, 2004).

Es un SIFT denso: no se hace la detección de extremos DoG de OpenCV, pero el
descriptor local y la invariancia de escala/orientación son los de SIFT. Esto
da un número predecible de descriptores y funciona bien con el vocabulario
visual del enunciado.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

SIFT_DESCRIPTOR_DIM = 128
SIFT_PATCH = 16
SIFT_CELLS = 4
SIFT_ORIENTATIONS = 8
SIFT_SCALES = (1.0, 0.5, 0.25)
SIFT_STEP = 8
SIFT_MAX_KEYPOINTS = 1500


def _resize_gray(image: np.ndarray, height: int, width: int) -> np.ndarray:
    """Redimensiona una imagen grayscale float [0,1] con Pillow."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise RuntimeError("SIFT requiere Pillow") from exc

    source = Image.fromarray(np.clip(image * 255.0, 0, 255).astype(np.uint8))
    resampling = getattr(Image, "Resampling", Image)
    resized = source.resize((width, height), resampling.LANCZOS)
    return np.asarray(resized, dtype=np.float64) / 255.0


def _bilinear(image: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Interpolación bilineal vectorizada sobre coordenadas flotantes."""
    height, width = image.shape
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    x1 = x0 + 1
    y1 = y0 + 1
    dx = x - x0
    dy = y - y0

    x0c = np.clip(x0, 0, width - 1)
    x1c = np.clip(x1, 0, width - 1)
    y0c = np.clip(y0, 0, height - 1)
    y1c = np.clip(y1, 0, height - 1)

    top = image[y0c, x0c] * (1.0 - dx) + image[y0c, x1c] * dx
    bottom = image[y1c, x0c] * (1.0 - dx) + image[y1c, x1c] * dx
    return top * (1.0 - dy) + bottom * dy


def _gradients(patch: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Gradientes centrales; los bordes quedan en cero."""
    gx = np.zeros_like(patch)
    gy = np.zeros_like(patch)
    gx[:, 1:-1] = patch[:, 2:] - patch[:, :-2]
    gy[1:-1, :] = patch[2:, :] - patch[:-2, :]
    return gx, gy


def _descriptor_at(
    image: np.ndarray,
    keypoint_y: int,
    keypoint_x: int,
    *,
    window: np.ndarray,
    relative_y: np.ndarray,
    relative_x: np.ndarray,
) -> Optional[np.ndarray]:
    """Descriptor SIFT de 128 dimensiones para un keypoint (o None)."""
    half = SIFT_PATCH // 2
    patch = image[
        keypoint_y - half : keypoint_y + half,
        keypoint_x - half : keypoint_x + half,
    ]
    if patch.shape != (SIFT_PATCH, SIFT_PATCH):
        return None

    gx, gy = _gradients(patch)
    magnitude = np.hypot(gx, gy)
    if float((magnitude * window).sum()) <= 1e-9:
        return None

    angles = np.arctan2(gy, gx)
    orientation_bins = (
        (angles + np.pi) / (2.0 * np.pi) * 36.0
    ).astype(np.int64) % 36
    orientation_histogram = np.bincount(
        orientation_bins.ravel(),
        weights=(magnitude * window).ravel(),
        minlength=36,
    )
    peak = int(orientation_histogram.argmax())
    if orientation_histogram[peak] <= 1e-9:
        return None
    dominant = (peak + 0.5) * (2.0 * np.pi / 36.0) - np.pi

    # Muestrear el parche rotado según la orientación dominante.
    cosine, sine = np.cos(dominant), np.sin(dominant)
    sample_x = keypoint_x + cosine * relative_x - sine * relative_y
    sample_y = keypoint_y + sine * relative_x + cosine * relative_y
    rotated = _bilinear(image, sample_x, sample_y)

    gx, gy = _gradients(rotated)
    magnitude = np.hypot(gx, gy)
    angles = np.arctan2(gy, gx)
    bins = (
        (angles + np.pi) / (2.0 * np.pi) * SIFT_ORIENTATIONS
    ).astype(np.int64) % SIFT_ORIENTATIONS

    cell_index = (
        (np.arange(SIFT_PATCH)[:, None] // (SIFT_PATCH // SIFT_CELLS)) * SIFT_CELLS
        + (np.arange(SIFT_PATCH)[None, :] // (SIFT_PATCH // SIFT_CELLS))
    )
    indices = cell_index * SIFT_ORIENTATIONS + bins
    descriptor = np.bincount(
        indices.ravel(),
        weights=(magnitude * window).ravel(),
        minlength=SIFT_DESCRIPTOR_DIM,
    ).astype(np.float64)

    norm = float(np.linalg.norm(descriptor))
    if norm <= 1e-12:
        return None
    descriptor /= norm
    descriptor = np.minimum(descriptor, 0.2)
    norm = float(np.linalg.norm(descriptor))
    if norm <= 1e-12:
        return None
    descriptor /= norm
    return descriptor


def dense_sift_descriptors(
    image: np.ndarray,
    *,
    step: int = SIFT_STEP,
    max_keypoints: int = SIFT_MAX_KEYPOINTS,
) -> np.ndarray:
    """Descriptores SIFT densos de una imagen grayscale float [0,1]."""
    gray = np.asarray(image, dtype=np.float64)
    if gray.ndim != 2:
        raise ValueError("SIFT espera una imagen grayscale 2-D")
    if gray.size == 0:
        return np.empty((0, SIFT_DESCRIPTOR_DIM), dtype=np.float64)

    height, width = gray.shape
    if height < SIFT_PATCH + 2 or width < SIFT_PATCH + 2:
        return np.empty((0, SIFT_DESCRIPTOR_DIM), dtype=np.float64)

    half = SIFT_PATCH // 2
    levels: List[Tuple[float, np.ndarray]] = []
    for scale in SIFT_SCALES:
        level_h = int(round(height * scale))
        level_w = int(round(width * scale))
        if level_h < SIFT_PATCH + 2 or level_w < SIFT_PATCH + 2:
            continue
        if scale == 1.0:
            levels.append((scale, gray))
        else:
            levels.append((scale, _resize_gray(gray, level_h, level_w)))

    positions: List[Tuple[np.ndarray, int, int]] = []
    for _, level in levels:
        level_h, level_w = level.shape
        for y in range(half, level_h - half, max(1, step)):
            for x in range(half, level_w - half, max(1, step)):
                positions.append((level, y, x))
    if not positions:
        return np.empty((0, SIFT_DESCRIPTOR_DIM), dtype=np.float64)
    if len(positions) > max_keypoints:
        chosen = np.linspace(0, len(positions) - 1, max_keypoints).astype(int)
        positions = [positions[index] for index in chosen]

    window = np.exp(
        -(
            (np.arange(SIFT_PATCH) - (SIFT_PATCH - 1) / 2.0)[:, None] ** 2
            + (np.arange(SIFT_PATCH) - (SIFT_PATCH - 1) / 2.0)[None, :] ** 2
        )
        / (2.0 * (SIFT_PATCH / 4.0) ** 2)
    )
    relative = np.arange(SIFT_PATCH) - (SIFT_PATCH - 1) / 2.0
    relative_y, relative_x = np.meshgrid(relative, relative, indexing="ij")

    descriptors: List[np.ndarray] = []
    for level, y, x in positions:
        descriptor = _descriptor_at(
            level,
            y,
            x,
            window=window,
            relative_y=relative_y,
            relative_x=relative_x,
        )
        if descriptor is not None:
            descriptors.append(descriptor)

    if not descriptors:
        return np.empty((0, SIFT_DESCRIPTOR_DIM), dtype=np.float64)
    return np.vstack(descriptors)


def _decode_grayscale(data: bytes) -> np.ndarray:
    """Decodifica una imagen como uint8 gris, acotada a 512 px de lado."""
    try:
        import io

        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("SIFT requiere Pillow") from exc

    with Image.open(io.BytesIO(data)) as image:
        grayscale = image.convert("L")
        if max(grayscale.size) > 512:
            ratio = 512.0 / max(grayscale.size)
            grayscale = grayscale.resize(
                (
                    max(1, int(round(grayscale.size[0] * ratio))),
                    max(1, int(round(grayscale.size[1] * ratio))),
                ),
                getattr(Image, "Resampling", Image).LANCZOS,
            )
        return np.asarray(grayscale, dtype=np.uint8)


def sift_backend() -> str:
    """Backend SIFT disponible: ``opencv`` si está instalado, si no ``dense``.

    El vocabulario debe entrenarse y consultarse con el **mismo** backend: los
    descriptores de OpenCV y los densos no comparten exactamente el mismo
    espacio.
    """
    try:
        import cv2  # type: ignore
    except ImportError:
        return "dense"
    return "opencv" if hasattr(cv2, "SIFT_create") else "dense"


def _normalize_sift_rows(descriptors: np.ndarray) -> np.ndarray:
    """Normalización SIFT: L2, recorte a 0.2 y L2 otra vez."""
    matrix = np.asarray(descriptors, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != SIFT_DESCRIPTOR_DIM:
        return np.empty((0, SIFT_DESCRIPTOR_DIM), dtype=np.float64)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)
    matrix = np.minimum(matrix, 0.2)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    matrix = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)
    return matrix


def _opencv_sift_descriptors(data: bytes) -> Optional[np.ndarray]:
    """SIFT estándar de OpenCV si ``cv2`` y ``SIFT_create`` están disponibles."""
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    if not hasattr(cv2, "SIFT_create"):
        return None
    try:
        gray = _decode_grayscale(data)
        keypoints, descriptors = cv2.SIFT_create().detectAndCompute(gray, None)
    except Exception:
        return None
    if descriptors is None or len(descriptors) == 0:
        return np.empty((0, SIFT_DESCRIPTOR_DIM), dtype=np.float64)
    return _normalize_sift_rows(descriptors)


def sift_descriptors_from_bytes(data: bytes) -> np.ndarray:
    """SIFT de una imagen: OpenCV si está instalado, si no SIFT denso propio."""
    if sift_backend() == "opencv":
        descriptors = _opencv_sift_descriptors(data)
        if descriptors is not None:
            return descriptors
    gray = _decode_grayscale(data).astype(np.float64) / 255.0
    return dense_sift_descriptors(gray)


__all__ = [
    "SIFT_DESCRIPTOR_DIM",
    "dense_sift_descriptors",
    "sift_backend",
    "sift_descriptors_from_bytes",
]


__all__ = [
    "SIFT_DESCRIPTOR_DIM",
    "dense_sift_descriptors",
    "sift_descriptors_from_bytes",
]
