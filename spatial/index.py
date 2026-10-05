"""Índice espacial R-Tree para latitud/longitud con Euclidiana y Haversine.

La implementación mantiene dos representaciones R-Tree de las mismas entradas:
una en grados (Euclidiana) y otra en una proyección local a metros (Haversine).
Así MINDIST y la distancia exacta usan la misma unidad en cada consulta. El
usuario sigue viendo un único índice lógico RTREE en el catálogo.
"""

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from indexes.rtree import RTree
from spatial.geo import (
    METERS_PER_DEGREE_LAT,
    Point,
    euclidean,
    haversine,
    meters_per_degree_lon,
    point_in_polygon,
    polygon_to_mbr,
    validate_point,
)


class SpatialIndex:
    kind = "rtree"

    def __init__(
        self,
        lat_column: str,
        lon_column: str,
        *,
        max_entries: int = 16,
        metric: str = "haversine",
    ):
        if not lat_column or not lon_column:
            raise ValueError("el índice espacial necesita columna de latitud y longitud")
        if lat_column == lon_column:
            raise ValueError("latitud y longitud no pueden ser la misma columna")
        metric = (metric or "haversine").strip().lower()
        if metric not in {"haversine", "euclidean"}:
            raise ValueError("metric debe ser 'haversine' o 'euclidean'")

        self.lat_column = lat_column
        self.lon_column = lon_column
        self.max_entries = max_entries
        self.metric = metric
        self._points: Dict[Any, Point] = {}
        self._lat0: Optional[float] = None
        self._lon0: float = 0.0
        self._m_per_lon: float = METERS_PER_DEGREE_LAT
        self._tree_euclidean = RTree(max_entries=max_entries)
        self._tree_haversine = RTree(max_entries=max_entries)
        self.tree = self._tree_haversine if metric == "haversine" else self._tree_euclidean

    def __len__(self) -> int:
        return len(self._points)

    @property
    def unique(self) -> bool:
        return False

    @property
    def order(self) -> int:
        return self.max_entries

    def __repr__(self) -> str:
        return (
            f"SpatialIndex({self.lat_column}, {self.lon_column}, "
            f"métrica={self.metric}, puntos={len(self)}, altura={self.tree.height})"
        )

    def _set_origin(self, lat: float) -> None:
        self._lat0 = float(lat)
        self._m_per_lon = meters_per_degree_lon(self._lat0)

    def _project_haversine(self, lat: float, lon: float) -> Tuple[float, float]:
        if self._lat0 is None:
            self._set_origin(lat)
        return (
            (lon - self._lon0) * self._m_per_lon,
            (lat - self._lat0) * METERS_PER_DEGREE_LAT,
        )

    @staticmethod
    def _project_euclidean(lat: float, lon: float) -> Tuple[float, float]:
        return lon, lat

    def _tree_for(self, metric: str) -> RTree:
        return self._tree_euclidean if metric == "euclidean" else self._tree_haversine

    def _coords_of(self, record: Dict[str, Any]) -> Point:
        if self.lat_column not in record:
            raise KeyError(f"el registro no tiene la columna '{self.lat_column}'")
        if self.lon_column not in record:
            raise KeyError(f"el registro no tiene la columna '{self.lon_column}'")
        return validate_point(record[self.lat_column], record[self.lon_column])

    def insert(self, record: Dict[str, Any], rid: Any) -> None:
        lat, lon = self._coords_of(record)
        if self._lat0 is None:
            self._set_origin(lat)
        self._points[rid] = (lat, lon)
        self._tree_euclidean.insert(self._project_euclidean(lat, lon), rid)
        self._tree_haversine.insert(self._project_haversine(lat, lon), rid)

    def bulk_load(self, pairs: Iterable[Tuple[Dict[str, Any], Any]]) -> None:
        prepared: List[Tuple[Any, float, float]] = []
        for record, rid in pairs:
            lat, lon = self._coords_of(record)
            prepared.append((rid, lat, lon))
        self._points = {rid: (lat, lon) for rid, lat, lon in prepared}
        self._tree_euclidean = RTree(max_entries=self.max_entries)
        self._tree_haversine = RTree(max_entries=self.max_entries)
        if prepared:
            self._set_origin(sum(lat for _, lat, _ in prepared) / len(prepared))
            self._tree_euclidean.bulk_load(
                [(self._project_euclidean(lat, lon), rid) for rid, lat, lon in prepared]
            )
            self._tree_haversine.bulk_load(
                [(self._project_haversine(lat, lon), rid) for rid, lat, lon in prepared]
            )
        else:
            self._lat0 = None
        self.tree = self._tree_haversine if self.metric == "haversine" else self._tree_euclidean

    def delete(self, rid: Any) -> bool:
        if rid not in self._points:
            return False
        remaining = [(key, value) for key, value in self._points.items() if key != rid]
        self.rebuild_from(remaining)
        return True

    def delete_record(self, record: Dict[str, Any], rid: Any) -> bool:
        return self.delete(rid)

    def rebuild_from(self, items: Iterable[Tuple[Any, Point]]) -> None:
        pairs = list(items)
        self._tree_euclidean = RTree(max_entries=self.max_entries)
        self._tree_haversine = RTree(max_entries=self.max_entries)
        self._points = {rid: validate_point(*point) for rid, point in pairs}
        if pairs:
            self._set_origin(sum(point[0] for _, point in pairs) / len(pairs))
            self._tree_euclidean.bulk_load(
                [(self._project_euclidean(lat, lon), rid) for rid, (lat, lon) in pairs]
            )
            self._tree_haversine.bulk_load(
                [(self._project_haversine(lat, lon), rid) for rid, (lat, lon) in pairs]
            )
        else:
            self._lat0 = None
        self.tree = self._tree_haversine if self.metric == "haversine" else self._tree_euclidean

    def coordinates(self, rid: Any) -> Point:
        try:
            return self._points[rid]
        except KeyError as exc:
            raise KeyError(f"RID desconocido en el índice espacial: {rid!r}") from exc

    def distance(self, origin: Point, rid: Any, *, metric: Optional[str] = None) -> float:
        used = metric or self.metric
        target = self.coordinates(rid)
        return euclidean(origin, target) if used == "euclidean" else haversine(origin, target)

    def range_search(
        self,
        center: Point,
        radius: float,
        *,
        metric: Optional[str] = None,
        exact: bool = True,
    ) -> List[Tuple[Any, float]]:
        used = (metric or self.metric).lower()
        if used not in {"euclidean", "haversine"}:
            raise ValueError("metric debe ser 'euclidean' o 'haversine'")
        if radius < 0:
            raise ValueError("el radio no puede ser negativo")

        if used == "euclidean":
            projected = self._project_euclidean(*center)
        else:
            projected = self._project_haversine(*center)
        box = (
            (projected[0] - radius, projected[1] - radius),
            (projected[0] + radius, projected[1] + radius),
        )
        candidates = self._tree_for(used).range_search(box)
        results: List[Tuple[Any, float]] = []
        for rid, _ in candidates:
            real = self.distance(center, rid, metric=used)
            if not exact or real <= radius:
                results.append((rid, real))
        results.sort(key=lambda item: item[1])
        return results

    def knn(
        self,
        center: Point,
        k: int,
        *,
        metric: Optional[str] = None,
    ) -> List[Tuple[Any, float]]:
        used = (metric or self.metric).lower()
        if used not in {"euclidean", "haversine"}:
            raise ValueError("metric debe ser 'euclidean' o 'haversine'")
        origin = (
            self._project_euclidean(*center)
            if used == "euclidean"
            else self._project_haversine(*center)
        )
        return self._tree_for(used).knn(
            origin,
            k,
            distance=lambda rid: self.distance(center, rid, metric=used),
        )

    def polygon_search(self, ring: Sequence[Point]) -> List[Tuple[Any, Point]]:
        if len(ring) < 3:
            raise ValueError("el polígono necesita al menos 3 vértices")
        # Polígonos vienen en lat/lon y el árbol Euclidiano está en lon/lat.
        box = polygon_to_mbr(ring)
        candidates = self._tree_euclidean.range_search(box)
        results: List[Tuple[Any, Point]] = []
        for rid, _ in candidates:
            point = self.coordinates(rid)
            if point_in_polygon(point, ring):
                results.append((rid, point))
        results.sort(key=lambda item: (item[1][0], item[1][1]))
        return results

    def scan(self) -> List[Point]:
        return list(self._points.values())

    def points_with_rid(self) -> List[Tuple[Any, Point]]:
        return list(self._points.items())

    def bounds(self):
        from spatial.geo import bounds_of
        return bounds_of(self._points.values())

    def validate(self) -> bool:
        self._tree_euclidean.validate()
        self._tree_haversine.validate()
        assert len(self._points) == len(self._tree_euclidean)
        assert len(self._points) == len(self._tree_haversine)
        return True

    def stats(self) -> Dict[str, Any]:
        data = self.tree.stats()
        data.update(
            {
                "kind": self.kind,
                "metric": self.metric,
                "lat_column": self.lat_column,
                "lon_column": self.lon_column,
                "euclidean_nodes": self._tree_euclidean.stats()["nodes"],
                "haversine_nodes": self._tree_haversine.stats()["nodes"],
            }
        )
        return data
