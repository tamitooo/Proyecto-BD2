"""Utilidades geográficas y geométricas para la Parte 2 (datos espaciales).

Todo se calcula con la librería estándar. Dos convenciones que conviene tener
claras porque se mezclan en todo el módulo:

* Las coordenadas de los puntos son **(latitud, longitud)** en grados, que es
  como las escribe el usuario en SQL (``POINT(-12.0464, -77.0428)``).
* El índice R-Tree trabaja sobre un plano. Para que las consultas sean
  correctas, los puntos se indexan como **(x, y) = (longitud, latitud)** y las
  distancias se miden con la métrica elegida.

Métricas implementadas (las dos que pide el enunciado):

* **Euclidiana**: distancia en el plano de las coordenadas, en *grados*. Es la
  métrica que usa MINDIST de forma exacta y la que tiene sentido si los datos no
  son geográficos (por ejemplo, coordenadas de una imagen).
* **Geodésica (Haversine)**: distancia sobre la esfera terrestre, en **metros**.
  Es la correcta para latitud/longitud.

Para Haversine el R-Tree necesita una **cota inferior** con la que podar. Se usa
la distancia euclidiana en un plano local escalado a metros
(``1° lat = 111 320 m``, ``1° lon = 111 320 · cos(lat) m``), que es menor o igual
que la distancia sobre la esfera, así que el k-NN sigue siendo **exacto**: la
cota sólo decide el orden de visita, y la distancia real se calcula siempre con
Haversine.
"""

import math
from typing import Iterable, List, Optional, Sequence, Tuple

Point = Tuple[float, float]
Ring = Sequence[Point]

#: Radios de referencia (WGS-84 medio).
EARTH_RADIUS_M = 6_371_008.8
#: Metros por grado de latitud (constante, la latitud no cambia de escala).
METERS_PER_DEGREE_LAT = 111_320.0


class GeoError(ValueError):
    """Coordenada o geometría inválida."""


# ----------------------------------------------------------------------
# Validación
# ----------------------------------------------------------------------

def validate_point(lat: float, lon: float) -> Point:
    """Valida un par latitud/longitud y lo devuelve normalizado a float."""
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


# ----------------------------------------------------------------------
# Distancias
# ----------------------------------------------------------------------

def euclidean(first: Point, second: Point) -> float:
    """Distancia euclidiana en el plano de coordenadas (en grados)."""
    return math.hypot(first[0] - second[0], first[1] - second[1])


def haversine(first: Point, second: Point) -> float:
    """Distancia geodésica (Haversine) en **metros**.

    Fórmula:
        a = sin²(Δφ/2) + cos φ1 · cos φ2 · sin²(Δλ/2)
        d = 2R · asin(√a)

    Se usa ``asin`` (no ``atan2``) porque es la forma que aparece en la clase y
    en el enunciado, y porque numéricamente es estable para distancias cortas.
    """
    lat1, lon1 = math.radians(first[0]), math.radians(first[1])
    lat2, lon2 = math.radians(second[0]), math.radians(second[1])

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1

    a = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    # Protección contra errores de redondeo que dejarían a > 1.
    a = min(1.0, max(0.0, a))
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


#: Métricas disponibles por nombre, como las escribe el SQL.
METRICS = {
    "euclidean": euclidean,
    "euclidiana": euclidean,
    "haversine": haversine,
    "geodesic": haversine,
    "geodesica": haversine,
    "geodésica": haversine,
}

#: Unidad de cada métrica, para mostrarla en los resultados.
METRIC_UNITS = {
    "euclidean": "grados",
    "haversine": "m",
}


def resolve_metric(name: str):
    """Devuelve ``(nombre_canónico, función)`` para una métrica del SQL."""
    key = (name or "euclidean").strip().lower()
    if key not in METRICS:
        raise GeoError(
            f"métrica desconocida '{name}'; usa EUCLIDEAN o HAVERSINE"
        )
    canonical = "haversine" if key in {"haversine", "geodesic", "geodesica", "geodésica"} else "euclidean"
    return canonical, METRICS[key]


# ----------------------------------------------------------------------
# Conversión de unidades y MBR
# ----------------------------------------------------------------------

def meters_per_degree_lon(latitude: float) -> float:
    """Metros por grado de longitud a una latitud dada."""
    return METERS_PER_DEGREE_LAT * max(0.01, math.cos(math.radians(latitude)))


def circle_to_mbr(center: Point, radius_m: float) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """MBR que contiene el círculo de radio ``radius_m`` alrededor de ``center``.

    Se devuelve en el plano del índice, es decir ``(x, y) = (lon, lat)``.
    """
    lat, lon = center
    if radius_m < 0:
        raise GeoError("el radio no puede ser negativo")

    delta_lat = radius_m / METERS_PER_DEGREE_LAT
    delta_lon = radius_m / meters_per_degree_lon(lat)
    return ((lon - delta_lon, lat - delta_lat), (lon + delta_lon, lat + delta_lat))


