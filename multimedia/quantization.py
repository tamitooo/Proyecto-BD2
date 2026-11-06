"""Reproducible K-Means descriptor quantization (issue #104).

The visual and audio codebooks must be trained independently: SIFT vectors
are 128-D while MFCC vectors have configurable (usually 13) dimensions.
This implementation uses NumPy K-Means++/Lloyd iterations, avoiding the
IVF index's private, scalar Python clustering implementation.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np


def _matrix(descriptors: np.ndarray, dimension: int | None = None) -> np.ndarray:
    matrix = np.asarray(descriptors, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] < 1:
        raise ValueError("descriptors must have shape (N, dimension>0)")
    if dimension is not None and matrix.shape[1] != dimension:
        raise ValueError(f"descriptor dimension must be {dimension}")
    if not np.isfinite(matrix).all():
        raise ValueError("descriptors must be finite")
    return np.ascontiguousarray(matrix)


class KMeansCodebook:
    """Map local descriptors to integer word IDs in ``[0, n_words)``.

    The seeded K-Means++ initialization is restarted ``n_init`` times, and
    the lowest-inertia solution is retained. Distances are computed in chunks
    to avoid an ``N x number_of_words`` allocation on large corpora.
    """

    def __init__(
        self,
        n_words: int,
        *,
        random_state: int = 0,
        n_init: int = 3,
        max_iter: int = 50,
        tol: float = 1e-4,
        batch_size: int = 4096,
    ) -> None:
        for name, value, minimum in (
            ("n_words", n_words, 1),
            ("n_init", n_init, 1),
            ("max_iter", max_iter, 1),
            ("batch_size", batch_size, 1),
        ):
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if type(random_state) is not int or random_state < 0:
            raise ValueError("random_state must be a nonnegative integer")
        if not isinstance(tol, (int, float)) or not math.isfinite(tol) or tol < 0:
            raise ValueError("tol must be finite and nonnegative")
        self.n_words = n_words
        self.random_state = random_state
        self.n_init = n_init
        self.max_iter = max_iter
        self.tol = float(tol)
        self.batch_size = batch_size
        self.centers_: np.ndarray | None = None
        self.inertia_: float | None = None

    @property
    def dimension(self) -> int | None:
        return None if self.centers_ is None else self.centers_.shape[1]

    def _nearest(self, points: np.ndarray, centers: np.ndarray):
        ids = np.empty(points.shape[0], dtype=np.int32)
        minimum = np.empty(points.shape[0], dtype=np.float64)
        norms = np.sum(centers * centers, axis=1)[None, :]
        for begin in range(0, len(points), self.batch_size):
            chunk = points[begin:begin + self.batch_size]
            distances = (
                np.sum(chunk * chunk, axis=1)[:, None]
                + norms - 2.0 * (chunk @ centers.T)
            )
            np.maximum(distances, 0.0, out=distances)
            local = np.argmin(distances, axis=1)
            ids[begin:begin + len(chunk)] = local
            minimum[begin:begin + len(chunk)] = distances[np.arange(len(chunk)), local]
        return ids, minimum

    def _initialize(self, points: np.ndarray, rng: np.random.Generator) -> np.ndarray:
        centers = np.empty((self.n_words, points.shape[1]), dtype=np.float64)
        centers[0] = points[rng.integers(len(points))]
        closest = np.sum((points - centers[0]) ** 2, axis=1)
        for index in range(1, self.n_words):
            total = float(np.sum(closest))
            selected = rng.choice(len(points), p=closest / total) if total > 0 else rng.integers(len(points))
            centers[index] = points[selected]
            new_distances = np.sum((points - centers[index]) ** 2, axis=1)
            np.minimum(closest, new_distances, out=closest)
        return centers

    def fit(self, descriptors: np.ndarray) -> "KMeansCodebook":
        points = _matrix(descriptors)
        if len(points) < self.n_words:
            raise ValueError("at least n_words training descriptors are required")
        rng = np.random.default_rng(self.random_state)
        best_inertia = math.inf
        best_centers = None

        for _ in range(self.n_init):
            centers = self._initialize(points, rng)
            for _ in range(self.max_iter):
                ids, distances = self._nearest(points, centers)
                counts = np.bincount(ids, minlength=self.n_words)
                updated = np.zeros_like(centers)
                np.add.at(updated, ids, points)
                nonempty = counts > 0
                updated[nonempty] /= counts[nonempty, None]
                if not np.all(nonempty):
                    farthest = np.argsort(-distances, kind="stable")
                    empties = np.flatnonzero(~nonempty)
                    for i, cluster in enumerate(empties):
                        updated[cluster] = points[farthest[i % len(farthest)]]
                shift = np.linalg.norm(updated - centers)
                threshold = self.tol * max(1.0, np.linalg.norm(centers))
                centers = updated
                if shift <= threshold:
                    break
            _, distances = self._nearest(points, centers)
            inertia = float(np.sum(distances))
            if inertia < best_inertia:
                best_inertia, best_centers = inertia, centers.copy()

        self.centers_ = np.ascontiguousarray(best_centers, dtype=np.float32)
        self.inertia_ = best_inertia
        return self

    def predict(self, descriptors: np.ndarray) -> np.ndarray:
        if self.centers_ is None:
            raise RuntimeError("codebook must be fitted before prediction")
        points = _matrix(descriptors, self.dimension)
        if len(points) == 0:
            return np.empty((0,), dtype=np.int32)
        return self._nearest(points, self.centers_.astype(np.float64))[0]

    def fit_predict(self, descriptors: np.ndarray) -> np.ndarray:
        return self.fit(descriptors).predict(descriptors)

    def save(self, path: str | Path) -> Path:
        if self.centers_ is None:
            raise RuntimeError("cannot save an unfitted codebook")
        destination = Path(path)
        if destination.exists():
            raise FileExistsError(destination)
        with destination.open("xb") as stream:
            np.savez_compressed(
                stream, centers=self.centers_, n_words=self.n_words,
                random_state=self.random_state,
            )
        return destination

    @classmethod
    def load(cls, path: str | Path) -> "KMeansCodebook":
        with np.load(path, allow_pickle=False) as data:
            centers = _matrix(data["centers"])
            n_words = int(data["n_words"])
            random_state = int(data["random_state"])
        if centers.shape[0] != n_words:
            raise ValueError("invalid saved codebook dimensions")
        model = cls(n_words=n_words, random_state=random_state)
        model.centers_ = np.asarray(centers, dtype=np.float32)
        return model
