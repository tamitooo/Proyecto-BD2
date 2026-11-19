"""Issue k: tiendas cercanas que tienen stock del producto.

El motor no puede filtrar por una columna del lado derecho de un JOIN (el
``WHERE`` se aplica antes del join), así que se usan dos consultas y la
intersección se hace en Python:

1. tiendas dentro del radio (R-Tree si existe; si no, filtro espacial lineal);
2. stock de ese producto con ``cantidad > 0``.

Con 20-50 tiendas la intersección es trivial.  Esta fuente no rankea productos:
es contexto de disponibilidad para el detalle (issue n), aunque
``availability_score`` queda disponible si la fusión decide usarla.
"""

from __future__ import annotations

from typing import List, Sequence

from spatial.geo import haversine, validate_point

from .sql import literal, rows
from .types import NearbyStore

FUENTE = "tiendas_cercanas"


def stores_with_product(
    engine,
    producto_id: int,
    center: Sequence[float],
    *,
    radius_m: float = 3000.0,
    limit: int = 10,
) -> List[NearbyStore]:
    """Tiendas dentro de ``radius_m`` del punto ``center`` con stock > 0."""
    if radius_m <= 0:
        raise ValueError("el radio debe ser positivo")
    lat, lon = validate_point(float(center[0]), float(center[1]))

    nearby = rows(
        engine,
        "SELECT id, nombre, lat, lon, distrito FROM tiendas "
        f"WHERE distancia(lat, POINT({literal(lat)}, {literal(lon)}), HAVERSINE) "
        f"< {literal(float(radius_m))}",
        "tiendas: radio",
    )
    stock = rows(
        engine,
        "SELECT tienda_id, cantidad FROM stock "
        f"WHERE producto_id = {literal(int(producto_id))} AND cantidad > 0",
        "tiendas: stock del producto",
    )
    quantity_by_store = {int(row["tienda_id"]): int(row["cantidad"]) for row in stock}

    stores: List[NearbyStore] = []
    for row in nearby:
        tienda_id = int(row["id"])
        if tienda_id not in quantity_by_store:
            continue
        store_lat, store_lon = float(row["lat"]), float(row["lon"])
        stores.append(
            NearbyStore(
                tienda_id=tienda_id,
                nombre=str(row["nombre"]),
                lat=store_lat,
                lon=store_lon,
                distrito=str(row["distrito"]),
                distancia_m=haversine((lat, lon), (store_lat, store_lon)),
                cantidad=quantity_by_store[tienda_id],
            )
        )

    stores.sort(key=lambda item: (item.distancia_m, item.tienda_id))
    return stores[: max(0, int(limit))]


def availability_score(stores: Sequence[NearbyStore]) -> float:
    """Puntaje opcional para la fusión: 1 en la tienda, decae con la distancia.

    ``1 / (1 + d_km)`` vale 1 si hay stock en el mismo punto y 0.5 a 1 km.
    Devuelve 0 si no hay tiendas.  Ojo: premia densidad comercial, no gusto.
    """
    if not stores:
        return 0.0
    return 1.0 / (1.0 + stores[0].distancia_m / 1000.0)
