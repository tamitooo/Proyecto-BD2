"""Issue i: "usuarios que compraron X también compraron Y".

El motor no admite alias ni autounión de ``compras`` (``query/sql_parser.py``
solo acepta ``JOIN tabla ON col = col`` sin alias, y evalúa el ``WHERE`` antes
del join), así que la fuente se resuelve con tres consultas simples y la
agregación se termina en Python:

1. compradores de X;
2. sus pares ``(usuario, producto)`` con ``GROUP BY usuario_id, producto_id``
   en el motor, para que cada comprador cuente una sola vez aunque el
   historial repita la compra;
3. historial del usuario actual, para no recomendar lo que ya tiene.

El motor no implementa ``COUNT(DISTINCT)``: la consulta 2 agrupa por los dos
campos y el conteo de personas se termina en Python.  Así el puntaje queda en
``(0, 1]`` aunque ``compras`` tenga filas repetidas (la muestra real las tiene).
"""

from __future__ import annotations

from typing import Dict, List

from .sql import literal, rows
from .types import Recommendation

FUENTE = "co_compra"
MAX_BUYERS = 300


def recommend_by_copurchase(
    engine,
    producto_id: int,
    *,
    k: int = 10,
    usuario_id: int | None = None,
    max_buyers: int = MAX_BUYERS,
) -> List[Recommendation]:
    """Recomienda por co-compra del producto ``producto_id``.

    ``usuario_id`` (opcional) excluye los productos que ese usuario ya compró.
    ``max_buyers`` acota la lista ``OR`` de la segunda consulta: con muchos
    compradores el SQL crece y conviene materializar la tabla de pares.
    """
    if k <= 0:
        return []

    buyers = sorted(
        {
            int(row["usuario_id"])
            for row in rows(
                engine,
                f"SELECT usuario_id FROM compras WHERE producto_id = {literal(int(producto_id))}",
                "co-compra: compradores de X",
            )
        }
    )
    if not buyers:
        return []

    used = buyers[: max(1, int(max_buyers))]
    condition = " OR ".join(f"usuario_id = {literal(user)}" for user in used)
    # GROUP BY (usuario, producto) para que cada comprador cuente una sola vez:
    # la muestra real repite pares y COUNT(*) contaría compras, no personas.
    pairs = rows(
        engine,
        "SELECT usuario_id, producto_id, COUNT(*) AS compras FROM compras "
        f"WHERE {condition} GROUP BY usuario_id, producto_id",
        "co-compra: pares (comprador, producto)",
    )
    buyers_by_product: Dict[int, int] = {}
    purchases_by_product: Dict[int, int] = {}
    for row in pairs:
        product = int(row["producto_id"])
        if product == int(producto_id):
            continue
        buyers_by_product[product] = buyers_by_product.get(product, 0) + 1
        purchases_by_product[product] = purchases_by_product.get(product, 0) + int(row["compras"])

    owned = set()
    if usuario_id is not None:
        owned = {
            int(row["producto_id"])
            for row in rows(
                engine,
                f"SELECT producto_id FROM compras WHERE usuario_id = {literal(int(usuario_id))}",
                "co-compra: historial del usuario",
            )
        }

    total = len(used)
    recommendations = [
        Recommendation(
            producto_id=product,
            score=count / total,
            fuente=FUENTE,
            evidencia={
                "co": count,
                "compras": purchases_by_product.get(product, count),
                "compradores_usados": total,
                "compradores_totales": len(buyers),
            },
        )
        for product, count in buyers_by_product.items()
        if product not in owned
    ]
    recommendations.sort(key=lambda item: (-item.score, item.producto_id))
    return recommendations[:k]
