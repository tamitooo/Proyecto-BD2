"""Índice espacial: envuelve el R-Tree con semántica de latitud/longitud.

El R-Tree trabaja sobre un plano ``(x, y)`` con una sola unidad. Para que las
consultas sean correctas con **las dos métricas** que pide el enunciado hace
falta que el plano del índice y el de la consulta hablen en la misma unidad:

* **Euclidiana** (grados): el plano es directamente ``(x, y) = (lon, lat)``. Sólo
  tiene sentido si los datos no son geográficos.
* **Geodésica / Haversine** (metros): el plano es una **proyección local
  equirectangular** en metros, ``x = (lon − lon₀) · 111320 · cos(lat₀)``,
  ``y = (lat − lat₀) · 111320``. Con eso MINDIST es una **cota inferior real** de
  la distancia geodésica y el k-NN es **exacto**.

La proyección usa el ``lat₀`` del centro del dataset, así que el error de
estiramiento es del orden de ``Δlon·(cos(lat) − cos(lat₀))``: despreciable en una
región de decenas de kilómetros (≈ 0.1 % a 20 km del centro en Lima). Se elige
porque es el enfoque que usa la clase y porque hace que las dos métricas
compartan el mismo índice sin duplicar la estructura.
"""

import math
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from indexes.rtree import MBR, RTree
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
    """R-Tree indexado por (latitud, longitud) con métrica configurable.

    El RID que guarda el árbol es el del almacenamiento, así que el índice no
    duplica los datos: sólo mantiene ``rid -> (lat, lon)`` para poder calcular la
    distancia real y para reconstruirse.
    """

    #: Técnicas expuestas al planner (mismo nombre que usa el catálogo).
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

        self.lat_column = lat_column
        self.lon_column = lon_column
        self.max_entries = max_entries
        self.metric = metric

        self.tree = RTree(max_entries=max_entries)
        #: rid -> (lat, lon). Es la única copia de datos que mantiene el índice.
        self._points: Dict[Any, Point] = {}
        #: Parámetros de la proyección local, fijados al primer punto.
        self._lat0: Optional[float] = None
        self._lon0: Optional[float] = None
        self._m_per_lon: float = METERS_PER_DEGREE_LAT

    # ------------------------------------------------------------ propiedades

    def __len__(self) -> int:
        return len(self.tree)

    @property
    def unique(self) -> bool:
        # Un índice espacial no impone unicidad.
        return False

    @property
    def order(self) -> int:
        """Alias de ``max_entries`` para que el catálogo lo trate como a los B+."""
        return self.max_entries

    def __repr__(self) -> str:
        return (
            f"SpatialIndex({self.lat_column}, {self.lon_column}, "
            f"métrica={self.metric}, puntos={len(self)}, altura={self.tree.height})"
        )

    # -------------------------------------------------------------- proyección

    def _project(
        self,
        lat: float,
        lon: float,
        metric: Optional[str] = None,
    ) -> Tuple[float, float]:
        """(lat, lon) -> plano del índice, en la unidad de la métrica.

        Cada métrica tiene su propio plano: Euclidiana usa grados y Haversine usa
        metros (proyección local). El árbol se construye con el plano de la
        métrica **por defecto** del índice; si se consulta con la otra métrica se
        proyecta de forma consistente y el resultado sigue siendo correcto
        (el MINDIST sigue siendo cota inferior del plano de esa métrica).
        """
        used = metric or self.metric
        if used == "euclidean":
            return lon, lat

        if self._lat0 is None:
            # Sin origen fijado (índice vacío): se usa el propio punto.
            return (
                (lon - lon) * meters_per_degree_lon(lat),
                (lat - lat) * METERS_PER_DEGREE_LAT,
            )
        return (
            (lon - self._lon0) * self._m_per_lon,
            (lat - self._lat0) * METERS_PER_DEGREE_LAT,
        )

    def _fix_origin(self, lat: float) -> None:
        """Fija el origen de la proyección antes de una carga masiva.

        Se hace con el centro del dataset (no con el primer punto) para que el
        estiramiento en longitud sea simétrico y mínimo.
        """
        if self.metric == "euclidean" or self._lat0 is not None:
            return
        self._lat0 = lat
        self._lon0 = 0.0
        self._m_per_lon = meters_per_degree_lon(lat)

    # -------------------------------------------------------------- escritura

    def insert(self, record: Dict[str, Any], rid: Any) -> None:
        """Inserta un registro (dict) con su RID."""
        lat, lon = self._coords_of(record)
        if self.metric != "euclidean" and self._lat0 is None:
            # Índice creado vacío: el primer punto fija el origen. Sin esto la
            # proyección colapsaba todos los puntos en (0, 0).
            self._fix_origin(lat)
        self._points[rid] = (lat, lon)
        self.tree.insert(self._project(lat, lon), rid)

    def bulk_load(self, pairs: Iterable[Tuple[Dict[str, Any], Any]]) -> None:
        """Carga masiva: fija el origen de proyección y empaqueta el árbol."""
        prepared: List[Tuple[Tuple[float, float], Any]] = []
        lats: List[float] = []

        for record, rid in pairs:
            lat, lon = self._coords_of(record)
            self._points[rid] = (lat, lon)
            lats.append(lat)
            prepared.append(((lat, lon), rid))

        if not prepared:
            return

        if self.metric != "euclidean" and self._lat0 is None:
            # Centro del dataset: minimiza el error de la proyección local.
            self._fix_origin(sum(lats) / len(lats))

        self.tree.bulk_load(
            [(self._project(lat, lon), rid) for (lat, lon), rid in prepared]
        )

    def delete(self, rid: Any) -> bool:
        """Elimina un punto por RID (reconstruye sólo si hace falta)."""
        if rid not in self._points:
            return False
        del self._points[rid]
        self.rebuild_from(self._points.items())
        return True

    def delete_record(self, record: Dict[str, Any], rid: Any) -> bool:
        return self.delete(rid)

    def rebuild_from(self, items: Iterable[Tuple[Any, Point]]) -> None:
        """Reconstruye el árbol a partir de ``(rid, (lat, lon))``."""
        pairs = list(items)
        self.tree = RTree(max_entries=self.max_entries)
        self._points = {}
        if not pairs:
            return
        lats = [point[0] for _, point in pairs]
        if self.metric != "euclidean":
            self._fix_origin(sum(lats) / len(lats))
        self.tree.bulk_load(
            [
                (self._project(lat, lon), rid)
                for rid, (lat, lon) in pairs
            ]
        )
        self._points = {rid: point for rid, point in pairs}

    def _coords_of(self, record: Dict[str, Any]) -> Point:
        """Extrae (lat, lon) de un registro, con validación."""
        if self.lat_column not in record:
            raise KeyError(f"el registro no tiene la columna '{self.lat_column}'")
        if self.lon_column not in record:
            raise KeyError(f"el registro no tiene la columna '{self.lon_column}'")
        return validate_point(record[self.lat_column], record[self.lon_column])

    # ---------------------------------------------------------------- consultas

    def coordinates(self, rid: Any) -> Point:
        """Coordenadas geográficas de un RID."""
        try:
            return self._points[rid]
        except KeyError as exc:
            raise KeyError(f"RID desconocido en el índice espacial: {rid!r}") from exc

    def distance(self, origin: Point, rid: Any) -> float:
        """Distancia real entre ``origin`` y el punto del RID, en la unidad métrica."""
        target = self.coordinates(rid)
        if self.metric == "euclidean":
            return euclidean(origin, target)
        return haversine(origin, target)

    def range_search(
        self,
        center: Point,
        radius: float,
        *,
        metric: Optional[str] = None,
        exact: bool = True,
    ) -> List[Tuple[Any, float]]:
        """Puntos dentro de un radio, con su distancia real.

        ``radius`` va en la unidad de la métrica: **metros** para Haversine,
        **grados** para Euclidiana.

        El índice descarta por MBR (barato) y después se comprueba la distancia
        real de cada candidato: **el resultado es exacto**, el MBR sólo poda.
        """
        used_metric = metric or self.metric
        if radius < 0:
            raise ValueError("el radio no puede ser negativo")

        box = self._query_box(center, radius, used_metric)
        candidates = self.tree.range_search(box)

        medir = euclidean if used_metric == "euclidean" else haversine
        results: List[Tuple[Any, float]] = []
        for rid, _mbr in candidates:
            real = medir(center, self.coordinates(rid))
            if not exact or real <= radius:
                results.append((rid, real))

        results.sort(key=lambda item: item[1])
        return results

    # Margen de la proyección local: el plano equirectangular puede desviarse
    # ~0.1 % a 20 km del centro; con 2 % la caja/cota sigue siendo segura para
    # datos de una ciudad o región (el resultado siempre se verifica exacto).
    _PROJECTION_SLACK = 0.98

    def _query_box(self, center: Point, radius: float, metric: str):
        """Caja en el **plano del árbol** que contiene la región de la consulta.

        El árbol se construye en el plano de ``self.metric`` (grados para
        Euclidiana, metros para Haversine). Si la consulta usa la otra métrica,
        el radio se convierte de unidad antes de abrir la caja; si no, la poda
        descartaría puntos válidos (era el error: ``EUCLIDEAN < 0.05`` se
        interpretaba como 0.05 metros).
        """
        lat, lon = center
        if metric == "euclidean":
            # Región en grados: [lat ± r] × [lon ± r].
            lat_lo, lat_hi, lon_lo, lon_hi = lat - radius, lat + radius, lon - radius, lon + radius
        else:
            # Región en metros: se pasa a grados con holgura por la latitud.
            dlat = radius / METERS_PER_DEGREE_LAT / self._PROJECTION_SLACK
            peor_lat = min(89.0, abs(lat) + dlat)
            dlon = radius / max(1.0, meters_per_degree_lon(peor_lat)) / self._PROJECTION_SLACK
            lat_lo, lat_hi, lon_lo, lon_hi = lat - dlat, lat + dlat, lon - dlon, lon + dlon

        if self.metric == "euclidean":
            return ((lon_lo, lat_lo), (lon_hi, lat_hi))
        a = self._project(lat_lo, lon_lo)
        b = self._project(lat_hi, lon_hi)
        return (
            (min(a[0], b[0]), min(a[1], b[1])),
            (max(a[0], b[0]), max(a[1], b[1])),
        )

    def _bound_scale(self, metric: str) -> float:
        """Factor que convierte MINDIST del plano del árbol en cota de ``metric``."""
        if metric == self.metric:
            return 1.0 if metric == "euclidean" else self._PROJECTION_SLACK
        if self.metric != "euclidean":
            # Árbol en metros, distancia en grados: d_grados >= d_m / max(m/°).
            return self._PROJECTION_SLACK / max(METERS_PER_DEGREE_LAT, self._m_per_lon)
        # Árbol en grados, distancia en metros: d_m >= d_grados · min(m/°).
        lats = [p[0] for p in self._points.values()] or [0.0]
        peor = min(89.0, max(abs(x) for x in lats))
        return self._PROJECTION_SLACK * min(METERS_PER_DEGREE_LAT, meters_per_degree_lon(peor))

    def knn(
        self,
        center: Point,
        k: int,
        *,
        metric: Optional[str] = None,
    ) -> List[Tuple[Any, float]]:
        """K vecinos más cercanos, con best-first search y poda por MINDIST.

        La distancia real se calcula con ``distance()``, que usa las coordenadas
        geográficas originales; el heap se ordena con MINDIST sobre el plano
        proyectado, que es una cota inferior de esa distancia.
        """
        used_metric = metric or self.metric
        origin = self._project(*center)
        medir = euclidean if used_metric == "euclidean" else haversine
        return self.tree.knn(
            origin,
            k,
            distance=lambda rid: medir(center, self.coordinates(rid)),
            bound_scale=self._bound_scale(used_metric),
        )

    def polygon_search(
        self,
        ring: Sequence[Point],
    ) -> List[Tuple[Any, Point]]:
        """Puntos dentro de un polígono (intersección con el área).

        Se poda con el MBR del polígono y se confirma con **ray casting**
        (punto-en-polígono). Devuelve ``(rid, (lat, lon))``.
        """
        if len(ring) < 3:
            raise ValueError("el polígono necesita al menos 3 vértices")

        polygon_mbr = polygon_to_mbr(ring)
        # El MBR del polígono está en (lon, lat); hay que llevarlo al plano.
        if self.metric == "euclidean":
            box = polygon_mbr
        else:
            (lon_min, lat_min), (lon_max, lat_max) = polygon_mbr
            box = (
                self._project(lat_min, lon_min),
                self._project(lat_max, lon_max),
            )
            # Asegurar el orden de las esquinas tras proyectar.
            box = (
                (min(box[0][0], box[1][0]), min(box[0][1], box[1][1])),
                (max(box[0][0], box[1][0]), max(box[0][1], box[1][1])),
            )

        candidates = self.tree.range_search(box)

        results: List[Tuple[Any, Point]] = []
        for rid, _mbr in candidates:
            point = self.coordinates(rid)
            if point_in_polygon(point, ring):
                results.append((rid, point))

        results.sort(key=lambda item: (item[1][0], item[1][1]))
        return results

    # ------------------------------------------------------------ utilitarios

    def scan(self) -> List[Point]:
        """Todos los puntos, para el panel de mapa."""
        return list(self._points.values())

    def points_with_rid(self) -> List[Tuple[Any, Point]]:
        return list(self._points.items())

    def bounds(self):
        """``(min_lat, max_lat, min_lon, max_lon)`` de los puntos indexados."""
        from spatial.geo import bounds_of

        return bounds_of(self._points.values())

    def validate(self) -> bool:
        """Valida el R-Tree y que las coordenadas y las entradas cuadren."""
        self.tree.validate()
        assert len(self._points) == len(self.tree), (
            f"el índice tiene {len(self._points)} coordenadas y "
            f"{len(self.tree)} entradas"
        )
        return True

    def serialized_size_bytes(self) -> int:
        """Espacio del índice en formato de disco (todas las entradas y nodos)."""
        return self.tree.serialized_size_bytes()

    def stats(self) -> Dict[str, Any]:
        data = self.tree.stats()
        data.update(
            {
                "kind": self.kind,
                "metric": self.metric,
                "lat_column": self.lat_column,
                "lon_column": self.lon_column,
            }
        )
        return data
