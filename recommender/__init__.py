"""Recomendador de la Parte 5.

Las fuentes de Persona 4 son i, j, k; la fuente visual (g/h) vive en
``recommender.visual`` y comparte el mismo contrato ``Recommendation``.
La fusión de puntajes y los endpoints son de Persona 5.
"""

from .copurchase import recommend_by_copurchase
from .metadata import recommend_by_metadata
from .schema import DDL, create_schema
from .stores import stores_with_product
from .types import NearbyStore, Recommendation
from .visual import (
    product_embedding,
    recommend_by_visual,
    search_by_image,
)

__all__ = [
    "DDL",
    "NearbyStore",
    "Recommendation",
    "create_schema",
    "product_embedding",
    "recommend_by_copurchase",
    "recommend_by_metadata",
    "recommend_by_visual",
    "search_by_image",
    "stores_with_product",
]
