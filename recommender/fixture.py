"""Fixture determinista para las fuentes de la Persona 4.

No es el dataset del proyecto: es una muestra pequeña con estructura conocida
para que ``i``, ``j`` y ``k`` se puedan probar sin esperar la carga completa.
El dataset real se carga con ``tools/seed_tienda.py`` desde ``examples/tienda``.

El orden de cada fila de ``productos`` es el de ``recommender/schema.py`` y el
de ``tools/seed_tienda.py``: ``id, nombre, categoria, precio, descripcion,
imagen, embedding``.

Estructura de compras (una fila por ``usuario_id`` y ``producto_id``, como
exige el contrato de datos):

* usuarios 1, 2 y 3 compran los productos 1, 2 y 3;
* usuarios 4 y 5 compran 1 y 4;
* el usuario 6 compra solo 1;
* usuarios 7 y 8 compran 2 y 3;
* el usuario 9 compra 14 y 15 (control: no toca la laptop 1).

Con eso, los compradores de 1 son 6 y la co-compra queda:
``2 -> 3/6``, ``3 -> 3/6`` y ``4 -> 2/6``.
"""

from __future__ import annotations

from typing import Any, Dict, Sequence, Tuple

from .sql import literal, run

# (id, nombre, categoria, precio, descripcion, imagen, embedding)
PRODUCTOS: Tuple[Tuple[Any, ...], ...] = (
    (1, "Laptop HP 15", "Laptops", 2500.0,
     "Laptop HP 15 con procesador Intel Core i5, 8 GB de RAM y 512 GB SSD para trabajo diario.",
     "laptop_hp_15.jpg", ""),
    (2, "Laptop Lenovo IdeaPad", "Laptops", 2600.0,
     "Laptop Lenovo IdeaPad con pantalla de 15 pulgadas, 16 GB de RAM y teclado retroiluminado.",
     "laptop_lenovo_ideapad.jpg", ""),
    (3, "Laptop Dell Inspiron", "Laptops", 3100.0,
     "Laptop Dell Inspiron con procesador Ryzen 7, 16 GB de RAM y tarjeta grafica dedicada.",
     "laptop_dell_inspiron.jpg", ""),
    (4, "Laptop Acer Aspire", "Laptops", 1800.0,
     "Laptop Acer Aspire economica con 8 GB de RAM y 256 GB SSD para estudiantes.",
     "laptop_acer_aspire.jpg", ""),
    (5, "Laptop Apple MacBook Air", "Laptops", 4200.0,
     "Laptop Apple MacBook Air con chip M2, pantalla Liquid Retina y bateria de larga duracion.",
     "laptop_macbook_air.jpg", ""),
    (6, "Laptop Asus VivoBook", "Laptops", 2550.0,
     "Laptop Asus VivoBook delgada con 8 GB de RAM, 512 GB SSD y pantalla Full HD.",
     "laptop_asus_vivobook.jpg", ""),
    (7, "Laptop Toshiba Satellite", "Laptops", 1990.0,
     "Laptop Toshiba Satellite con disco duro de 1 TB y pantalla de 14 pulgadas.",
     "laptop_toshiba_satellite.jpg", ""),
    (8, "Celular Samsung Galaxy A54", "Celulares", 1200.0,
     "Celular Samsung Galaxy A54 con camara de 50 MP, 128 GB y bateria de 5000 mAh.",
     "celular_samsung_a54.jpg", ""),
    (9, "Celular Xiaomi Redmi Note 13", "Celulares", 1350.0,
     "Celular Xiaomi Redmi Note 13 con pantalla AMOLED, 256 GB y carga rapida.",
     "celular_xiaomi_note13.jpg", ""),
    (10, "Celular Motorola Moto G54", "Celulares", 900.0,
     "Celular Motorola Moto G54 con 128 GB, camara de 50 MP y sonido estereo.",
     "celular_moto_g54.jpg", ""),
    (11, "Celular Apple iPhone 15", "Celulares", 3500.0,
     "Celular Apple iPhone 15 con chip A16, camara de 48 MP y conector USB-C.",
     "celular_iphone_15.jpg", ""),
    (12, "Celular Honor X8", "Celulares", 1100.0,
     "Celular Honor X8 con 128 GB, pantalla de 90 Hz y carga de 22.5 W.",
     "celular_honor_x8.jpg", ""),
    (13, "Celular ZTE Blade A73", "Celulares", 980.0,
     "Celular ZTE Blade A73 con 128 GB, bateria de 5000 mAh y Android actualizado.",
     "celular_zte_a73.jpg", ""),
    (14, "Audifono Sony WH-1000XM5", "Audio", 1200.0,
     "Audifono Sony WH-1000XM5 con cancelacion de ruido activa y 30 horas de bateria.",
     "audifono_sony_xm5.jpg", ""),
    (15, "Audifono Bose QuietComfort", "Audio", 1500.0,
     "Audifono Bose QuietComfort con cancelacion de ruido y almohadillas de memoria.",
     "audifono_bose_qc.jpg", ""),
    (16, "Parlante JBL Flip 6", "Audio", 300.0,
     "Parlante JBL Flip 6 portatil, resistente al agua y con 12 horas de reproduccion.",
     "parlante_jbl_flip6.jpg", ""),
    (17, "Audifono Xiaomi Basic", "Audio", 90.0,
     "Audifono Xiaomi Basic inalambrico con estuche de carga y microfono integrado.",
     "audifono_xiaomi_basic.jpg", ""),
    (18, "Barra de sonido LG", "Audio", 850.0,
     "Barra de sonido LG con subwoofer inalambrico y conexion Bluetooth.",
     "barra_lg.jpg", ""),
    (19, "Parlante Alexa Echo Dot", "Audio", 200.0,
     "Parlante inteligente Alexa Echo Dot con control por voz y sonido compacto.",
     "parlante_echo_dot.jpg", ""),
    (20, "Audifono KZ EDX", "Audio", 75.0,
     "Audifono KZ EDX con drivers dinamicos y cable trenzado desmontable.",
     "audifono_kz_edx.jpg", ""),
)

