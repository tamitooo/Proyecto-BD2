"""Arma el dataset de productos de la tienda con Amazon Berkeley Objects (ABO).

ABO (https://amazon-berkeley-objects.s3.amazonaws.com/index.html) son productos
reales de Amazon con licencia CC BY-NC 4.0. Se eligen productos con nombre y
descripción en español de 8 categorías que se compran juntas. ABO no trae
precios: se generan por categoría con una semilla fija.

    python -m tools.preparar_abo --raw data/abo_raw --salida data/tienda_abo

Descarga solo la metadata (unos 90 MB) y las imágenes elegidas (versión de
256 px). Escribe productos.csv, imagenes/ (JPEG de 160x160 con bordes blancos),
modelo/bow_image.npz (vocabulario BoVW entrenado con esas imágenes), origen.csv
(id de ABO de cada producto) y LICENCIA.txt.
"""
from __future__ import annotations

import argparse
import csv
import glob
import gzip
import hashlib
import html
import io
import json
import math
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

from tools.generate_part5_data import PRODUCT_FIELDS, read_products
from vector.bow import model_path, train_model
from vector.extract_features import ExtractFeatures
from vector.sift import sift_backend

BASE = "https://amazon-berkeley-objects.s3.amazonaws.com"
LISTINGS = [f"listings/metadata/listings_{c}.json.gz" for c in "0123456789abcdef"]
IMAGES_META = "images/metadata/images.csv.gz"

CATEGORIAS = {
    "CHAIR": "sillas",
    "TABLE": "mesas",
    "SOFA": "sofas",
    "PILLOW": "cojines",
    "RUG": "alfombras",
    "LAMP": "lamparas",
    "LIGHT_FIXTURE": "lamparas",
    "SHOES": "calzado",
    "FINERING": "joyas",
    "FINENECKLACEBRACELETANKLET": "joyas",
    "FINEEARRING": "joyas",
}
# Rango de precio en soles por categoría (mínimo, máximo).
PRECIOS = {
    "sillas": (120, 900), "mesas": (180, 1500), "sofas": (900, 4500),
    "cojines": (25, 150), "alfombras": (90, 1200), "lamparas": (60, 650),
    "calzado": (80, 450), "joyas": (50, 900),
}
LADO = 160
MAX_NOMBRE = 120
MAX_DESCRIPCION = 700
# ABO a veces repite la marca pegada ("Amazon CollectionAmazon Collection ...").
PREFIJOS = re.compile(r"^(\s*(amazon\s*basics|amazon\s*commercial|amazon\s+essentials|amazon\s+collection)\s*[-–—:.]?)+\s*", re.I)
# Etiqueta de ABO que aparece al inicio o en medio del nombre ("find. Amazon Brand – ...").
MARCA_AMAZON = re.compile(r"\b(marca\s+(de\s+)?amazon|amazon\s+brand)\b\s*[-–—:.,]?\s*", re.I)
EXCLUIR = re.compile(r"\b(muestra|muestreo|swatch|renovad[oa])\b|\d{8}-\d{2}", re.I)
# Traducciones automáticas de ABO que cambiaron el nombre de la marca.
MARCAS = ((re.compile(r"\bRemache\b"), "Rivet"), (re.compile(r"^La soluci[oó]n\b"), "The Fix"))
# En muebles, una imagen casi lisa es una muestra de tela, no el producto.
MUEBLES = {"sillas", "mesas", "sofas", "cojines", "alfombras"}
MIN_CONTRASTE = 10
# EXTRACT_FEATURES falla si SIFT no encuentra descriptores.
MIN_DESCRIPTORES = 8
PALABRAS_VISUALES = 64


def descargar(raw: Path) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    for key in LISTINGS + [IMAGES_META]:
        destino = raw / Path(key).name
        if not destino.is_file():
            with urllib.request.urlopen(f"{BASE}/{key}", timeout=120) as r:
                destino.write_bytes(r.read())


def _valores(d: dict, campo: str, prefijo: str) -> list[str]:
    return [html.unescape(x["value"]).strip() for x in d.get(campo, [])
            if x.get("language_tag", "").startswith(prefijo) and x.get("value", "").strip()]


