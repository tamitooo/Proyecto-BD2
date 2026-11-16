"""Genera la muestra de datos de la tienda (Parte 5) con semilla fija.

Sirve para desarrollar mientras llega el dataset real (#127, #128, #129): tiene
las mismas columnas, así que basta con reemplazar los CSV, las imágenes y el
modelo por los definitivos.

    productos.csv  id, nombre, categoria, precio, descripcion, imagen
    tiendas.csv    id, nombre, lat, lon, distrito
    stock.csv      id, tienda_id, producto_id, cantidad
    compras.csv    id, usuario_id, producto_id, fecha, cantidad
    imagenes/      una imagen PNG por producto (el nombre está en productos.imagen)
    modelo/        bow_image.npz, vocabulario BoVW entrenado con esas imágenes

Cada categoría tiene un patrón visual propio, así que la búsqueda visual agrupa
por categoría. Las compras siguen pares de categorías que se compran juntas
(laptop con mochila, celular con audífonos, zapatillas con reloj).

Uso, desde la raíz del repo (requiere numpy, Pillow y opencv-python-headless,
el mismo SIFT que usa el backend en Docker):

    python -m examples.tienda.generar_muestra
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw

from vector.bow import model_path, train_model
from vector.extract_features import ExtractFeatures
from vector.sift import sift_backend

AQUI = Path(__file__).resolve().parent
SEMILLA = 2026
LADO = 160
PALABRAS_VISUALES = 16
POR_CATEGORIA = 5
MIN_DESCRIPTORES = 8
USUARIOS = 40
COMPRAS = 200

CATEGORIAS = {
    "laptops": {
        "marcas": ["HP", "Lenovo", "Asus", "Acer", "Dell"],
        "modelos": ["15", "ThinkPad 14", "VivoBook 16", "Aspire 5", "Inspiron 13"],
        "precio": (1800, 5200),
        "texto": "laptop portátil con procesador rápido, memoria RAM, disco SSD y pantalla para trabajo y estudio",
        "extras": ["16 GB de RAM", "teclado retroiluminado", "tarjeta gráfica dedicada", "pantalla táctil", "lector de huella", "batería de 10 horas", "ideal para programar", "ligera y delgada"],
    },
    "celulares": {
        "marcas": ["Samsung", "Xiaomi", "Motorola", "Apple", "Honor"],
        "modelos": ["Galaxy A55", "Redmi Note 13", "Moto G84", "iPhone 13", "Magic 6"],
        "precio": (700, 3900),
        "texto": "celular smartphone con cámara de alta resolución, batería de larga duración y pantalla brillante",
        "extras": ["carga rápida", "5G", "256 GB de almacenamiento", "resistente al agua", "triple cámara", "pantalla AMOLED", "ideal para fotos", "doble SIM"],
    },
    "audifonos": {
        "marcas": ["Sony", "JBL", "Xiaomi", "Apple", "Logitech"],
        "modelos": ["WH-1000", "Tune 520", "Buds 5", "AirPods", "G435"],
        "precio": (90, 1400),
        "texto": "audífonos inalámbricos bluetooth con cancelación de ruido, micrófono y sonido nítido para música",
        "extras": ["estuche de carga", "modo ambiente", "graves potentes", "resistentes al sudor", "plegables", "ideal para gaming", "conexión multipunto", "30 horas de batería"],
    },
    "mochilas": {
        "marcas": ["Samsonite", "Totto", "Xiaomi", "Targus", "North Face"],
        "modelos": ["Urban", "Campus", "Commuter", "Classic", "Borealis"],
        "precio": (80, 450),
        "texto": "mochila resistente al agua con compartimento acolchado para laptop, bolsillos y correas cómodas",
        "extras": ["puerto USB de carga", "bolsillo antirrobo", "espalda acolchada", "capacidad de 30 litros", "ideal para viajes", "tela reflectante", "cierre reforzado", "compartimento para tablet"],
    },
    "zapatillas": {
        "marcas": ["Nike", "Adidas", "Puma", "New Balance", "Asics"],
        "modelos": ["Revolution", "Runfalcon", "Velocity", "574", "Gel Contend"],
        "precio": (180, 650),
        "texto": "zapatillas deportivas para correr con suela amortiguada, malla transpirable y ajuste ligero",
        "extras": ["ideal para maratón", "suela antideslizante", "plantilla de memoria", "diseño urbano", "talla ancha", "ligeras para entrenar", "refuerzo en el talón", "para trail"],
    },
    "relojes": {
        "marcas": ["Casio", "Garmin", "Xiaomi", "Huawei", "Amazfit"],
        "modelos": ["G-Shock", "Forerunner 55", "Smart Band 8", "Watch Fit 3", "Bip 5"],
        "precio": (120, 1500),
        "texto": "reloj deportivo con monitor de ritmo cardiaco, GPS, contador de pasos y batería de varios días",
        "extras": ["monitor de sueño", "resistente al agua", "pantalla AMOLED", "notificaciones del celular", "modo natación", "oxígeno en sangre", "correa de silicona", "ideal para correr"],
    },
}

COMPRADOS_JUNTOS = [("laptops", "mochilas"), ("celulares", "audifonos"), ("zapatillas", "relojes")]

TIENDAS = [
    ("Tienda Miraflores", -12.1211, -77.0297, "Miraflores"),
    ("Tienda San Isidro", -12.0975, -77.0365, "San Isidro"),
    ("Tienda Surco", -12.1460, -76.9920, "Santiago de Surco"),
    ("Tienda La Molina", -12.0790, -76.9420, "La Molina"),
    ("Tienda Los Olivos", -11.9920, -77.0700, "Los Olivos"),
]


def _color(r: random.Random) -> tuple[int, int, int]:
    return (r.randint(20, 200), r.randint(20, 200), r.randint(20, 200))


def _imagen(categoria: str, r: random.Random) -> Image.Image:
    fondo = r.randint(215, 245)
    img = Image.new("RGB", (LADO, LADO), (fondo, fondo, fondo))
    d = ImageDraw.Draw(img)
    c = _color(r)
    if categoria == "laptops":
        paso = r.randint(18, 30)
        for y in range(0, LADO, paso):
            for x in range(0, LADO, paso):
                if (x // paso + y // paso) % 2 == 0:
                    d.rectangle([x, y, x + paso - 1, y + paso - 1], fill=c)
    elif categoria == "celulares":
        x = r.randint(0, 12)
        while x < LADO:
            ancho = r.randint(6, 14)
            d.rounded_rectangle([x, 10, x + ancho, LADO - 10], radius=4, fill=c)
            x += ancho + r.randint(8, 16)
    elif categoria == "audifonos":
        for _ in range(r.randint(5, 8)):
            cx, cy, radio = r.randint(20, 140), r.randint(20, 140), r.randint(12, 30)
            d.ellipse([cx - radio, cy - radio, cx + radio, cy + radio], outline=c, width=r.randint(4, 7))
    elif categoria == "mochilas":
        for _ in range(r.randint(7, 12)):
            x, y, t = r.randint(0, 130), r.randint(0, 130), r.randint(18, 34)
            d.polygon([(x, y + t), (x + t // 2, y), (x + t, y + t)], fill=c)
    elif categoria == "zapatillas":
        for _ in range(r.randint(10, 16)):
            x, y, largo = r.randint(0, 140), r.randint(0, 140), r.randint(16, 32)
            d.line([(x, y), (x + largo, y + largo)], fill=c, width=r.randint(5, 9))
    elif categoria == "relojes":
        for _ in range(r.randint(8, 14)):
            cx, cy, radio = r.randint(10, 150), r.randint(10, 150), r.randint(6, 14)
            d.ellipse([cx - radio, cy - radio, cx + radio, cy + radio], fill=c)
            d.line([(cx, cy), (cx + radio, cy - radio)], fill=(0, 0, 0), width=2)
    return img


def _imagen_con_textura(categoria: str, r: random.Random, ruta: Path):
    """Repite hasta que SIFT encuentre descriptores; si no, EXTRACT_FEATURES falla."""
    for _ in range(50):
        _imagen(categoria, r).save(ruta)
        descriptores = ExtractFeatures.local_descriptors(ruta, kind="image")
        if descriptores.shape[0] >= MIN_DESCRIPTORES:
            return descriptores
    raise RuntimeError(f"el patrón de '{categoria}' no da descriptores SIFT")


def _escribir(nombre: str, columnas: list[str], filas: list[list]) -> None:
    with open(AQUI / nombre, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(columnas)
        w.writerows(filas)


def generar() -> None:
    r = random.Random(SEMILLA)
    carpeta = AQUI / "imagenes"
    carpeta.mkdir(exist_ok=True)

    productos, documentos, por_categoria = [], [], {c: [] for c in CATEGORIAS}
    for categoria, info in CATEGORIAS.items():
        for i in range(POR_CATEGORIA):
            pid = len(productos) + 1
            imagen = f"producto_{pid:03d}.png"
            documentos.append(_imagen_con_textura(categoria, r, carpeta / imagen))
            precio = round(r.uniform(*info["precio"]), 2)
            nombre = f"{info['marcas'][i]} {info['modelos'][i]}"
            extras = ", ".join(r.sample(info["extras"], r.randint(2, 3)))
            descripcion = f"{nombre}: {info['texto']}; {extras}."
            productos.append([pid, nombre, categoria, precio, descripcion, imagen])
            por_categoria[categoria].append(pid)

    tiendas = [[i + 1, *t] for i, t in enumerate(TIENDAS)]

    stock = []
    for p in productos:
        for tienda in sorted(r.sample(range(1, len(TIENDAS) + 1), r.randint(2, 4))):
            stock.append([len(stock) + 1, tienda, p[0], r.randint(1, 25)])

    compras, inicio = [], date(2026, 9, 1)
    while len(compras) < COMPRAS:
        usuario = r.randint(1, USUARIOS)
        a, b = r.choice(COMPRADOS_JUNTOS)
        cesta = [r.choice(por_categoria[a]), r.choice(por_categoria[b])]
        if r.random() < 0.3:
            cesta.append(r.choice(productos)[0])
        dia = inicio + timedelta(days=r.randint(0, 60))
        for producto in cesta[: COMPRAS - len(compras)]:
            compras.append([len(compras) + 1, usuario, producto, dia.isoformat(), r.randint(1, 2)])

    _escribir("productos.csv", ["id", "nombre", "categoria", "precio", "descripcion", "imagen"], productos)
    _escribir("tiendas.csv", ["id", "nombre", "lat", "lon", "distrito"], tiendas)
    _escribir("stock.csv", ["id", "tienda_id", "producto_id", "cantidad"], stock)
    _escribir("compras.csv", ["id", "usuario_id", "producto_id", "fecha", "cantidad"], compras)

    modelo = train_model("image", documentos, PALABRAS_VISUALES, seed=SEMILLA, descriptor_backend=sift_backend())
    modelo.save(model_path(AQUI / "modelo", "image"))
    print(f"{len(productos)} productos, {len(tiendas)} tiendas, {len(stock)} filas de stock, "
          f"{len(compras)} compras; vocabulario de {modelo.n_words} palabras ({sift_backend()})")


if __name__ == "__main__":
    generar()
