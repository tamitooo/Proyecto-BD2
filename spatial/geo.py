"""Utilidades geográficas y geométricas para la Parte 2 (datos espaciales)."""

import math
from typing import Iterable, List, Optional, Sequence, Tuple

Point = Tuple[float, float]
Ring = Sequence[Point]
EARTH_RADIUS_M = 6_371_008.8
METERS_PER_DEGREE_LAT = 111_320.0


class GeoError(ValueError):
    """Coordenada o geometría inválida."""


def validate_point(lat: float, lon: float) -> Point:
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError) as exc:
        raise GeoError(f"coordenada no numérica: {lat!r}, {lon!r}") from exc
    if math.isnan(lat) or math.isnan(lon):
        raise GeoError("coordenada NaN")
    if not -90.0 <= lat <= 90.0:
        raise GeoError(f"latitud fuera de rango [-90, 90]: {lat}")
    if not -180.0 <= lon <= 180.0:
        raise GeoError(f"longitud fuera de rango [-180, 180]: {lon}")
    return lat, lon


def euclidean(first: Point, second: Point) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def haversine(first: Point, second: Point) -> float:
    lat1, lon1 = math.radians(first[0]), math.radians(first[1])
    lat2, lon2 = math.radians(second[0]), math.radians(second[1])
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    a = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    a = min(1.0, max(0.0, a))
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


METRICS = {
    "euclidean": euclidean,
    "euclidiana": euclidean,
    "haversine": haversine,
    "geodesic": haversine,
    "geodesica": haversine,
    "geodésica": haversine,
}
METRIC_UNITS = {"euclidean": "grados", "haversine": "m"}


def resolve_metric(name: str):
    key = (name or "euclidean").strip().lower()
    if key not in METRICS:
        raise GeoError(f"métrica desconocida '{name}'; usa EUCLIDEAN o HAVERSINE")
    canonical = (
        "haversine"
        if key in {"haversine", "geodesic", "geodesica", "geodésica"}
        else "euclidean"
    )
    return canonical, METRICS[key]


def meters_per_degree_lon(latitude: float) -> float:
    return METERS_PER_DEGREE_LAT * max(0.01, math.cos(math.radians(latitude)))


def circle_to_mbr(center: Point, radius_m: float) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    lat, lon = center
    if radius_m < 0:
        raise GeoError("el radio no puede ser negativo")
    delta_lat = radius_m / METERS_PER_DEGREE_LAT
    delta_lon = radius_m / meters_per_degree_lon(lat)
    return ((lon - delta_lon, lat - delta_lat), (lon + delta_lon, lat + delta_lat))


def bounds_of(points: Iterable[Point]) -> Optional[Tuple[float, float, float, float]]:
    min_lat = min_lon = math.inf
    max_lat = max_lon = -math.inf
    found = False
    for lat, lon in points:
        found = True
        min_lat = min(min_lat, lat)
        max_lat = max(max_lat, lat)
        min_lon = min(min_lon, lon)
        max_lon = max(max_lon, lon)
    if not found:
        return None
    return min_lat, max_lat, min_lon, max_lon


def point_in_polygon(point: Point, ring: Ring) -> bool:
    if len(ring) < 3:
        raise GeoError("un polígono necesita al menos 3 vértices")
    lat, lon = point
    inside = False
    n = len(ring)
    for i in range(n):
        lat1, lon1 = ring[i]
        lat2, lon2 = ring[(i + 1) % n]
        if _on_segment((lat, lon), (lat1, lon1), (lat2, lon2)):
            return True
        if (lat1 > lat) != (lat2 > lat):
            t = (lat - lat1) / (lat2 - lat1)
            crossing_lon = lon1 + t * (lon2 - lon1)
            if crossing_lon > lon:
                inside = not inside
    return inside


def _on_segment(point: Point, first: Point, second: Point, tol: float = 1e-12) -> bool:
    px, py = point
    ax, ay = first
    bx, by = second
    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > tol:
        return False
    return (
        min(ax, bx) - tol <= px <= max(ax, bx) + tol
        and min(ay, by) - tol <= py <= max(ay, by) + tol
    )


def polygon_to_mbr(ring: Ring) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    if len(ring) < 3:
        raise GeoError("un polígono necesita al menos 3 vértices")
    lats = [lat for lat, _ in ring]
    lons = [lon for _, lon in ring]
    return ((min(lons), min(lats)), (max(lons), max(lats)))


def polygon_area(ring: Ring) -> float:
    if len(ring) < 3:
        return 0.0
    total = 0.0
    n = len(ring)
    for i in range(n):
        lat1, lon1 = ring[i]
        lat2, lon2 = ring[(i + 1) % n]
        total += lon1 * lat2 - lon2 * lat1
    return abs(total) / 2.0


def polygon_perimeter_m(ring: Ring) -> float:
    if len(ring) < 2:
        return 0.0
    return sum(haversine(ring[i], ring[(i + 1) % len(ring)]) for i in range(len(ring)))


def generate_points(
    count: int,
    *,
    center: Point = (-12.0464, -77.0428),
    spread_km: float = 30.0,
    seed: int = 42,
) -> List[Point]:
    import random

    rng = random.Random(seed)
    lat0, lon0 = center
    dlat = spread_km / (METERS_PER_DEGREE_LAT / 1000.0)
    dlon = spread_km / (meters_per_degree_lon(lat0) / 1000.0)
    hotspots = [
        (lat0 + rng.uniform(-dlat, dlat), lon0 + rng.uniform(-dlon, dlon))
        for _ in range(8)
    ]
    points: List[Point] = []
    for i in range(count):
        if i % 5 == 0:
            lat = lat0 + rng.uniform(-dlat, dlat)
            lon = lon0 + rng.uniform(-dlon, dlon)
        else:
            focus_lat, focus_lon = hotspots[i % len(hotspots)]
            lat = focus_lat + rng.gauss(0, dlat / 12.0)
            lon = focus_lon + rng.gauss(0, dlon / 12.0)
        points.append(validate_point(min(90.0, max(-90.0, lat)), lon))
    return points