def _recortar(texto: str, limite: int) -> str:
    if len(texto.encode("utf-8")) <= limite:
        return texto
    corte = texto.encode("utf-8")[:limite].decode("utf-8", "ignore")
    return corte.rsplit(" ", 1)[0].rstrip(" ,;:-")


def _llave(semilla: int, item_id: str) -> str:
    return hashlib.sha256(f"{semilla}:{item_id}".encode()).hexdigest()


def candidatos(raw: Path, semilla: int) -> dict[str, list[dict]]:
    por_categoria: dict[str, list[dict]] = {c: [] for c in set(CATEGORIAS.values())}
    for archivo in sorted(glob.glob(str(raw / "listings_*.json.gz"))):
        with gzip.open(archivo, "rt", encoding="utf-8") as f:
            for linea in f:
                d = json.loads(linea)
                tipo = (d.get("product_type") or [{}])[0].get("value")
                categoria = CATEGORIAS.get(tipo)
                if not categoria or not d.get("main_image_id"):
                    continue
                nombres = _valores(d, "item_name", "es")
                vinetas = _valores(d, "bullet_point", "es")
                if not nombres or not vinetas:
                    continue
                nombre = PREFIJOS.sub("", MARCA_AMAZON.sub("", nombres[0])).strip(" -–—:,")
                for patron, marca in MARCAS:
                    nombre = patron.sub(marca, nombre)
                if EXCLUIR.search(nombre) or len(nombre) < 8:
                    continue
                nombre = _recortar(nombre, MAX_NOMBRE)
                descripcion = _recortar(" ".join(v.rstrip(".") + "." for v in vinetas), MAX_DESCRIPCION)
                por_categoria[categoria].append({
                    "item_id": d["item_id"], "imagen_id": d["main_image_id"],
                    "nombre": nombre, "descripcion": descripcion, "categoria": categoria,
                })
    for lista in por_categoria.values():
        lista.sort(key=lambda p: _llave(semilla, p["item_id"]))
    return por_categoria


def elegir(por_categoria: dict[str, list[dict]], por_cat: int) -> list[dict]:
    """Quita variantes (misma imagen o mismo nombre antes de la primera coma)."""
    elegidos = []
    imagenes = set()
    for categoria in sorted(por_categoria):
        raices = set()
        n = 0
        for p in por_categoria[categoria]:
            raiz = re.sub(r"\W+", " ", p["nombre"].split(",")[0].casefold()).strip()
            if p["imagen_id"] in imagenes or raiz in raices:
                continue
            imagenes.add(p["imagen_id"])
            raices.add(raiz)
            elegidos.append(p)
            n += 1
            if n == por_cat:
                break
    return elegidos


def precio(semilla: int, p: dict) -> float:
    bajo, alto = PRECIOS[p["categoria"]]
    u = int(_llave(semilla + 1, p["item_id"])[:8], 16) / 0xFFFFFFFF
    valor = math.exp(math.log(bajo) + u * (math.log(alto) - math.log(bajo)))
    return math.floor(valor) + 0.9


def rutas_imagen(raw: Path, ids: set[str]) -> dict[str, str]:
    rutas = {}
    with gzip.open(raw / Path(IMAGES_META).name, "rt", encoding="utf-8", newline="") as f:
        for fila in csv.DictReader(f):
            if fila["image_id"] in ids:
                rutas[fila["image_id"]] = fila["path"]
    return rutas


def _bajar_imagen(args: tuple[Path, str]) -> tuple[str, bytes | None]:
    cache, ruta = args
    destino = cache / ruta.replace("/", "_")
    if destino.is_file():
        return ruta, destino.read_bytes()
    try:
        with urllib.request.urlopen(f"{BASE}/images/small/{ruta}", timeout=60) as r:
            datos = r.read()
    except OSError:
        return ruta, None
    destino.write_bytes(datos)
    return ruta, datos


