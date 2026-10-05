"""R-Tree 2D con split cuadrático, range search y k-NN por MINDIST."""

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

MBR = Tuple[Tuple[float, float], Tuple[float, float]]
Point = Tuple[float, float]


def mbr_of_point(point: Point) -> MBR:
    x, y = point
    return ((x, y), (x, y))


def mbr_union(first: MBR, second: MBR) -> MBR:
    (ax1, ay1), (ax2, ay2) = first
    (bx1, by1), (bx2, by2) = second
    return ((min(ax1, bx1), min(ay1, by1)), (max(ax2, bx2), max(ay2, by2)))


def mbr_of_mbrs(mbrs: Sequence[MBR]) -> MBR:
    if not mbrs:
        raise ValueError("mbr_of_mbrs requiere al menos un MBR")
    result = mbrs[0]
    for mbr in mbrs[1:]:
        result = mbr_union(result, mbr)
    return result


def mbr_area(mbr: MBR) -> float:
    (x1, y1), (x2, y2) = mbr
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def mbr_enlargement(mbr: MBR, point: Point) -> float:
    return mbr_area(mbr_union(mbr, mbr_of_point(point))) - mbr_area(mbr)


def mbr_enlargement_to_include(mbr: MBR, other: MBR) -> float:
    return mbr_area(mbr_union(mbr, other)) - mbr_area(mbr)


def mbr_contains_point(mbr: MBR, point: Point) -> bool:
    (x1, y1), (x2, y2) = mbr
    x, y = point
    return x1 <= x <= x2 and y1 <= y <= y2


def mbr_intersects(first: MBR, second: MBR) -> bool:
    (ax1, ay1), (ax2, ay2) = first
    (bx1, by1), (bx2, by2) = second
    return not (ax2 < bx1 or bx2 < ax1 or ay2 < by1 or by2 < ay1)


def mindist_point_to_mbr(point: Point, mbr: MBR) -> float:
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
    return math.hypot(first[0] - second[0], first[1] - second[1])


@dataclass
class RTreeEntry:
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
        if not self.entries:
            return None
        return mbr_of_mbrs([entry.mbr for entry in self.entries])


