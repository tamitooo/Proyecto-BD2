"""Infraestructura espacial del minigestor BD2."""

from .geo import euclidean, haversine, point_in_polygon
from .index import SpatialIndex

__all__ = ["SpatialIndex", "euclidean", "haversine", "point_in_polygon"]
