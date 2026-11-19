"""Issue j: productos relacionados por metadatos (misma categoría, precio similar).

Una sola consulta al motor (``WHERE categoria = ... AND id <> X``) y el puntaje
se calcula en Python para que sea continuo:

    score = 1 / (1 + |precio - precio_X| / max(precio_X, 1))

Un "misma categoría" binario produce empates masivos y, al fusionarse,
convierte el top-10 en un sorteo; esta fórmula ordena por cercanía de precio
dentro de la categoría.
"""

from __future__ import annotations

from typing import List

from .sql import literal, one, rows
from .types import Recommendation

FUENTE = "metadatos"


def recommend_by_metadata(engine, producto_id: int, *, k: int = 10) -> List[Recommendation]:
    if k <= 0:
        return []

    anchor = one(
        engine,
        f"SELECT categoria, precio FROM productos WHERE id = {literal(int(producto_id))}",
        "metadatos: producto ancla",
    )
    if anchor is None:
        return []

    categoria = str(anchor["categoria"])
    precio_ancla = float(anchor["precio"])
    denominator = max(abs(precio_ancla), 1.0)

    candidates = rows(
        engine,
        "SELECT id, precio FROM productos "
        f"WHERE categoria = {literal(categoria)} "
        f"AND id <> {literal(int(producto_id))}",
        "metadatos: misma categoría",
    )

    recommendations = []
    for row in candidates:
        precio = float(row["precio"])
        delta = abs(precio - precio_ancla)
        recommendations.append(
            Recommendation(
                producto_id=int(row["id"]),
                score=1.0 / (1.0 + delta / denominator),
                fuente=FUENTE,
                evidencia={
                    "categoria": categoria,
                    "precio": precio,
                    "precio_ancla": precio_ancla,
                    "delta_precio": delta,
                },
            )
        )

    recommendations.sort(key=lambda item: (-item.score, item.producto_id))
    return recommendations[:k]