class RTree:
    def __init__(self, max_entries: int = 8, min_entries: Optional[int] = None):
        if max_entries < 4:
            raise ValueError("max_entries debe ser >= 4")
        self.max_entries = max_entries
        self.min_entries = math.ceil(max_entries / 2) if min_entries is None else min_entries
        if not 1 < self.min_entries <= max_entries // 2 + 1:
            raise ValueError("min_entries fuera de rango")
        self.root = RTreeNode(is_leaf=True)
        self._size = 0

    def __len__(self) -> int:
        return self._size

    @property
    def height(self) -> int:
        level, node = 1, self.root
        while not node.is_leaf:
            node = node.entries[0].child
            level += 1
        return level

    def __repr__(self) -> str:
        return f"RTree(entradas={self._size}, M={self.max_entries}, altura={self.height})"

    def insert(self, point: Point, rid: Any) -> None:
        entry = RTreeEntry(mbr=mbr_of_point((float(point[0]), float(point[1]))), rid=rid)
        leaf = self._choose_leaf(entry.mbr)
        leaf.entries.append(entry)
        split = self._quadratic_split(leaf) if len(leaf.entries) > self.max_entries else None
        self._adjust_tree(leaf, split)
        self._size += 1

    def bulk_load(self, points: Iterable[Tuple[Point, Any]]) -> None:
        items = [(float(p[0]), float(p[1]), rid) for p, rid in points]
        self.root = RTreeNode(is_leaf=True)
        self._size = 0
        if not items:
            return
        side = max(1, int(math.sqrt(len(items))))
        min_x, max_x = min(i[0] for i in items), max(i[0] for i in items)
        min_y, max_y = min(i[1] for i in items), max(i[1] for i in items)
        span_x, span_y = (max_x - min_x) or 1.0, (max_y - min_y) or 1.0

        def locality_key(item):
            x, y, _ = item
            cx = int((x - min_x) / span_x * (side - 1)) if side > 1 else 0
            cy = int((y - min_y) / span_y * (side - 1)) if side > 1 else 0
            return (cx + cy, cx, cy)

        items.sort(key=locality_key)
        nodes: List[RTreeNode] = []
        for chunk in self._balanced_chunks(items, self.max_entries):
            node = RTreeNode(is_leaf=True)
            for x, y, rid in chunk:
                node.entries.append(RTreeEntry(mbr=mbr_of_point((x, y)), rid=rid))
                self._size += 1
            nodes.append(node)
        while len(nodes) > 1:
            parents: List[RTreeNode] = []
            for chunk in self._balanced_chunks(nodes, self.max_entries):
                parent = RTreeNode(is_leaf=False)
                for child in chunk:
                    child.parent = parent
                    parent.entries.append(RTreeEntry(mbr=child.mbr, child=child))
                parents.append(parent)
            nodes = parents
        self.root = nodes[0]

    def _balanced_chunks(self, items: List[Any], max_size: int) -> List[List[Any]]:
        total = len(items)
        if total <= max_size:
            return [list(items)]
        groups = math.ceil(total / max_size)
        base, rest = divmod(total, groups)
        while base < self.min_entries and groups > 1:
            groups -= 1
            base, rest = divmod(total, groups)
        chunks, start = [], 0
        for index in range(groups):
            size = base + (1 if index < rest else 0)
            chunks.append(list(items[start:start + size]))
            start += size
        return chunks

    def _choose_leaf(self, mbr: MBR) -> RTreeNode:
        node = self.root
        while not node.is_leaf:
            best = min(
                node.entries,
                key=lambda e: (mbr_enlargement_to_include(e.mbr, mbr), mbr_area(e.mbr)),
            )
            node = best.child
        return node

    def _quadratic_split(self, node: RTreeNode) -> RTreeNode:
        entries = list(node.entries)
        group_a, group_b = self._pick_seeds(entries)
        seed_a, seed_b = group_a[0], group_b[0]
        remaining = [e for e in entries if e is not seed_a and e is not seed_b]

        def group_mbr(group):
            return mbr_of_mbrs([e.mbr for e in group])

        while remaining:
            if len(group_a) + len(remaining) == self.min_entries:
                group_a.extend(remaining); remaining = []; break
            if len(group_b) + len(remaining) == self.min_entries:
                group_b.extend(remaining); remaining = []; break
            best_entry = max(
                remaining,
                key=lambda e: abs(
                    mbr_enlargement_to_include(group_mbr(group_a), e.mbr)
                    - mbr_enlargement_to_include(group_mbr(group_b), e.mbr)
                ),
            )
            remaining.remove(best_entry)
            da = mbr_enlargement_to_include(group_mbr(group_a), best_entry.mbr)
            db = mbr_enlargement_to_include(group_mbr(group_b), best_entry.mbr)
            aa, ab = mbr_area(group_mbr(group_a)), mbr_area(group_mbr(group_b))
            if (da, aa, len(group_a)) <= (db, ab, len(group_b)):
                group_a.append(best_entry)
            else:
                group_b.append(best_entry)

        node.entries = group_a
        new_node = RTreeNode(is_leaf=node.is_leaf, entries=group_b, parent=node.parent)
        for entry in node.entries:
            if entry.child is not None:
                entry.child.parent = node
        for entry in new_node.entries:
            if entry.child is not None:
                entry.child.parent = new_node
        return new_node

    def _pick_seeds(self, entries: List[RTreeEntry]):
        best_pair, best_waste = None, None
        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                first, second = entries[i], entries[j]
                waste = mbr_area(mbr_union(first.mbr, second.mbr)) - mbr_area(first.mbr) - mbr_area(second.mbr)
                if best_waste is None or waste > best_waste:
                    best_waste, best_pair = waste, (first, second)
        first, second = best_pair
        return [first], [second]

    def _adjust_tree(self, node: RTreeNode, split: Optional[RTreeNode]) -> None:
        while node.parent is not None:
            parent = node.parent
            if split is not None:
                parent.entries.append(RTreeEntry(mbr=split.mbr, child=split))
                split.parent = parent
            node_mbr = node.mbr
            for entry in parent.entries:
                if entry.child is node and node_mbr is not None:
                    entry.mbr = node_mbr
                    break
            split = self._quadratic_split(parent) if len(parent.entries) > self.max_entries else None
            node = parent
        if split is not None:
            new_root = RTreeNode(is_leaf=False)
            for child in (node, split):
                child.parent = new_root
                new_root.entries.append(RTreeEntry(mbr=child.mbr, child=child))
            self.root = new_root

    def search(self, point: Point) -> List[Any]:
        x, y = float(point[0]), float(point[1])
        results = []
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

    def range_search(self, mbr: MBR, *, intersects: bool = True) -> List[Tuple[Any, MBR]]:
        results, stack = [], [self.root]
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

    def search_circle(self, center: Point, radius: float) -> List[Tuple[Any, MBR]]:
        x, y = center
        return self.range_search(((x - radius, y - radius), (x + radius, y + radius)))

    def knn(
        self,
        point: Point,
        k: int,
        *,
        distance: Optional[Callable[[Any], float]] = None,
        coordinates: Optional[Callable[[Any], Point]] = None,
    ) -> List[Tuple[Any, float]]:
        if k <= 0:
            raise ValueError("k debe ser >= 1")
        import heapq
        if distance is None:
            if coordinates is None:
                raise ValueError("knn requiere 'distance' o 'coordinates'")
            real_distance = lambda rid: euclidean(point, coordinates(rid))
        else:
            real_distance = distance

        heap: List[Tuple[float, int, Any]] = []
        counter = 0
        if self.root.mbr is not None:
            heapq.heappush(heap, (mindist_point_to_mbr(point, self.root.mbr), counter, self.root))
        best: List[Tuple[float, Any]] = []
        worst = math.inf
        while heap:
            bound, _, node = heapq.heappop(heap)
            if len(best) >= k and bound > worst:
                break
            if node.is_leaf:
                for entry in node.entries:
                    real = real_distance(entry.rid)
                    if len(best) < k:
                        heapq.heappush(best, (-real, entry.rid))
                        if len(best) == k:
                            worst = -best[0][0]
                    elif real < worst:
                        heapq.heapreplace(best, (-real, entry.rid))
                        worst = -best[0][0]
            else:
                for entry in node.entries:
                    child_bound = mindist_point_to_mbr(point, entry.mbr)
                    if len(best) >= k and child_bound > worst:
                        continue
                    counter += 1
                    heapq.heappush(heap, (child_bound, counter, entry.child))
        results = [(rid, -neg) for neg, rid in best]
        results.sort(key=lambda item: item[1])
        return results

    def scan(self) -> Iterator[Tuple[Any, MBR]]:
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
        if len(self.root) == 0:
            return True
        if not self.root.is_leaf:
            assert len(self.root.entries) >= 2
        leaf_depths = set()

        def visit(node: RTreeNode, depth: int):
            if node is not self.root:
                assert len(node.entries) >= self.min_entries
            assert len(node.entries) <= self.max_entries
            if node.is_leaf:
                leaf_depths.add(depth)
                return
            for entry in node.entries:
                assert entry.child is not None
                child_mbr = entry.child.mbr
                assert child_mbr is not None
                (px1, py1), (px2, py2) = entry.mbr
                (cx1, cy1), (cx2, cy2) = child_mbr
                assert px1 <= cx1 + 1e-9 and py1 <= cy1 + 1e-9
                assert px2 >= cx2 - 1e-9 and py2 >= cy2 - 1e-9
                assert entry.child.parent is node
                visit(entry.child, depth + 1)

        visit(self.root, 1)
        assert len(leaf_depths) == 1
        assert sum(1 for _ in self.scan()) == self._size
        return True

    def stats(self) -> Dict[str, Any]:
        nodes = leaves = entries_internal = entries_leaf = 0
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
            "avg_occupancy": sum(occupancy) / len(occupancy) if occupancy else 0.0,
            "fill_factor": entries_leaf / (leaves * self.max_entries) if leaves else 0.0,
        }
