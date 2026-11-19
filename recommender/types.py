"""Tipos de salida de las fuentes del recomendador (Persona 4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(frozen=True)
class Recommendation:
    """Un producto recomendado por una fuente.

    ``score`` siempre es "más alto = más recomendado" y queda en ``(0, 1]``
    para las fuentes de esta persona.  ``evidencia`` conserva los valores
    crudos (conteos, precios, distancias) para auditar la fusión.
    """

    producto_id: int
    score: float
    fuente: str
    evidencia: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "producto_id": self.producto_id,
            "score": round(self.score, 6),
            "fuente": self.fuente,
            "evidencia": dict(self.evidencia),
        }


@dataclass(frozen=True)
class NearbyStore:
    """Una tienda que tiene stock del producto y cae dentro del radio."""

    tienda_id: int
    nombre: str
    lat: float
    lon: float
    distrito: str
    distancia_m: float
    cantidad: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "tienda_id": self.tienda_id,
            "nombre": self.nombre,
            "lat": self.lat,
            "lon": self.lon,
            "distrito": self.distrito,
            "distancia_m": round(self.distancia_m, 1),
            "cantidad": self.cantidad,
        }