def normalizar(datos: bytes) -> Image.Image:
    with Image.open(io.BytesIO(datos)) as img:
        img = ImageOps.contain(img.convert("RGB"), (LADO, LADO))
    lienzo = Image.new("RGB", (LADO, LADO), "white")
    lienzo.paste(img, ((LADO - img.width) // 2, (LADO - img.height) // 2))
    return lienzo


def preparar(*, raw: Path, salida: Path, por_cat: int = 400, semilla: int = 2026,
             palabras: int = PALABRAS_VISUALES, hilos: int = 8) -> dict:
    if salida.exists():
        raise FileExistsError(salida)
    descargar(raw)
    elegidos = elegir(candidatos(raw, semilla), por_cat)
    rutas = rutas_imagen(raw, {p["imagen_id"] for p in elegidos})
    cache = raw / "imagenes_small"
    cache.mkdir(exist_ok=True)
    trabajos = [(cache, rutas[p["imagen_id"]]) for p in elegidos if p["imagen_id"] in rutas]
    with ThreadPoolExecutor(hilos) as pool:
        bajadas = dict(pool.map(_bajar_imagen, trabajos))

    (salida / "imagenes").mkdir(parents=True)
    filas, origen, documentos = [], [], []
    for p in elegidos:
        datos = bajadas.get(rutas.get(p["imagen_id"], ""))
        if not datos:
            continue
        try:
            imagen = normalizar(datos)
        except OSError:
            continue
        if (p["categoria"] in MUEBLES
                and ImageStat.Stat(imagen.convert("L")).stddev[0] < MIN_CONTRASTE):
            continue
        pid = len(filas) + 1
        archivo = f"abo_{pid:05d}.jpg"
        ruta = salida / "imagenes" / archivo
        imagen.save(ruta, format="JPEG", quality=88)
        descriptores = ExtractFeatures.local_descriptors(ruta, kind="image")
        if descriptores.shape[0] < MIN_DESCRIPTORES:
            ruta.unlink()
            continue
        documentos.append(descriptores)
        filas.append([pid, p["nombre"], p["categoria"], precio(semilla, p), p["descripcion"], archivo])
        origen.append([pid, p["item_id"], p["imagen_id"]])

    with (salida / "productos.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(PRODUCT_FIELDS)
        w.writerows(filas)
    with (salida / "origen.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(("id", "abo_item_id", "abo_image_id"))
        w.writerows(origen)
    (salida / "LICENCIA.txt").write_text(
        "Productos e imágenes: Amazon Berkeley Objects (ABO), Amazon.com, licencia CC BY-NC 4.0\n"
        "https://amazon-berkeley-objects.s3.amazonaws.com/index.html\n"
        "Cambios: selección de productos, nombre y descripción en español tomados de ABO,\n"
        "imágenes reducidas a 160x160 con bordes blancos. Los precios NO son de Amazon:\n"
        f"se generaron por categoría con semilla {semilla}.\n", encoding="utf-8")
    read_products(salida / "productos.csv", image_dir=salida / "imagenes")
    modelo = train_model("image", documentos, palabras, seed=semilla,
                         descriptor_backend=sift_backend())
    modelo.save(model_path(salida / "modelo", "image"))
    conteo: dict[str, int] = {}
    for fila in filas:
        conteo[fila[2]] = conteo.get(fila[2], 0) + 1
    return {"productos": len(filas), "por_categoria": dict(sorted(conteo.items())),
            "descartados": len(elegidos) - len(filas),
            "vocabulario": f"{modelo.n_words} palabras ({sift_backend()})"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--raw", type=Path, default=Path("data/abo_raw"))
    p.add_argument("--salida", type=Path, default=Path("data/tienda_abo"))
    p.add_argument("--por-categoria", type=int, default=400)
    p.add_argument("--semilla", type=int, default=2026)
    p.add_argument("--palabras", type=int, default=PALABRAS_VISUALES, help="K del vocabulario BoVW")
    a = p.parse_args(argv)
    print(json.dumps(preparar(raw=a.raw, salida=a.salida, por_cat=a.por_categoria,
                              semilla=a.semilla, palabras=a.palabras), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
