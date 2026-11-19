"""Recomendador de la Parte 5: fuentes de la Persona 4 (issues i, j, k).

Este paquete **no** fusiona puntajes ni expone endpoints: eso es de la Persona 5
(issue l).  Cada fuente devuelve una lista ordenada de ``Recommendation`` con
``{producto_id, score}`` y la evidencia cruda para que la fusión pueda
normalizar sin volver a consultar el motor.
"""

from .copurchase import recommend_by_copurchase
from .metadata import recommend_by_metadata
from .schema import DDL, create_schema
from .stores import stores_with_product
from .types import NearbyStore, Recommendation

__all__ = [
    "DDL",
    "NearbyStore",
    "Recommendation",
    "create_schema",
    "recommend_by_copurchase",
    "recommend_by_metadata",
    "stores_with_product",
]
