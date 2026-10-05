"""R-Tree para datos espaciales 2D (Parte 2 del proyecto).

Sigue la especificación vista en clase (semana 06):

* **Hoja** = ``(MBR, RID)``; **nodo interno** = ``(MBR, puntero a hijo)``; la raíz
  es un nodo interno (o una hoja si el árbol es diminuto).
* Cada nodo tiene entre ``m`` y ``M`` entradas, con ``m = ceil(M/2)``.
* Los MBR de un mismo nivel **pueden solaparse**: el R-Tree no es una partición
  disjunta del espacio.
* **Inserción**: ``ChooseLeaf`` baja eligiendo el hijo con **menor ampliación de
  área** (empate → el de menor área). Si la hoja está llena, ``QuadraticSplit``:
  ``PickSeeds`` elige las dos entradas más alejadas maximizando
  ``area(MBR(E1 ∪ E2)) − area(E1) − area(E2)`` y ``PickNext`` reparte el resto al
  grupo cuya MBR crezca menos. Después ``AdjustTree`` propaga hacia arriba y, si
  la raíz se dividió, se crea una **nueva raíz**.
* **MINDIST** es una **cota inferior** y sirve para **podar**, no para elegir
  semillas (eso lo hace el área / MAXDIST).
* **k-NN**: best-first con un min-heap de ``(MINDIST, nodo)``. La distancia
  **real** se calcula sólo con los puntos de las hojas visitadas; los nodos
  internos se ordenan con MINDIST. Complejidad típica ``O(K log n)``, peor caso
  ``O(n log n)``.

Este módulo **no** sabe de almacenamiento ni de SQL: recibe puntos ``(x, y)`` con
un RID y devuelve RIDs. La integración con el catálogo y el ejecutor está en
``query/catalog.py`` y ``query/query_executor.py``.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

#: Un MBR se representa como ``((x_min, y_min), (x_max, y_max))``, igual que la
#: notación ``((L1..LD), (U1..UD))`` de la clase.
MBR = Tuple[Tuple[float, float], Tuple[float, float]]
Point = Tuple[float, float]


# ----------------------------------------------------------------------
# Geometría de rectángulos
# ----------------------------------------------------------------------

def mbr_of_point(point: Point) -> MBR:
    """MBR degenerado de un punto (sus dos esquinas coinciden)."""
    x, y = point
    return ((x, y), (x, y))


def mbr_union(first: MBR, second: MBR) -> MBR:
    """MBR que contiene a los dos (la unión de los intervalos por eje)."""
    (ax1, ay1), (ax2, ay2) = first
    (bx1, by1), (bx2, by2) = second
    return (
        (min(ax1, bx1), min(ay1, by1)),
        (max(ax2, bx2), max(ay2, by2)),
    )


def mbr_of_mbrs(mbrs: Sequence[MBR]) -> MBR:
    """MBR que cubre una lista de MBR (el del padre)."""
    if not mbrs:
        raise ValueError("mbr_of_mbrs requiere al menos un MBR")
    result = mbrs[0]
    for mbr in mbrs[1:]:
        result = mbr_union(result, mbr)
    return result


def mbr_area(mbr: MBR) -> float:
    """Área del MBR. Un punto (MBR degenerado) tiene área 0."""
    (x1, y1), (x2, y2) = mbr
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def mbr_enlargement(mbr: MBR, point: Point) -> float:
    """Ampliación de área necesaria para incluir ``point`` (Δ de ChooseLeaf)."""
    return mbr_area(mbr_union(mbr, mbr_of_point(point))) - mbr_area(mbr)


def mbr_enlargement_to_include(mbr: MBR, other: MBR) -> float:
    """Ampliación de área necesaria para incluir otro MBR."""
    return mbr_area(mbr_union(mbr, other)) - mbr_area(mbr)


def mbr_contains_point(mbr: MBR, point: Point) -> bool:
    (x1, y1), (x2, y2) = mbr
    x, y = point
    return x1 <= x <= x2 and y1 <= y <= y2


def mbr_intersects(first: MBR, second: MBR) -> bool:
    """True si los dos MBR se solapan (los intervalos se cruzan en los dos ejes)."""
    (ax1, ay1), (ax2, ay2) = first
    (bx1, by1), (bx2, by2) = second
    return not (ax2 < bx1 or bx2 < ax1 or ay2 < by1 or by2 < ay1)


def mindist_point_to_mbr(point: Point, mbr: MBR) -> float:
    """MINDIST de un punto Q a un MBR (fórmula de la clase).

    Por cada dimensión: si Q está dentro del intervalo aporta 0, si está a la
    izquierda ``(Q_i − L_i)²`` y si está a la derecha ``(Q_i − U_i)²``. Es la
    distancia al punto más cercano posible dentro del MBR.
    """
    (x1, y1), (x2, y2) = mbr
    qx, qy = point

    total = 0.0
    if qx < x1:
        total += (qx - x1) ** 2
    elif qx > x2:
        total += (qx - x2) ** 2

    if qy < y1:
        total += (qy - y1) ** 2
    elif qy > y2:
        total += (qy - y2) ** 2

    return math.sqrt(total)


def mindist_mbr_to_mbr(first: MBR, second: MBR) -> float:
    """MINDIST entre dos MBR (la que pide la Práctica 2)."""
    (ax1, ay1), (ax2, ay2) = first
    (bx1, by1), (bx2, by2) = second

    total = 0.0
    if ax1 > bx2:
        total += (ax1 - bx2) ** 2
    elif bx1 > ax2:
        total += (bx1 - ax2) ** 2

    if ay1 > by2:
        total += (ay1 - by2) ** 2
    elif by1 > ay2:
        total += (by1 - ay2) ** 2

    return math.sqrt(total)


def euclidean(first: Point, second: Point) -> float:
    """Distancia euclidiana entre dos puntos."""
    return math.hypot(first[0] - second[0], first[1] - second[1])


# ----------------------------------------------------------------------
# Nodos
# ----------------------------------------------------------------------

@dataclass
class RTreeEntry:
    """Una entrada de un nodo.

    En una **hoja** guarda ``mbr`` (el MBR del objeto) y ``rid``; en un nodo
    **interno** guarda ``mbr`` (que cubre todo el subárbol del hijo) y ``child``.
    """

    mbr: MBR
    rid: Any = None
    child: Optional["RTreeNode"] = None


@dataclass
class RTreeNode:
    is_leaf: bool = True
    entries: List[RTreeEntry] = field(default_factory=list)
    parent: Optional["RTreeNode"] = None

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def mbr(self) -> Optional[MBR]:
        """MBR que cubre todas las entradas del nodo."""
        if not self.entries:
            return None
        return mbr_of_mbrs([entry.mbr for entry in self.entries])


# ----------------------------------------------------------------------
# R-Tree
# ----------------------------------------------------------------------

class RTree:
    """R-Tree con split cuadrático.

    ``max_entries`` es la capacidad ``M`` de cada nodo; el mínimo es
    ``m = ceil(M/2)``, como en la clase.
    """

    def __init__(self, max_entries: int = 8, min_entries: Optional[int] = None):
        if max_entries < 4:
            raise ValueError("max_entries debe ser >= 4")
        self.max_entries = max_entries
        self.min_entries = (
            math.ceil(max_entries / 2) if min_entries is None else min_entries
        )
        if not 1 < self.min_entries <= max_entries // 2 + 1:
            raise ValueError("min_entries fuera de rango")
        self.root = RTreeNode(is_leaf=True)
        self._size = 0

    # ---------------------------------------------------------------- básicos

    def __len__(self) -> int:
        return self._size

    @property
    def height(self) -> int:
        """Altura del árbol (1 = sólo la raíz)."""
        level = 1
        node = self.root
        while not node.is_leaf:
            node = node.entries[0].child
            level += 1
        return level

    def __repr__(self) -> str:
        return (
            f"RTree(entradas={self._size}, M={self.max_entries}, "
            f"altura={self.height})"
        )

    # ------------------------------------------------------------ inserción

    def insert(self, point: Point, rid: Any) -> None:
        """Inserta un punto con su RID (Receta E de la clase)."""
        x, y = float(point[0]), float(point[1])
        entry = RTreeEntry(mbr=mbr_of_point((x, y)), rid=rid)

        # 1) ChooseLeaf: bajar eligiendo la MENOR ampliación de área.
        leaf = self._choose_leaf(entry.mbr)

        # 2) Insertar; si está llena, QuadraticSplit.
        leaf.entries.append(entry)
        split = None
        if len(leaf.entries) > self.max_entries:
            split = self._quadratic_split(leaf)

        # 3) AdjustTree: propagar los MBR hacia arriba.
        self._adjust_tree(leaf, split)
        self._size += 1

    def bulk_load(self, points: Iterable[Tuple[Point, Any]]) -> None:
        """Carga masiva por empaquetado ordenado.

        Insertar uno a uno con ``ChooseLeaf`` es ``O(n log n)`` con mucho
        solapamiento; para 100 000 puntos eso es lento. Aquí se ordenan los
        puntos por una clave que preserva localidad espacial y se **empaquetan**
        los nodos al máximo, construyendo los niveles hacia arriba.

        El reparto de cada nivel no es "bloques de M y el resto al final": eso
        dejaría el último nodo por debajo del mínimo ``m``. Se reparte de forma
        **equilibrada** (cada nodo recibe ``base`` o ``base+1`` hijos), así que
        el árbol resultante respeta las invariantes ``m ≤ entradas ≤ M`` en todos
        los nodos y las hojas quedan a la misma profundidad.
        """
        items = [(float(p[0]), float(p[1]), rid) for p, rid in points]
        if not items:
            return

        self.root = RTreeNode(is_leaf=True)
        self._size = 0

        # Ordenar por celda de una rejilla: barato y conserva localidad espacial.
        side = max(1, int(math.sqrt(len(items))))
        min_x = min(item[0] for item in items)
        max_x = max(item[0] for item in items)
        min_y = min(item[1] for item in items)
        max_y = max(item[1] for item in items)
        span_x = (max_x - min_x) or 1.0
        span_y = (max_y - min_y) or 1.0

        def hilbert_key(item):
            x, y, _ = item
            cell_x = int((x - min_x) / span_x * (side - 1)) if side > 1 else 0
            cell_y = int((y - min_y) / span_y * (side - 1)) if side > 1 else 0
            return (cell_x + cell_y, cell_x, cell_y)

        items.sort(key=hilbert_key)

        # Nivel de hojas: se reparte equilibrado entre los nodos necesarios.
        nodes: List[RTreeNode] = []
        for chunk in self._balanced_chunks(items, self.max_entries):
            node = RTreeNode(is_leaf=True)
            for x, y, rid in chunk:
                node.entries.append(
                    RTreeEntry(mbr=mbr_of_point((x, y)), rid=rid)
                )
                self._size += 1
            nodes.append(node)

        # Niveles internos hacia arriba, también equilibrados.
        while len(nodes) > 1:
            parents: List[RTreeNode] = []
            for chunk in self._balanced_chunks(nodes, self.max_entries):
                parent = RTreeNode(is_leaf=False)
                for child in chunk:
                    child.parent = parent
                    parent.entries.append(
                        RTreeEntry(mbr=child.mbr, child=child)
                    )
                parents.append(parent)
            nodes = parents

        self.root = nodes[0]

    def _balanced_chunks(self, items: List[Any], max_size: int) -> List[List[Any]]:
        """Reparte ``items`` en bloques de tamaño ``base`` o ``base+1``.

        Garantiza que **ningún** bloque quede por debajo de ``m`` (salvo cuando
        hay menos de ``m`` elementos en total, que es el caso de la raíz).
        """
        total = len(items)
        if total <= max_size:
            return [list(items)]

        groups = math.ceil(total / max_size)
        base, resto = divmod(total, groups)
        # Los ``resto`` primeros bloques llevan uno más.
        while base < self.min_entries and groups > 1:
            groups -= 1
            base, resto = divmod(total, groups)

        chunks: List[List[Any]] = []
        start = 0
        for index in range(groups):
            size = base + (1 if index < resto else 0)
            chunks.append(list(items[start:start + size]))
            start += size
        return chunks

    def _choose_leaf(self, mbr: MBR) -> RTreeNode:
        """Baja eligiendo el hijo con menor ampliación de área (Δ)."""
        node = self.root
        while not node.is_leaf:
            best = None
            best_key = None
            for entry in node.entries:
                delta = mbr_enlargement_to_include(entry.mbr, mbr)
                # Empate -> el de menor área.
                key = (delta, mbr_area(entry.mbr))
                if best_key is None or key < best_key:
                    best_key = key
                    best = entry
            node = best.child
        return node

    def _quadratic_split(self, node: RTreeNode) -> RTreeNode:
        """Divide un nodo con ``M+1`` entradas en dos (PickSeeds + PickNext).

        Invariante que se respeta al final: entre los dos nodos resultantes hay
        **exactamente** las mismas entradas que había antes (no se pierde ni se
        duplica ninguna), y cada uno tiene al menos ``m`` entradas.
        """
        entries = list(node.entries)
        group_a, group_b = self._pick_seeds(entries)
        seed_a, seed_b = group_a[0], group_b[0]
        remaining = [
            entry for entry in entries
            if entry is not seed_a and entry is not seed_b
        ]

        def mbr_of(group: List[RTreeEntry]) -> MBR:
            return mbr_of_mbrs([entry.mbr for entry in group])

        while remaining:
            # Regla de capacidad mínima: si a un grupo le faltan entradas para
            # llegar a m y no quedan suficientes para que el otro también las
            # alcance, ese grupo se lleva TODO lo que queda.
            faltan_a = self.min_entries - len(group_a)
            faltan_b = self.min_entries - len(group_b)
            if faltan_a >= len(remaining) or faltan_b >= len(remaining):
                if faltan_a > faltan_b:
                    group_a.extend(remaining)
                elif faltan_b > faltan_a:
                    group_b.extend(remaining)
                else:
                    group_a.extend(remaining)
                remaining = []
                break

            # PickNext: la entrada que más diferencia hay entre asignarla a un
            # grupo o al otro (la que más importa decidir bien).
            best_entry = remaining[0]
            best_difference = None
            for entry in remaining:
                delta_a = mbr_enlargement_to_include(mbr_of(group_a), entry.mbr)
                delta_b = mbr_enlargement_to_include(mbr_of(group_b), entry.mbr)
                difference = abs(delta_a - delta_b)
                if best_difference is None or difference > best_difference:
                    best_difference = difference
                    best_entry = entry

            remaining.remove(best_entry)

            delta_a = mbr_enlargement_to_include(mbr_of(group_a), best_entry.mbr)
            delta_b = mbr_enlargement_to_include(mbr_of(group_b), best_entry.mbr)
            area_a = mbr_area(mbr_of(group_a))
            area_b = mbr_area(mbr_of(group_b))

            # Menor ampliación; empate -> menor área; empate -> menor tamaño.
            if (delta_a, area_a, len(group_a)) <= (delta_b, area_b, len(group_b)):
                group_a.append(best_entry)
            else:
                group_b.append(best_entry)

        assert len(group_a) + len(group_b) == len(entries), (
            "el split perdió entradas: "
            f"{len(group_a)} + {len(group_b)} != {len(entries)}"
        )
        assert group_a and group_b, "el split dejó un grupo vacío"

        # Reutilizamos ``node`` para el grupo A y creamos uno nuevo para el B.
        node.entries = group_a
        new_node = RTreeNode(
            is_leaf=node.is_leaf,
            entries=group_b,
            parent=node.parent,
        )
        for entry in group_b:
            if entry.child is not None:
                entry.child.parent = new_node
        return new_node

    def _pick_seeds(self, entries: List[RTreeEntry]):
        """PickSeeds: el par más "derrochador" si se pusiera en el mismo grupo.

        Maximiza ``area(MBR(E1 ∪ E2)) − area(E1) − area(E2)``.
        """
        best_pair = None
        best_waste = None

        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                first, second = entries[i], entries[j]
                waste = (
                    mbr_area(mbr_union(first.mbr, second.mbr))
                    - mbr_area(first.mbr)
                    - mbr_area(second.mbr)
                )
                if best_waste is None or waste > best_waste:
                    best_waste = waste
                    best_pair = (first, second)

        first, second = best_pair
        return [first], [second]

    def _adjust_tree(
        self,
        node: RTreeNode,
        split: Optional[RTreeNode],
    ) -> None:
        """Propaga los MBR hacia arriba y crea raíz nueva si hizo falta."""
        while node.parent is not None:
            parent = node.parent

            if split is not None:
                parent.entries.append(
                    RTreeEntry(mbr=split.mbr, child=split)
                )
                split.parent = parent

            # El MBR del hijo pudo cambiar: se recalcula el del padre.
            node_mbr = node.mbr
            for entry in parent.entries:
                if entry.child is node and node_mbr is not None:
                    entry.mbr = node_mbr
                    break

            split = None
            if len(parent.entries) > self.max_entries:
                split = self._quadratic_split(parent)

            node = parent

        # La raíz se dividió -> nueva raíz (el árbol crece en altura).
        if split is not None:
            new_root = RTreeNode(is_leaf=False)
            for child in (node, split):
                child.parent = new_root
                new_root.entries.append(RTreeEntry(mbr=child.mbr, child=child))
            self.root = new_root

    # -------------------------------------------------------------- búsqueda

    def search(self, point: Point) -> List[Any]:
        """Búsqueda por igualdad: los RID del punto exacto."""
        x, y = float(point[0]), float(point[1])
        results: List[Any] = []
        for leaf in self._leaves_reaching_point((x, y)):
            for entry in leaf.entries:
                (x1, y1), (x2, y2) = entry.mbr
                if x1 == x == x2 and y1 == y == y2:
                    results.append(entry.rid)
        return results

    def _leaves_reaching_point(self, point: Point) -> Iterator[RTreeNode]:
        stack = [self.root]
        while stack:
            node = stack.pop()
            if node.is_leaf:
                yield node
                continue
            for entry in node.entries:
                if mbr_contains_point(entry.mbr, point):
                    stack.append(entry.child)

    def range_search(
        self,
        mbr: MBR,
        *,
        intersects: bool = True,
    ) -> List[Tuple[Any, MBR]]:
        """Búsqueda por rango: los objetos cuyo MBR **se solapa** con ``mbr``.

        Devuelve ``(rid, mbr_del_objeto)``. La comprobación exacta (p. ej. una
        distancia real menor que el radio, o la intersección con un polígono) la
        hace quien consume el resultado: el índice sólo descarta por MBR, que es
        lo que le corresponde.
        """
        results: List[Tuple[Any, MBR]] = []
        stack = [self.root]

        while stack:
            node = stack.pop()
            for entry in node.entries:
                if not mbr_intersects(entry.mbr, mbr):
                    continue
                if node.is_leaf:
                    results.append((entry.rid, entry.mbr))
                else:
                    stack.append(entry.child)

        return results

    def search_circle(
        self,
        center: Point,
        radius: float,
    ) -> List[Tuple[Any, MBR]]:
        """Búsqueda por rango circular: candidatos dentro del MBR del círculo."""
        x, y = center
        box = ((x - radius, y - radius), (x + radius, y + radius))
        return self.range_search(box)

    def knn(
        self,
        point: Point,
        k: int,
        *,
        distance: Optional[Callable[[Any], float]] = None,
        coordinates: Optional[Callable[[Any], Point]] = None,
    ) -> List[Tuple[Any, float]]:
        """K vecinos más cercanos por best-first search (Receta G de la clase).

        1. min-heap con ``(MINDIST, nodo)``, empezando por la raíz.
        2. Se saca el de menor MINDIST; si ya hay K resultados y ese MINDIST
           supera la K-ésima mejor distancia, se corta (poda global).
        3. En una **hoja** se calcula la distancia **real** a sus puntos y se
           actualiza el top-K; en un **nodo interno** se encolan los hijos con su
           MINDIST.
        4. La distancia real sólo se calcula con los **puntos de las hojas
           visitadas**; los nodos internos se ordenan con MINDIST.

        Complejidad típica ``O(K log n)``; peor caso ``O(n log n)``.

        Parámetros
        ----------
        distance:
            ``f(rid) -> distancia_real``. Se le pasa el RID porque el índice no
            guarda las coordenadas del objeto: quien lo usa (el índice espacial
            del catálogo) sabe resolverlas. Si no se indica, se usa la distancia
            euclidiana contra las coordenadas que devuelva ``coordinates``.
        coordinates:
            ``f(rid) -> (x, y)`` para la métrica por defecto. Si tampoco se
            indica, se usa el centro del MBR de la entrada.

        Devuelve ``[(rid, distancia_real)]`` ordenado de menor a mayor.
        """
        if k <= 0:
            raise ValueError("k debe ser >= 1")

        import heapq

        def default_point(rid, mbr: MBR) -> Point:
            (x1, y1), (x2, y2) = mbr
            return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

        if distance is None:
            if coordinates is None:
                def real_distance(rid, mbr=default_point):
                    raise ValueError("knn requiere 'distance' o 'coordinates'")
            else:
                def real_distance(rid):
                    return euclidean(point, coordinates(rid))
        else:
            real_distance = distance

        heap: List[Tuple[float, int, Any]] = []
        counter = 0
        root_mbr = self.root.mbr
        if root_mbr is not None:
            heapq.heappush(
                heap, (mindist_point_to_mbr(point, root_mbr), counter, self.root)
            )

        best: List[Tuple[float, Any]] = []   # max-heap simulado con negativos
        worst = math.inf

        while heap:
            distance_bound, _, node = heapq.heappop(heap)

            # Poda global: si ya tengo K y la cota supera la peor del top-K, no
            # puede haber nada mejor en el resto de la cola.
            if len(best) >= k and distance_bound > worst:
                break

            if node.is_leaf:
                for entry in node.entries:
                    real = real_distance(entry.rid)
                    # Se ordena por distancia (max-heap con signo negativo).
                    if len(best) < k:
                        heapq.heappush(best, (-real, entry.rid))
                        if len(best) == k:
                            worst = -best[0][0]
                    elif real < worst:
                        heapq.heapreplace(best, (-real, entry.rid))
                        worst = -best[0][0]
            else:
                for entry in node.entries:
                    bound = mindist_point_to_mbr(point, entry.mbr)
                    if len(best) >= k and bound > worst:
                        continue
                    counter += 1
                    heapq.heappush(heap, (bound, counter, entry.child))

        # Interfaz uniforme del proyecto: (rid, distancia), ordenado ascendente.
        results = [(rid, -neg) for neg, rid in best]
        results.sort(key=lambda item: item[1])
        return results

    # ------------------------------------------------------------ utilitarios

    def scan(self) -> Iterator[Tuple[Any, MBR]]:
        """Recorre todas las entradas de las hojas en orden de árbol."""
        stack = [self.root]
        while stack:
            node = stack.pop()
            if node.is_leaf:
                for entry in node.entries:
                    yield entry.rid, entry.mbr
            else:
                for entry in node.entries:
                    stack.append(entry.child)

    def validate(self) -> bool:
        """Comprueba las invariantes del R-Tree. Lanza ``AssertionError`` si falla.

        * La raíz es hoja o tiene >= 2 hijos.
        * Todo nodo no raíz tiene entre ``m`` y ``M`` entradas.
        * El MBR del padre contiene los MBR de sus hijos (a menos de redondeo).
        * Todas las hojas están a la misma profundidad.
        * El MBR de cada nodo interno cubre a sus hijos.
        """
        if len(self.root) == 0:
            return True

        if not self.root.is_leaf:
            assert len(self.root.entries) >= 2, "la raíz interna necesita >= 2 hijos"

        leaf_depths = set()

        def visit(node: RTreeNode, depth: int) -> None:
            if node is not self.root:
                assert len(node.entries) >= self.min_entries, (
                    f"nodo con {len(node.entries)} entradas < m={self.min_entries}"
                )
            assert len(node.entries) <= self.max_entries, (
                f"nodo con {len(node.entries)} entradas > M={self.max_entries}"
            )

            if node.is_leaf:
                leaf_depths.add(depth)
                return

            for entry in node.entries:
                assert entry.child is not None, "nodo interno sin hijo"
                child_mbr = entry.child.mbr
                assert child_mbr is not None, "hijo sin MBR"
                assert mbr_intersects(entry.mbr, child_mbr), (
                    "el MBR del padre no cubre al hijo"
                )
                # El MBR del padre debe CONTENER al del hijo.
                (px1, py1), (px2, py2) = entry.mbr
                (cx1, cy1), (cx2, cy2) = child_mbr
                assert px1 <= cx1 + 1e-9 and py1 <= cy1 + 1e-9, (
                    "el MBR del padre no contiene al hijo (esquina inferior)"
                )
                assert px2 >= cx2 - 1e-9 and py2 >= cy2 - 1e-9, (
                    "el MBR del padre no contiene al hijo (esquina superior)"
                )
                assert entry.child.parent is node, "puntero de padre inconsistente"
                visit(entry.child, depth + 1)

        visit(self.root, 1)
        assert len(leaf_depths) == 1, (
            f"las hojas no están a la misma profundidad: {sorted(leaf_depths)}"
        )

        size = sum(1 for _ in self.scan())
        assert size == self._size, f"tamaño inconsistente: {size} != {self._size}"
        return True

    def stats(self) -> Dict[str, Any]:
        """Estadísticas del índice, para el informe y el benchmark."""
        nodes = 0
        leaves = 0
        entries_internal = 0
        entries_leaf = 0
        occupancy: List[int] = []

        stack = [self.root]
        while stack:
            node = stack.pop()
            nodes += 1
            occupancy.append(len(node.entries))
            if node.is_leaf:
                leaves += 1
                entries_leaf += len(node.entries)
            else:
                entries_internal += len(node.entries)
                for entry in node.entries:
                    stack.append(entry.child)

        return {
            "entries": self._size,
            "max_entries": self.max_entries,
            "min_entries": self.min_entries,
            "height": self.height,
            "nodes": nodes,
            "leaves": leaves,
            "internal_entries": entries_internal,
            "leaf_entries": entries_leaf,
            "avg_occupancy": (
                sum(occupancy) / len(occupancy) if occupancy else 0.0
            ),
            "fill_factor": (
                entries_leaf / (leaves * self.max_entries)
                if leaves
                else 0.0
            ),
        }
