"""Índice IVF (Inverted File Index) para vectores multimedia (Parte 4)."""

from __future__ import annotations

import heapq
import math
import operator
import random
from itertools import repeat
from pathlib import Path
from typing import Dict, Hashable, Iterable, List, Optional, Sequence, Tuple

from indexes.persistence import atomic_pickle_write, pickle_read, remove_if_exists

from .metrics import get_search_metric
from .ranking import SearchResult, SimilarityRanking

Vector = Tuple[float, ...]


class IVFIndex:
    def __init__(
        self,
        *,
        n_lists: int,
        metric_name: str = "euclidean",
        max_iterations: int = 25,
        training_points_per_list: int = 256,
        n_probe: Optional[int] = None,
        random_seed: Optional[int] = None,
    ) -> None:
        if n_lists < 1:
            raise ValueError("n_lists debe ser >= 1")
        if max_iterations < 1:
            raise ValueError("max_iterations debe ser >= 1")
        if training_points_per_list < 1:
            raise ValueError("training_points_per_list debe ser >= 1")
        if n_probe is not None and n_probe < 1:
            raise ValueError("n_probe debe ser >= 1")

        self.n_lists = int(n_lists)
        self.metric_name = SimilarityRanking(metric_name).metric
        self.max_iterations = int(max_iterations)
        self.training_points_per_list = int(training_points_per_list)
        self.n_probe = (
            math.ceil(math.sqrt(self.n_lists)) if n_probe is None else int(n_probe)
        )

        self.centroids: List[Vector] = []
        self.lists: List[Dict[Hashable, Vector]] = []
        self.dimension: Optional[int] = None
        self.file_path: Optional[str] = None

        self._assignments: Dict[Hashable, int] = {}
        self._rng = random.Random(random_seed)
        self.random_seed = random_seed

    def __len__(self) -> int:
        return len(self._assignments)

    @property
    def is_trained(self) -> bool:
        return bool(self.centroids)


    def train(self, vectors: Iterable[Iterable[float]]) -> None:
        """Calcula los centroides con K-Means a partir de una muestra."""
        if self._assignments:
            raise ValueError("no se puede reentrenar un índice con vectores")

        points = [self._as_vector(vector) for vector in vectors]
        if len(points) < self.n_lists:
            raise ValueError(
                f"se necesitan al menos {self.n_lists} vectores para entrenar, "
                f"recibidos {len(points)}"
            )
        dimensions = {len(point) for point in points}
        if len(dimensions) != 1:
            raise ValueError("todos los vectores deben tener la misma dimensión")

        limit = self.n_lists * self.training_points_per_list
        if len(points) > limit:
            points = self._rng.sample(points, limit)
        if self.metric_name == "cosine":
            points = [self._unit_vector(point) for point in points]

        self.centroids = self._kmeans(points)
        self.lists = [{} for _ in self.centroids]
        self.dimension = dimensions.pop()
        self.persist()

    def _kmeans(self, points: Sequence[Vector]) -> List[Vector]:
        """Lloyd con K-Means++; con vectores unitarios Euclidiana ordena igual que coseno y es más barata."""
        centroids = self._initial_centroids(points)
        assignments: Optional[List[int]] = None

        for _ in range(self.max_iterations):
            updated = [self._nearest(point, centroids) for point in points]
            if updated == assignments:
                break
            assignments = updated

            clusters: List[List[Vector]] = [[] for _ in centroids]
            for point, list_id in zip(points, assignments):
                clusters[list_id].append(point)
            largest = max(clusters, key=len)
            centroids = [
                self._centroid(cluster)
                if cluster
                # Celda vacía: se reubica dentro de la más poblada.
                else self._rng.choice(largest)
                for cluster in clusters
            ]
        return centroids

    def _initial_centroids(self, points: Sequence[Vector]) -> List[Vector]:
        """K-Means++: favorece centroides iniciales separados entre sí."""
        first = self._rng.choice(points)
        centroids = [first]
        weights = [math.dist(point, first) ** 2 for point in points]

        while len(centroids) < self.n_lists:
            if sum(weights) > 0.0:
                centroid = self._rng.choices(points, weights=weights)[0]
            else:
                centroid = self._rng.choice(points)
            centroids.append(centroid)
            weights = [
                min(weight, math.dist(point, centroid) ** 2)
                for point, weight in zip(points, weights)
            ]
        return centroids

    @staticmethod
    def _nearest(point: Vector, centroids: Sequence[Vector]) -> int:
        """Índice del centroide más cercano; los empates van al primero."""
        costs = list(map(math.dist, repeat(point), centroids))
        return costs.index(min(costs))

    @staticmethod
    def _most_similar(point: Vector, centroids: Sequence[Vector]) -> int:
        """Centroide de mayor producto punto; los empates van al primero."""
        scores = [sum(map(operator.mul, point, centroid)) for centroid in centroids]
        return scores.index(max(scores))

    def _centroid(self, cluster: Sequence[Vector]) -> Vector:
        mean = tuple(math.fsum(values) / len(cluster) for values in zip(*cluster))
        return self._unit_vector(mean) if self.metric_name == "cosine" else mean

    @staticmethod
    def _unit_vector(vector: Vector) -> Vector:
        norm = math.hypot(*vector)
        return vector if norm == 0.0 else tuple(value / norm for value in vector)


    def assign(self, vector: Iterable[float]) -> int:
        """Devuelve la lista invertida que corresponde a ``vector``."""
        if not self.is_trained:
            raise ValueError("el índice debe entrenarse antes de usarse")
        query = self._as_query(vector)
        if self.metric_name == "euclidean":
            return self._nearest(query, self.centroids)
        if self.metric_name == "cosine":
            query = self._unit_vector(query)
        return self._most_similar(query, self.centroids)

    def insert(self, vector_id: Hashable, vector: Iterable[float]) -> int:
        """Reescribe el archivo completo; para carga masiva usar ``build``."""
        list_id = self._insert(vector_id, vector)
        self.persist()
        return list_id

    def build(self, items: Iterable[Tuple[Hashable, Iterable[float]]]) -> None:
        """Entrena con ``items`` y los inserta todos (construcción masiva)."""
        pairs = [(vector_id, self._as_vector(vector)) for vector_id, vector in items]
        # Antes de entrenar, para no dejar un índice construido a medias.
        if len({vector_id for vector_id, _ in pairs}) != len(pairs):
            raise ValueError("vector_id duplicado en la construcción")
        self.train(vector for _, vector in pairs)
        for vector_id, vector in pairs:
            self._insert(vector_id, vector)
        self.persist()

    def _insert(self, vector_id: Hashable, vector: Iterable[float]) -> int:
        if vector_id in self._assignments:
            raise ValueError(f"vector_id duplicado: {vector_id!r}")
        values = self._as_vector(vector)
        list_id = self.assign(values)
        self.lists[list_id][vector_id] = values
        self._assignments[vector_id] = list_id
        return list_id

    @staticmethod
    def _as_vector(vector: Iterable[float]) -> Vector:
        values = tuple(float(value) for value in vector)
        if not values:
            raise ValueError("vector no puede estar vacío")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("el vector debe contener solo valores finitos")
        return values

    def _as_query(self, vector: Iterable[float]) -> Vector:
        values = self._as_vector(vector)
        if len(values) != self.dimension:
            raise ValueError(
                f"dimensión inválida: esperada {self.dimension}, recibida {len(values)}"
            )
        return values


    def knn(
        self,
        query_vector: Iterable[float],
        *,
        k: int = 10,
        n_probe: Optional[int] = None,
    ) -> List[Tuple[Hashable, float]]:
        """k vecinos aproximados revisando las ``n_probe`` listas más cercanas (menor = mejor)."""
        if k <= 0 or not self._assignments:
            return []

        effective_probe = self.n_probe if n_probe is None else int(n_probe)
        if effective_probe < 1:
            raise ValueError("n_probe debe ser >= 1")

        query = self._as_query(query_vector)
        cost = get_search_metric(self.metric_name)
        probe_order = sorted(
            (list_id for list_id, items in enumerate(self.lists) if items),
            key=lambda list_id: (cost(query, self.centroids[list_id]), list_id),
        )

        candidates: List[Tuple[Hashable, float]] = []
        for position, list_id in enumerate(probe_order):
            if position >= effective_probe and len(candidates) >= k:
                break
            candidates.extend(
                (vector_id, cost(query, vector))
                for vector_id, vector in self.lists[list_id].items()
            )
        return self._best(candidates, k)

    def search_similar(
        self,
        query_vector: Iterable[float],
        *,
        k: int = 10,
        n_probe: Optional[int] = None,
    ) -> List[SearchResult]:
        """Retorna resultados con un ``score`` uniforme (mayor = mejor)."""
        raw = self.knn(query_vector, k=k, n_probe=n_probe)
        return SimilarityRanking(self.metric_name).rank(raw, k=k)

    def brute_force_knn(
        self, query_vector: Iterable[float], *, k: int = 10
    ) -> List[Tuple[Hashable, float]]:
        """Búsqueda exacta, referencia para medir Recall@k."""
        if k <= 0 or not self._assignments:
            return []
        query = self._as_query(query_vector)
        cost = get_search_metric(self.metric_name)
        return self._best(
            [
                (vector_id, cost(query, vector))
                for inverted_list in self.lists
                for vector_id, vector in inverted_list.items()
            ],
            k,
        )

    @staticmethod
    def _best(
        candidates: Iterable[Tuple[Hashable, float]], k: int
    ) -> List[Tuple[Hashable, float]]:
        """Top-k por costo; ``repr`` hace deterministas los empates."""
        return heapq.nsmallest(k, candidates, key=lambda item: (item[1], repr(item[0])))


    def attach_file(self, file_path, load_existing: bool = True) -> bool:
        self.file_path = str(file_path)
        if load_existing and Path(self.file_path).exists():
            self.load()
            return True
        return False

    def persist(self) -> None:
        if not self.file_path:
            return
        atomic_pickle_write(
            self.file_path,
            {
                "kind": "ivf",
                "n_lists": self.n_lists,
                "metric_name": self.metric_name,
                "max_iterations": self.max_iterations,
                "training_points_per_list": self.training_points_per_list,
                "n_probe": self.n_probe,
                "dimension": self.dimension,
                "centroids": self.centroids,
                "lists": self.lists,
            },
        )

    def load(self) -> "IVFIndex":
        state = pickle_read(self.file_path)
        if state.get("kind") != "ivf":
            raise ValueError("archivo IVF incompatible")
        self.n_lists = int(state["n_lists"])
        self.metric_name = state["metric_name"]
        self.max_iterations = int(state["max_iterations"])
        self.training_points_per_list = int(state["training_points_per_list"])
        self.n_probe = int(state["n_probe"])
        self.dimension = state["dimension"]
        self.centroids = state["centroids"]
        self.lists = state["lists"]
        self._assignments = {
            vector_id: list_id
            for list_id, inverted_list in enumerate(self.lists)
            for vector_id in inverted_list
        }
        self.validate()
        return self

    def drop_persistent_file(self) -> None:
        remove_if_exists(self.file_path)

    def serialized_size_bytes(self) -> int:
        if self.file_path and Path(self.file_path).exists():
            return Path(self.file_path).stat().st_size
        return 0


    def validate(self) -> bool:
        """Comprueba invariantes estructurales del índice."""
        if not self.is_trained:
            if self.lists or self._assignments or self.dimension is not None:
                raise AssertionError("índice sin entrenar no debe tener contenido")
            return True

        if len(self.centroids) != self.n_lists or len(self.lists) != self.n_lists:
            raise AssertionError("debe existir un centroide y una lista por celda")
        if any(len(centroid) != self.dimension for centroid in self.centroids):
            raise AssertionError("centroide con dimensión inconsistente")

        stored = sum(len(inverted_list) for inverted_list in self.lists)
        if stored != len(self._assignments):
            raise AssertionError("vector_id repetido o ausente en las listas")
        for list_id, inverted_list in enumerate(self.lists):
            for vector_id, vector in inverted_list.items():
                if self._assignments.get(vector_id) != list_id:
                    raise AssertionError(f"asignación inconsistente: {vector_id!r}")
                if len(vector) != self.dimension:
                    raise AssertionError(f"dimensión inconsistente: {vector_id!r}")
        return True

    def stats(self) -> dict:
        """Resumen pequeño útil para tests, demos y futura instrumentación."""
        sizes = [len(inverted_list) for inverted_list in self.lists]
        return {
            "vectors": len(self),
            "dimension": self.dimension,
            "n_lists": self.n_lists,
            "n_probe": self.n_probe,
            "metric": self.metric_name,
            "is_trained": self.is_trained,
            "non_empty_lists": sum(1 for size in sizes if size),
            "largest_list": max(sizes, default=0),
        }