# (id, nombre, lat, lon, distrito)
TIENDAS: Tuple[Tuple[Any, ...], ...] = (
    (1, "Tienda Centro", -12.0464, -77.0428, "Cercado de Lima"),
    (2, "Tienda San Isidro", -12.0364, -77.0428, "San Isidro"),
    (3, "Tienda Callao", -12.3464, -77.0428, "Callao"),
    (4, "Tienda Miraflores", -12.0644, -77.0428, "Miraflores"),
    (5, "Tienda Surco", -12.1464, -77.0428, "Santiago de Surco"),
)

# (id, tienda_id, producto_id, cantidad)
STOCK: Tuple[Tuple[int, int, int, int], ...] = (
    (1, 1, 1, 5),
    (2, 2, 1, 2),
    (3, 4, 1, 0),   # sin stock: no debe aparecer
    (4, 3, 2, 4),   # única tienda del producto 2, a ~33 km
    (5, 1, 3, 1),
    (6, 5, 14, 3),
)

# (id, usuario_id, producto_id, fecha YYYY-MM-DD, cantidad)
COMPRAS: Tuple[Tuple[int, int, int, str, int], ...] = (
    (1, 1, 1, "2026-01-05", 1), (2, 1, 2, "2026-01-05", 1), (3, 1, 3, "2026-01-06", 1),
    (4, 2, 1, "2026-01-05", 1), (5, 2, 2, "2026-01-07", 1), (6, 2, 3, "2026-01-07", 1),
    (7, 3, 1, "2026-01-08", 1), (8, 3, 2, "2026-01-08", 1), (9, 3, 3, "2026-01-09", 1),
    (10, 4, 1, "2026-01-10", 1), (11, 4, 4, "2026-01-10", 1),
    (12, 5, 1, "2026-01-11", 1), (13, 5, 4, "2026-01-12", 1),
    (14, 6, 1, "2026-01-13", 1),
    (15, 7, 2, "2026-01-13", 1), (16, 7, 3, "2026-01-14", 1),
    (17, 8, 2, "2026-01-14", 1), (18, 8, 3, "2026-01-15", 1),
    (19, 9, 14, "2026-01-15", 1), (20, 9, 15, "2026-01-16", 1),
)

SAMPLE: Dict[str, Sequence[Tuple[Any, ...]]] = {
    "productos": PRODUCTOS,
    "tiendas": TIENDAS,
    "stock": STOCK,
    "compras": COMPRAS,
}


def _count(engine, table: str) -> int:
    return sum(1 for _ in engine.catalog.get_table(table).storage.scan())


def load_sample(engine, *, replace: bool = False) -> Dict[str, int]:
    """Carga la muestra en las tablas vacías y devuelve filas insertadas."""
    inserted: Dict[str, int] = {}
    for table in ("productos", "tiendas", "stock", "compras"):
        if replace:
            run(engine, f"DELETE FROM {table}", f"limpiar {table}")
        elif _count(engine, table) > 0:
            inserted[table] = 0
            continue
        # El parser acepta un solo VALUES (...) por INSERT y no admite lista de
        # columnas: una sentencia por fila, en el orden del DDL.
        for row in SAMPLE[table]:
            values = ", ".join(literal(value) for value in row)
            run(
                engine,
                f"INSERT INTO {table} VALUES ({values})",
                f"cargar {table}",
            )
        inserted[table] = len(SAMPLE[table])
    return inserted
