"""Esquema de la Parte 5 (contrato compartido del equipo).

El motor **no infiere el esquema desde CSV**: cada tabla se declara antes con
``CREATE TABLE`` y una clave primaria de una sola columna.  Por eso este
archivo es el contrato que deben usar las cinco personas, no el dataset.

El orden de columnas de ``productos`` coincide con
``tools/seed_tienda.py`` (``id, nombre, categoria, precio, descripcion,
imagen, embedding``): ese cargador usa ``INSERT ... VALUES`` sin lista de
columnas, así que un orden distinto intercambiaría categoría y precio.
``compras.fecha`` es ``VARCHAR(10)`` (``YYYY-MM-DD``) porque así viene en
``examples/tienda/compras.csv``.
"""

from __future__ import annotations

from typing import Dict

from .sql import RecommenderError

DDL: Dict[str, str] = {
    "productos": (
        "CREATE TABLE productos ("
        "id INT, nombre VARCHAR(96), categoria VARCHAR(32), precio FLOAT, "
        "descripcion VARCHAR(1024), imagen VARCHAR(160), embedding VARCHAR(2048))"
    ),
    "tiendas": (
        "CREATE TABLE tiendas ("
        "id INT, nombre VARCHAR(64), lat FLOAT, lon FLOAT, distrito VARCHAR(32))"
    ),
    "stock": (
        "CREATE TABLE stock (id INT, tienda_id INT, producto_id INT, cantidad INT)"
    ),
    "compras": (
        "CREATE TABLE compras ("
        "id INT, usuario_id INT, producto_id INT, fecha VARCHAR(10), cantidad INT)"
    ),
}

TABLAS = tuple(DDL)


def create_schema(engine) -> None:
    """Crea las tablas que falten; no toca las existentes."""
    for table in TABLAS:
        if _has_table(engine, table):
            continue
        result = engine.run(DDL[table])
        if not result.success:
            raise RecommenderError(f"no se pudo crear {table}: {result.error}")


def _has_table(engine, name: str) -> bool:
    catalog = getattr(engine, "catalog", None)
    if catalog is not None and hasattr(catalog, "has_table"):
        return catalog.has_table(name)
    return False