def bounds_of(points: Iterable[Point]) -> Optional[Tuple[float, float, float, float]]:
    """``(min_lat, max_lat, min_lon, max_lon)`` de una colección de puntos."""
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


# ----------------------------------------------------------------------
# Polígonos
# ----------------------------------------------------------------------

def point_in_polygon(point: Point, ring: Ring) -> bool:
    """Ray casting (even-odd): ¿el punto está dentro del polígono?

    Se traza un rayo horizontal hacia la derecha desde el punto y se cuentan los
    cruces con las aristas. Un número impar de cruces significa "dentro". Los
    puntos sobre el borde se consideran dentro (se comprueban aparte para que el
    resultado sea estable).
    """
    if len(ring) < 3:
        raise GeoError("un polígono necesita al menos 3 vértices")

    lat, lon = point
    inside = False
    n = len(ring)

    for i in range(n):
        lat1, lon1 = ring[i]
        lat2, lon2 = ring[(i + 1) % n]

        # Punto exactamente sobre la arista -> dentro.
        if _on_segment((lat, lon), (lat1, lon1), (lat2, lon2)):
            return True

        # ¿La arista cruza la horizontal que pasa por el punto?
        if (lat1 > lat) != (lat2 > lat):
            # Longitud de la arista en la latitud del punto.
            t = (lat - lat1) / (lat2 - lat1)
            crossing_lon = lon1 + t * (lon2 - lon1)
            if crossing_lon > lon:
                inside = not inside

    return inside


def _on_segment(point: Point, first: Point, second: Point, tol: float = 1e-12) -> bool:
    """¿``point`` está sobre el segmento ``first``-``second``?"""
    px, py = point
    ax, ay = first
    bx, by = second

    cross = (px - ax) * (by - ay) - (py - ay) * (bx - ax)
    if abs(cross) > tol:
        return False

    if min(ax, bx) - tol <= px <= max(ax, bx) + tol and \
       min(ay, by) - tol <= py <= max(ay, by) + tol:
        return True
    return False


def polygon_to_mbr(ring: Ring) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """MBR del polígono, en el plano del índice ``(x, y) = (lon, lat)``."""
    if len(ring) < 3:
        raise GeoError("un polígono necesita al menos 3 vértices")
    lats = [lat for lat, _ in ring]
    lons = [lon for _, lon in ring]
    return ((min(lons), min(lats)), (max(lons), max(lats)))


def polygon_area(ring: Ring) -> float:
    """Área del polígono por la fórmula del cordón (shoelace), en grados²."""
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
    """Perímetro del polígono en metros (suma de Haversine por arista)."""
    if len(ring) < 2:
        return 0.0
    total = 0.0
    n = len(ring)
    for i in range(n):
        total += haversine(ring[i], ring[(i + 1) % n])
    return total


# ----------------------------------------------------------------------
# Espiral de puntos de prueba (para datasets reproducibles)
# ----------------------------------------------------------------------

def generate_points(
    count: int,
    *,
    center: Point = (-12.0464, -77.0428),
    spread_km: float = 30.0,
    seed: int = 42,
) -> List[Point]:
    """Genera ``count`` puntos reproducibles alrededor de ``center``.

    Se usa una distribución con **zonas de densidad** (varios focos) en lugar de
    uniforme: así las consultas por rango encuentran cantidades distintas según
    la zona y el índice tiene que trabajar con MBR solapados, que es el caso
    interesante para comparar con la búsqueda secuencial.
    """
    import random

    rng = random.Random(seed)
    lat0, lon0 = center
    dlat = spread_km / (METERS_PER_DEGREE_LAT / 1000.0)
    dlon = spread_km / (meters_per_degree_lon(lat0) / 1000.0)

    # Focos de densidad: 8 zonas con distinta concentración.
    hotspots = [
        (
            lat0 + rng.uniform(-dlat, dlat),
            lon0 + rng.uniform(-dlon, dlon),
        )
        for _ in range(8)
    ]

    points: List[Point] = []
    for i in range(count):
        if i % 5 == 0:
            # 20 % disperso por toda el área.
            lat = lat0 + rng.uniform(-dlat, dlat)
            lon = lon0 + rng.uniform(-dlon, dlon)
        else:
            # 80 % concentrado en los focos.
            focus_lat, focus_lon = hotspots[i % len(hotspots)]
            lat = focus_lat + rng.gauss(0, dlat / 12.0)
            lon = focus_lon + rng.gauss(0, dlon / 12.0)
        points.append(validate_point(min(90.0, max(-90.0, lat)), lon))
    return points
