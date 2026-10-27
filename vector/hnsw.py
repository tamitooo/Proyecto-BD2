"""Estructura base de HNSW (Hierarchical Navigable Small World).

Este módulo corresponde al issue #113 y define únicamente la infraestructura
jerárquica que usarán los issues posteriores:

* nodos vectoriales con vecinos separados por nivel;
* parámetros M, ef_construction y ef_search;
* entry point y nivel máximo global;
* generación probabilística y reproducible de niveles;
* validación de invariantes estructurales.

La inserción navegable/conexión de vecinos corresponde al issue #114; la
búsqueda k-NN pública se completa en el #115. Mantener esa separación hace que cada issue sea
pequeño, testeable y fácil de integrar.
"""

from __future__ import annotations

import heapq
import itertools
import math
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, Hashable, Iterable, Optional, Sequence, Set, Tuple

Vector = Tuple[float, ...]
Metric = Callable[[Sequence[float], Sequence[float]], float]


@dataclass
class HNSWNode:
    """Nodo del grafo HNSW.

    ``level`` indica el nivel superior en el que participa. Todo nodo participa
    desde nivel 0 hasta ``level``. ``neighbors`` mantiene un conjunto de IDs por
    nivel; los enlaces reales se crearán durante la inserción del issue #114.
    """

    vector_id: Hashable
    vector: Vector
    level: int
    neighbors: Dict[int, Set[Hashable]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.level < 0:
            raise ValueError("level debe ser >= 0")
        self.vector = tuple(float(value) for value in self.vector)
        if not self.vector:
            raise ValueError("vector no puede estar vacío")
        # Todo nivel del nodo existe aunque todavía no tenga vecinos.
        for current in range(self.level + 1):
            self.neighbors.setdefault(current, set())

    def neighbors_at(self, level: int) -> Set[Hashable]:
        """Devuelve el conjunto mutable de vecinos del nivel indicado."""
        if level < 0 or level > self.level:
            raise ValueError(
                f"el nodo {self.vector_id!r} no participa en el nivel {level}"
            )
        return self.neighbors[level]


class HNSWIndex:
    """Contenedor estructural de un índice HNSW.

    Parameters
    ----------
    M:
        Máximo de conexiones objetivo por nodo/nivel. La política exacta de
        poda se añadirá en el issue #114.
    ef_construction:
        Tamaño de la lista dinámica de candidatos durante construcción.
    ef_search:
        Tamaño por defecto de la lista dinámica de candidatos durante búsqueda.
    random_seed:
        Semilla para que la asignación de niveles sea reproducible en tests.
    level_multiplier:
        Factor de la distribución exponencial usada para elegir niveles. Si se
        omite se usa ``1 / log(M)``, convención habitual en HNSW.
    metric:
        Función de distancia/similitud compartida. El issue #113 no la ejecuta;
        se almacena para que #114/#115 puedan consumir la interfaz común de
        métricas sin acoplar HNSW a Euclidiana.
    """

    def __init__(
        self,
        *,
        M: int = 16,
        ef_construction: int = 100,
        ef_search: int = 50,
        random_seed: Optional[int] = None,
        level_multiplier: Optional[float] = None,
        metric: Optional[Metric] = None,
    ) -> None:
        if M < 2:
            raise ValueError("M debe ser >= 2")
        if ef_construction < 1:
            raise ValueError("ef_construction debe ser >= 1")
        if ef_search < 1:
            raise ValueError("ef_search debe ser >= 1")

        multiplier = (
            1.0 / math.log(M) if level_multiplier is None else float(level_multiplier)
        )
        if not math.isfinite(multiplier) or multiplier <= 0:
            raise ValueError("level_multiplier debe ser finito y > 0")

        self.M = int(M)
        self.ef_construction = int(ef_construction)
        self.ef_search = int(ef_search)
        self.level_multiplier = multiplier
        self.metric = metric

        self.nodes: Dict[Hashable, HNSWNode] = {}
        self.entry_point: Optional[Hashable] = None
        self.max_level: int = -1
        self.dimension: Optional[int] = None

        self._rng = random.Random(random_seed)
        self.random_seed = random_seed
        self._heap_counter = itertools.count()

    def __len__(self) -> int:
        return len(self.nodes)

    @property
    def is_empty(self) -> bool:
        return not self.nodes

    def random_level(self) -> int:
        """Genera un nivel con distribución exponencial.

        ``U`` se toma en ``(0, 1]`` y se calcula
        ``floor(-ln(U) * level_multiplier)``. La mayoría de nodos queda en
        nivel 0 y cada nivel superior contiene progresivamente menos nodos.
        """
        # random() puede devolver exactamente 0.0; se evita log(0).
        u = max(self._rng.random(), float.fromhex("0x1.0p-1022"))
        return int(math.floor(-math.log(u) * self.level_multiplier))

    def make_node(
        self,
        vector_id: Hashable,
        vector: Iterable[float],
        *,
        level: Optional[int] = None,
    ) -> HNSWNode:
        """Construye un nodo validado pero **no lo inserta en el grafo**.

        Es deliberadamente una operación estructural. La inserción HNSW real
        (navegación, selección de vecinos y enlaces bidireccionales) pertenece
        al issue #114.
        """
        values = tuple(float(value) for value in vector)
        if not values:
            raise ValueError("vector no puede estar vacío")
        if self.dimension is not None and len(values) != self.dimension:
            raise ValueError(
                f"dimensión inválida: esperada {self.dimension}, recibida {len(values)}"
            )
        node_level = self.random_level() if level is None else int(level)
        return HNSWNode(vector_id=vector_id, vector=values, level=node_level)

    def _register_structural_node(self, node: HNSWNode) -> None:
        """Registra un nodo sin crear enlaces; helper interno para #114/tests."""
        if node.vector_id in self.nodes:
            raise ValueError(f"vector_id duplicado: {node.vector_id!r}")
        if self.dimension is None:
            self.dimension = len(node.vector)
        elif len(node.vector) != self.dimension:
            raise ValueError(
                f"dimensión inválida: esperada {self.dimension}, recibida {len(node.vector)}"
            )

        self.nodes[node.vector_id] = node
        if self.entry_point is None or node.level > self.max_level:
            self.entry_point = node.vector_id
            self.max_level = node.level

    # ---------------------------------------------------------- issue #114

    @staticmethod
    def _euclidean(first: Sequence[float], second: Sequence[float]) -> float:
        return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(first, second)))

    def _distance(self, first: Sequence[float], second: Sequence[float]) -> float:
        """Distancia usada por construcción/navegación.

        Persona B podrá inyectar una métrica común mediante ``metric``. Mientras
        esa capa todavía no exista, Euclidiana es el fallback determinista.
        El contrato de HNSW en esta etapa es "menor valor = más cercano".
        """
        if len(first) != len(second):
            raise ValueError("los vectores deben tener la misma dimensión")
        fn = self.metric or self._euclidean
        value = float(fn(first, second))
        if not math.isfinite(value):
            raise ValueError("la métrica debe devolver un valor finito")
        return value

    def _greedy_search_level(
        self,
        query: Sequence[float],
        entry_id: Hashable,
        level: int,
    ) -> Hashable:
        """Navega greedy en una capa hasta alcanzar un mínimo local."""
        current_id = entry_id
        current = self.nodes[current_id]
        if current.level < level:
            raise ValueError("entry point no participa en el nivel solicitado")
        current_distance = self._distance(query, current.vector)

        improved = True
        while improved:
            improved = False
            # ``repr`` hace deterministas los empates incluso con IDs de tipos
            # que Python no puede comparar directamente entre sí.
            neighbors = sorted(current.neighbors[level], key=repr)
            for neighbor_id in neighbors:
                neighbor = self.nodes[neighbor_id]
                distance = self._distance(query, neighbor.vector)
                if (distance, repr(neighbor_id)) < (
                    current_distance,
                    repr(current_id),
                ):
                    current_id = neighbor_id
                    current = neighbor
                    current_distance = distance
                    improved = True
                    break
        return current_id

    def _search_layer(
        self,
        query: Sequence[float],
        entry_ids: Iterable[Hashable],
        ef: int,
        level: int,
    ) -> list[Hashable]:
        """Best-first local usado durante construcción de una capa HNSW."""
        if ef < 1:
            raise ValueError("ef debe ser >= 1")

        visited: Set[Hashable] = set()
        candidates = []  # min-heap por distancia
        best = []        # max-heap simulado con distancia negativa

        for node_id in entry_ids:
            if node_id in visited:
                continue
            node = self.nodes[node_id]
            if node.level < level:
                continue
            visited.add(node_id)
            distance = self._distance(query, node.vector)
            order = next(self._heap_counter)
            heapq.heappush(candidates, (distance, order, node_id))
            heapq.heappush(best, (-distance, -order, node_id))

        if not candidates:
            return []

        while candidates:
            candidate_distance, _, candidate_id = heapq.heappop(candidates)
            worst_best = -best[0][0]
            if len(best) >= ef and candidate_distance > worst_best:
                break

            node = self.nodes[candidate_id]
            for neighbor_id in sorted(node.neighbors[level], key=repr):
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                neighbor = self.nodes[neighbor_id]
                distance = self._distance(query, neighbor.vector)
                worst_best = -best[0][0]
                if len(best) < ef or distance < worst_best:
                    order = next(self._heap_counter)
                    heapq.heappush(candidates, (distance, order, neighbor_id))
                    heapq.heappush(best, (-distance, -order, neighbor_id))
                    if len(best) > ef:
                        heapq.heappop(best)

        result = [item[2] for item in best]
        result.sort(
            key=lambda node_id: (
                self._distance(query, self.nodes[node_id].vector),
                repr(node_id),
            )
        )
        return result

    def _prune_node(self, node_id: Hashable, level: int) -> None:
        """Conserva los M vecinos más próximos y elimina enlaces recíprocos."""
        node = self.nodes[node_id]
        neighbors = node.neighbors[level]
        if len(neighbors) <= self.M:
            return

        ordered = sorted(
            neighbors,
            key=lambda other_id: (
                self._distance(node.vector, self.nodes[other_id].vector),
                repr(other_id),
            ),
        )
        keep = set(ordered[: self.M])
        removed = set(neighbors) - keep
        node.neighbors[level] = keep

        for other_id in removed:
            other = self.nodes.get(other_id)
            if other is not None and other.level >= level:
                other.neighbors[level].discard(node_id)

    def _connect_bidirectional(
        self,
        first_id: Hashable,
        second_id: Hashable,
        level: int,
    ) -> None:
        if first_id == second_id:
            return
        first = self.nodes[first_id]
        second = self.nodes[second_id]
        if first.level < level or second.level < level:
            raise ValueError("ambos nodos deben participar en el nivel del enlace")
        first.neighbors[level].add(second_id)
        second.neighbors[level].add(first_id)

    def insert(
        self,
        vector_id: Hashable,
        vector: Iterable[float],
        *,
        level: Optional[int] = None,
    ) -> HNSWNode:
        """Inserta un vector siguiendo el flujo de construcción HNSW.

        El parámetro ``level`` existe para pruebas reproducibles; en uso normal
        se omite y se obtiene mediante la distribución probabilística definida
        en :meth:`random_level`.
        """
        if vector_id in self.nodes:
            raise ValueError(f"vector_id duplicado: {vector_id!r}")

        node = self.make_node(vector_id, vector, level=level)

        # Primer vector: no hay navegación ni vecinos.
        if not self.nodes:
            self._register_structural_node(node)
            return node

        old_entry = self.entry_point
        old_max_level = self.max_level
        assert old_entry is not None

        # Se registra primero para que las rutinas de conexión puedan resolver
        # el ID, pero se conserva el entry point previo durante la navegación.
        self._register_structural_node(node)
        self.entry_point = old_entry
        self.max_level = old_max_level

        entry_id = old_entry

        # 1) Desde las capas que el nuevo nodo no alcanza, descenso greedy.
        for current_level in range(old_max_level, node.level, -1):
            entry_id = self._greedy_search_level(
                node.vector, entry_id, current_level
            )

        # 2) En cada capa compartida buscar candidatos con ef_construction,
        # escoger los M más próximos y crear conexiones recíprocas.
        top_shared = min(node.level, old_max_level)
        for current_level in range(top_shared, -1, -1):
            candidates = self._search_layer(
                node.vector,
                [entry_id],
                self.ef_construction,
                current_level,
            )
            candidates = [cid for cid in candidates if cid != vector_id]
            selected = candidates[: self.M]

            for neighbor_id in selected:
                self._connect_bidirectional(
                    vector_id, neighbor_id, current_level
                )

            # La conexión del nuevo nodo puede llevar a un vecino existente por
            # encima de M. Podarlo puede eliminar también el enlace recíproco.
            for neighbor_id in list(selected):
                self._prune_node(neighbor_id, current_level)
            self._prune_node(vector_id, current_level)

            if candidates:
                entry_id = candidates[0]

        # 3) Un nodo que alcanza una capa nueva se vuelve entry point.
        if node.level > old_max_level:
            self.entry_point = vector_id
            self.max_level = node.level
        else:
            self.entry_point = old_entry
            self.max_level = old_max_level

        return node

    def validate(self) -> bool:
        """Comprueba invariantes estructurales del grafo.

        La validación es intencionalmente estricta para detectar corrupciones
        antes de implementar la inserción y la búsqueda.
        """
        if not self.nodes:
            if self.entry_point is not None or self.max_level != -1:
                raise AssertionError(
                    "índice vacío debe tener entry_point=None y max_level=-1"
                )
            if self.dimension is not None:
                raise AssertionError("índice vacío debe tener dimension=None")
            return True

        if self.entry_point not in self.nodes:
            raise AssertionError("entry_point debe referenciar un nodo existente")

        dimensions = {len(node.vector) for node in self.nodes.values()}
        if len(dimensions) != 1:
            raise AssertionError("todos los vectores deben tener la misma dimensión")
        actual_dimension = next(iter(dimensions))
        if self.dimension != actual_dimension:
            raise AssertionError("dimension global inconsistente")

        actual_max = max(node.level for node in self.nodes.values())
        if self.max_level != actual_max:
            raise AssertionError("max_level no coincide con el nivel máximo de los nodos")
        if self.nodes[self.entry_point].level != self.max_level:
            raise AssertionError("entry_point debe pertenecer al nivel máximo")

        for node_id, node in self.nodes.items():
            expected_levels = set(range(node.level + 1))
            if set(node.neighbors) != expected_levels:
                raise AssertionError(
                    f"niveles de vecinos inconsistentes en nodo {node_id!r}"
                )
            for level, neighbors in node.neighbors.items():
                if len(neighbors) > self.M:
                    raise AssertionError(
                        f"nodo {node_id!r} excede M={self.M} vecinos en nivel {level}"
                    )
                if node_id in neighbors:
                    raise AssertionError("un nodo no puede ser vecino de sí mismo")
                for neighbor_id in neighbors:
                    neighbor = self.nodes.get(neighbor_id)
                    if neighbor is None:
                        raise AssertionError(
                            f"vecino inexistente {neighbor_id!r} desde {node_id!r}"
                        )
                    if neighbor.level < level:
                        raise AssertionError(
                            f"vecino {neighbor_id!r} no participa en nivel {level}"
                        )
                    # HNSW usa enlaces bidireccionales en cada capa.
                    if node_id not in neighbor.neighbors[level]:
                        raise AssertionError(
                            f"enlace no recíproco {node_id!r}<->{neighbor_id!r} "
                            f"en nivel {level}"
                        )
        return True

    def stats(self) -> dict:
        """Resumen pequeño útil para tests, demos y futura instrumentación."""
        level_counts: Dict[int, int] = {}
        for node in self.nodes.values():
            for level in range(node.level + 1):
                level_counts[level] = level_counts.get(level, 0) + 1
        return {
            "nodes": len(self.nodes),
            "dimension": self.dimension,
            "entry_point": self.entry_point,
            "max_level": self.max_level,
            "M": self.M,
            "ef_construction": self.ef_construction,
            "ef_search": self.ef_search,
            "level_counts": level_counts,
        }
