"""Bag of Visual/Audio Words con TF-IDF para la Parte 4 (sección 2.4.1).

La pipeline que implementa este módulo es la del enunciado:

1. un extractor de descriptores locales produce una matriz ``(n, d)``
   (SIFT de 128 dimensiones para imágenes, MFCC de 20 para audio);
2. K-Means agrupa una muestra de descriptores del corpus en ``K`` centroides
   (las "palabras" visuales/auditivas);
3. cada descriptor se asigna a su centroide más cercano y se construye un
   histograma de ``K`` palabras;
4. el histograma se pondera con TF-IDF usando las frecuencias de documento del
   corpus y se normaliza en L2.

El vocabulario (centroides) y el IDF son **compartidos**: se entrenan una vez
sobre una muestra del corpus, se guardan en disco y se reutilizan al indexar y
al consultar. Si se entrenaran por objeto, los vectores de dos imágenes no
estarían en el mismo espacio y el coseno no tendría sentido.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import numpy as np

MODEL_VERSION = 1
MODEL_TEMPLATE = "bow_{kind}.npz"


class BowError(ValueError):
    """Error de entrenamiento, codificación o carga del vocabulario."""


def model_path(model_root, kind: str) -> Path:
    """Ruta estándar del vocabulario de una modalidad."""
    return Path(model_root) / MODEL_TEMPLATE.format(kind=kind)


def _as_matrix(values, *, name: str = "descriptores") -> np.ndarray:
    matrix = np.asarray(values, dtype=np.float64)
    if matrix.ndim != 2:
        raise BowError(f"{name} debe ser una matriz 2-D (n, d)")
    if matrix.shape[1] == 0:
        raise BowError(f"{name} no puede tener dimensión 0")
    return matrix


def _squared_distances(points: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    """Distancias euclidianas al cuadrado con la identidad ||x-c||²."""
    point_norms = np.einsum("ij,ij->i", points, points)
    centroid_norms = np.einsum("ij,ij->i", centroids, centroids)
    distances = (
        point_norms[:, None]
        + centroid_norms[None, :]
        - 2.0 * (points @ centroids.T)
    )
    return np.maximum(distances, 0.0)


def assign_labels(
    descriptors: np.ndarray,
    centroids: np.ndarray,
    *,
    chunk_size: int = 4096,
) -> np.ndarray:
    """Índice del centroide más cercano para cada descriptor."""
    points = _as_matrix(descriptors)
    centers = _as_matrix(centroids, name="centroides")
    if points.shape[1] != centers.shape[1]:
        raise BowError(
            f"descriptores de dimensión {points.shape[1]} y centroides de "
            f"dimensión {centers.shape[1]}"
        )
    labels = np.empty(points.shape[0], dtype=np.int32)
    for start in range(0, points.shape[0], chunk_size):
        end = min(start + chunk_size, points.shape[0])
        labels[start:end] = _squared_distances(
            points[start:end], centers
        ).argmin(axis=1)
    return labels


def _kmeans_plus_plus(
    points: np.ndarray, n_clusters: int, rng: np.random.Generator
) -> np.ndarray:
    """Inicialización K-Means++ (Arthur y Vassilvitskii, 2007)."""
    n = points.shape[0]
    first = int(rng.integers(n))
    centers = [points[first]]
    closest = _squared_distances(points, points[first : first + 1])[:, 0]

    for _ in range(1, n_clusters):
        total = float(closest.sum())
        if total <= 0.0:
            index = int(rng.integers(n))
        else:
            probabilities = closest / total
            index = int(rng.choice(n, p=probabilities))
        centers.append(points[index])
        new_distances = _squared_distances(
            points, points[index : index + 1]
        )[:, 0]
        closest = np.minimum(closest, new_distances)
    return np.vstack(centers)


def kmeans(
    descriptors: np.ndarray,
    n_clusters: int,
    *,
    max_iter: int = 25,
    seed: Optional[int] = 0,
) -> Tuple[np.ndarray, np.ndarray]:
    """K-Means de Lloyd con inicialización K-Means++.

    Devuelve ``(centroides, etiquetas)``. Si un cluster queda vacío se
    reinicializa con un descriptor aleatorio, igual que en una implementación
    de producción.
    """
    points = _as_matrix(descriptors)
    if n_clusters < 1:
        raise BowError("n_clusters debe ser >= 1")
    if points.shape[0] < n_clusters:
        raise BowError(
            f"se necesitan al menos {n_clusters} descriptores para K-Means; "
            f"hay {points.shape[0]}"
        )

    rng = np.random.default_rng(seed)
    centroids = _kmeans_plus_plus(points, n_clusters, rng)
    labels = np.full(points.shape[0], -1, dtype=np.int32)

    for _ in range(max_iter):
        new_labels = assign_labels(points, centroids)
        if np.array_equal(labels, new_labels):
            labels = new_labels
            break
        labels = new_labels
        for cluster in range(n_clusters):
            members = points[labels == cluster]
            if members.shape[0] > 0:
                centroids[cluster] = members.mean(axis=0)
            else:
                centroids[cluster] = points[int(rng.integers(points.shape[0]))]

    return centroids, labels


@dataclass
class FeatureModel:
    """Vocabulario + IDF compartidos por indexación y consulta."""

    kind: str
    n_words: int
    descriptor_dim: int
    centroids: np.ndarray
    idf: np.ndarray
    descriptor_mean: np.ndarray
    descriptor_std: np.ndarray
    n_documents: int = 0
    standardize: bool = False
    descriptor_backend: Optional[str] = None
    version: int = MODEL_VERSION

    def __post_init__(self) -> None:
        self.kind = str(self.kind)
        self.n_words = int(self.n_words)
        self.descriptor_dim = int(self.descriptor_dim)
        self.centroids = _as_matrix(self.centroids, name="centroides")
        self.idf = np.asarray(self.idf, dtype=np.float64).reshape(-1)
        self.descriptor_mean = np.asarray(
            self.descriptor_mean, dtype=np.float64
        ).reshape(-1)
        self.descriptor_std = np.asarray(
            self.descriptor_std, dtype=np.float64
        ).reshape(-1)
        self.n_documents = int(self.n_documents)
        if self.centroids.shape != (self.n_words, self.descriptor_dim):
            raise BowError(
                f"centroides con forma {self.centroids.shape}; se esperaba "
                f"({self.n_words}, {self.descriptor_dim})"
            )
        if self.idf.shape != (self.n_words,):
            raise BowError("idf debe tener una entrada por palabra")
        if self.descriptor_mean.shape != (self.descriptor_dim,):
            raise BowError("descriptor_mean debe tener dimensión d")
        if self.descriptor_std.shape != (self.descriptor_dim,):
            raise BowError("descriptor_std debe tener dimensión d")

    @property
    def vector_dim(self) -> int:
        return self.n_words

    def _prepare(self, descriptors) -> np.ndarray:
        matrix = np.asarray(descriptors, dtype=np.float64)
        if matrix.size == 0:
            return np.empty((0, self.descriptor_dim), dtype=np.float64)
        matrix = _as_matrix(matrix)
        if matrix.shape[1] != self.descriptor_dim:
            raise BowError(
                f"descriptores de dimensión {matrix.shape[1]}; el vocabulario "
                f"espera {self.descriptor_dim}"
            )
        if self.standardize:
            std = np.where(self.descriptor_std > 1e-9, self.descriptor_std, 1.0)
            matrix = (matrix - self.descriptor_mean) / std
        return matrix

    def histogram(self, descriptors) -> np.ndarray:
        """Conteo de cada palabra para un objeto."""
        matrix = self._prepare(descriptors)
        if matrix.shape[0] == 0:
            return np.zeros(self.n_words, dtype=np.float64)
        labels = assign_labels(matrix, self.centroids)
        return np.bincount(labels, minlength=self.n_words).astype(np.float64)

    def assign(self, descriptors) -> np.ndarray:
        """Etiqueta de palabra para cada descriptor."""
        matrix = self._prepare(descriptors)
        if matrix.shape[0] == 0:
            return np.empty(0, dtype=np.int32)
        return assign_labels(matrix, self.centroids)

    def encode(self, descriptors) -> np.ndarray:
        """Vector TF-IDF de dimensión K, normalizado en L2."""
        counts = self.histogram(descriptors)
        total = float(counts.sum())
        if total <= 0.0:
            return np.zeros(self.n_words, dtype=np.float64)
        tf = counts / total
        weighted = tf * self.idf
        norm = float(np.linalg.norm(weighted))
        if norm > 0.0:
            weighted = weighted / norm
        return weighted

    def save(self, path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            target,
            version=np.asarray([self.version], dtype=np.int32),
            kind=np.asarray([self.kind]),
            n_words=np.asarray([self.n_words], dtype=np.int32),
            descriptor_dim=np.asarray([self.descriptor_dim], dtype=np.int32),
            centroids=self.centroids,
            idf=self.idf,
            descriptor_mean=self.descriptor_mean,
            descriptor_std=self.descriptor_std,
            n_documents=np.asarray([self.n_documents], dtype=np.int64),
            standardize=np.asarray([bool(self.standardize)]),
            descriptor_backend=np.asarray([self.descriptor_backend or ""]),
        )

    @classmethod
    def load(cls, path) -> "FeatureModel":
        source = Path(path)
        if not source.is_file():
            raise BowError(f"no existe el vocabulario: {source}")
        with np.load(source, allow_pickle=False) as data:
            backend = None
            if "descriptor_backend" in data:
                backend = str(data["descriptor_backend"][0]) or None
            return cls(
                kind=str(data["kind"][0]),
                n_words=int(data["n_words"][0]),
                descriptor_dim=int(data["descriptor_dim"][0]),
                centroids=data["centroids"],
                idf=data["idf"],
                descriptor_mean=data["descriptor_mean"],
                descriptor_std=data["descriptor_std"],
                n_documents=int(data["n_documents"][0]),
                standardize=bool(data["standardize"][0]),
                descriptor_backend=backend,
                version=int(data["version"][0]),
            )


def train_model(
    kind: str,
    documents: Iterable[np.ndarray],
    n_words: int,
    *,
    standardize: Optional[bool] = None,
    max_descriptors: int = 20000,
    max_iter: int = 25,
    seed: Optional[int] = 0,
    descriptor_backend: Optional[str] = None,
) -> FeatureModel:
    """Entrena vocabulario e IDF a partir de un corpus de descriptores.

    ``documents`` es un iterable de matrices ``(n_i, d)``: una por imagen o
    audio. Se usa una muestra acotada de descriptores para K-Means (el
    vocabulario no mejora mucho con más puntos y el costo crece linealmente),
    pero el IDF se calcula con todos los documentos recibidos.
    """
    cleaned: List[np.ndarray] = []
    descriptor_dim: Optional[int] = None
    for document in documents:
        matrix = np.asarray(document, dtype=np.float64)
        if matrix.size == 0:
            continue
        matrix = _as_matrix(matrix)
        if descriptor_dim is None:
            descriptor_dim = matrix.shape[1]
        elif matrix.shape[1] != descriptor_dim:
            raise BowError(
                f"todos los documentos deben tener descriptores de dimensión "
                f"{descriptor_dim}; llegó {matrix.shape[1]}"
            )
        # Un descriptor todo-cero no aporta una palabra útil (por ejemplo, una
        # imagen sin gradientes). Se descarta para no contaminar K-Means.
        norms = np.linalg.norm(matrix, axis=1)
        matrix = matrix[norms > 1e-9]
        if matrix.shape[0] > 0:
            cleaned.append(matrix)

    if not cleaned or descriptor_dim is None:
        raise BowError(
            "no hay descriptores para entrenar el vocabulario; revisa que las "
            "imágenes tengan textura o que los audios no sean silencio"
        )

    all_descriptors = np.vstack(cleaned)
    if all_descriptors.shape[0] < 2:
        raise BowError("se necesitan al menos 2 descriptores para entrenar")

    requested_words = int(n_words)
    n_words = max(1, min(requested_words, all_descriptors.shape[0]))
    rng = np.random.default_rng(seed)
    if all_descriptors.shape[0] > max_descriptors:
        indices = rng.choice(
            all_descriptors.shape[0], size=max_descriptors, replace=False
        )
        sample = all_descriptors[indices]
    else:
        sample = all_descriptors

    if standardize is None:
        standardize = kind == "audio"
    if standardize:
        mean = sample.mean(axis=0)
        std = sample.std(axis=0)
        std = np.where(std > 1e-9, std, 1.0)
    else:
        mean = np.zeros(descriptor_dim, dtype=np.float64)
        std = np.ones(descriptor_dim, dtype=np.float64)

    sample_normalized = (sample - mean) / std
    centroids, _ = kmeans(
        sample_normalized, n_words, max_iter=max_iter, seed=seed
    )

    model = FeatureModel(
        kind=kind,
        n_words=n_words,
        descriptor_dim=descriptor_dim,
        centroids=centroids,
        idf=np.ones(n_words, dtype=np.float64),
        descriptor_mean=mean,
        descriptor_std=std,
        n_documents=len(cleaned),
        standardize=bool(standardize),
        descriptor_backend=descriptor_backend,
    )

    document_frequency = np.zeros(n_words, dtype=np.float64)
    for document in cleaned:
        labels = model.assign(document)
        counts = np.bincount(labels, minlength=n_words)
        document_frequency += (counts > 0).astype(np.float64)

    # IDF suavizado: evita división por cero para palabras que no aparecen.
    model.idf = np.log(
        (1.0 + len(cleaned)) / (1.0 + document_frequency)
    ) + 1.0
    return model


__all__ = [
    "BowError",
    "FeatureModel",
    "assign_labels",
    "kmeans",
    "model_path",
    "train_model",
]
