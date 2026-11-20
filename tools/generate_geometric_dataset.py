"""Corpus de figuras etiquetadas para probar SIMILAR_TO / BoVW con SIFT.

Uso: python -m tools.generate_geometric_dataset --count 3000 --queries 90
Genera CSV de seis columnas compatible con el importador, imágenes 160x160,
etiquetas de referencia, consultas independientes, vocabulario e índices de
vectores precalculados. No altera el corpus antiguo de examples/tienda.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

# Intentionally no square/rectangle class. A board contains many scattered
# objects; the supervised label is the MOST FREQUENT shape, not a centred icon.
SHAPES = ("circulo", "triangulo", "pentagono", "estrella", "hexagono")
COLORS = {
    "rojo": (220, 65, 75),
    "verde": (53, 173, 105),
    "azul": (62, 122, 223),
    "amarillo": (226, 188, 50),
    "violeta": (158, 84, 202),
    "naranja": (230, 125, 47),
}
PRODUCT_COLUMNS = ("id", "nombre", "categoria", "precio", "descripcion", "imagen")
INDEXED_COLUMNS = (*PRODUCT_COLUMNS, "embedding")
LABEL_COLUMNS = ("id", "figura", "color", "angulo", "radio", "centro_x", "centro_y", "imagen",
                 "n_formas", "n_dominantes", "n_distractores", "escena_json")
QUERY_COLUMNS = ("id", "figura", "color", "imagen", "n_formas")


def _polygon_points(shape: str, cx: int, cy: int, radius: int, rotation: float) -> list[tuple[int, int]]:
    count = {"triangulo": 3, "pentagono": 5, "estrella": 10, "hexagono": 6}[shape]
    points = []
    for vertex in range(count):
        distance = radius * (0.45 if shape == "estrella" and vertex % 2 else 1)
        theta = math.radians(rotation + vertex * 360 / count)
        points.append((round(cx + distance * math.cos(theta)), round(cy + distance * math.sin(theta))))
    return points


def _draw_object(draw: ImageDraw.ImageDraw, obj: dict, scale: float) -> None:
    shape, cx, cy, radius = obj["figura"], obj["x"], obj["y"], obj["radio"]
    color = obj["rgb"]
    edge = (28, 38, 52)
    width = max(1, round(2 * scale))
    if shape == "circulo":
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color,
                     outline=edge, width=width)
        draw.ellipse((cx - radius * .48, cy - radius * .48,
                      cx + radius * .48, cy + radius * .48), outline=edge, width=width)
    else:
        points = _polygon_points(shape, cx, cy, radius, obj["angulo"])
        draw.polygon(points, fill=color)
        draw.line(points + [points[0]], fill=edge, width=width, joint="curve")
        # Angular strokes supply stable SIFT keypoints without drawing squares.
        for vertex in points[::2] if shape == "estrella" else points:
            draw.line(((cx, cy), (round(cx + .54 * (vertex[0] - cx)),
                                   round(cy + .54 * (vertex[1] - cy)))),
                      fill=(43, 51, 65), width=max(1, round(scale)))
    # All decoration consists of circular marks (never rectangular/square marks).
    dot = max(1, round(radius * .08))
    for offset, mul in ((0, .21), (127, .48), (243, .39)):
        t = math.radians(obj["angulo"] + offset)
        x = round(cx + radius * mul * math.cos(t))
        y = round(cy + radius * mul * math.sin(t))
        draw.ellipse((x-dot,y-dot,x+dot,y+dot),fill=(245,245,245),outline=edge,width=1)


def render_shape(shape: str, color: str, *, size: int, seed: int) -> tuple[Image.Image, dict]:
    """A random tabletop of 6-12 assorted shapes, with a dominant shape label.

    Deterministic per seed; centers are sampled independently (no lattice),
    objects vary in orientation/size/color, occasional overlaps are allowed.
    The dominant shape outnumbers *all other shapes combined*, so the category
    remains objectively defined even when the board contains distractors.
    """
    if shape not in SHAPES or color not in COLORS or size < 96:
        raise ValueError("figura/color no válido o lienzo menor que 96px")
    rng = random.Random(seed)
    scale = size / 160
    n_total = rng.randint(7, 12)
    n_primary = rng.randint((n_total // 2) + 2, n_total - 2)
    n_other = n_total - n_primary
    assert n_primary > n_other >= 2
    other_shapes = [s for s in SHAPES if s != shape]
    distractors = [other_shapes[i % len(other_shapes)] for i in range(n_other)]
    rng.shuffle(distractors)
    kinds = [shape] * n_primary + distractors
    rng.shuffle(kinds)

    bgcolor = rng.randint(235, 250)
    image = Image.new("RGB", (size, size), (bgcolor, bgcolor, bgcolor))
    draw = ImageDraw.Draw(image)
    placed = []
    for i, kind in enumerate(kinds):
        # Independently sampled positions make it look like objects tossed on a board.
        # Some overlap / edge cropping is intentional, not alignment to a grid.
        radius = round(rng.uniform(12, 27) * scale)
        if kind == shape and i == kinds.index(shape):
            radius = round(rng.uniform(23, 31) * scale)
        center_x = rng.randint(round(radius * .60), size - round(radius * .60))
        center_y = rng.randint(round(radius * .60), size - round(radius * .60))
        angle = rng.uniform(0, 360)
        if kind == shape and rng.random() < .84:
            hue = color
        else:
            hue = rng.choice(tuple(COLORS))
        rgb = tuple(max(0, min(255, channel + rng.randint(-22, 22))) for channel in COLORS[hue])
        obj = {"figura": kind, "color": hue, "x": center_x, "y": center_y,
               "radio": radius, "angulo": round(angle, 2), "rgb": rgb}
        _draw_object(draw, obj, scale)
        placed.append(obj)

    # Tiny circular pinholes/ink splashes make backgrounds less uniform while
    # adding texture; this intentionally uses no square or rectangular shapes.
    for _ in range(rng.randint(1, 6)):
        x, y = rng.randrange(size), rng.randrange(size)
        d = max(1, round(rng.uniform(.7, 1.7) * scale))
        draw.ellipse((x-d, y-d, x+d, y+d), fill=(rng.randint(105,170),)*3)

    primary = max((obj for obj in placed if obj["figura"] == shape), key=lambda obj: obj["radio"])
    scene = [{k: v for k, v in obj.items() if k != "rgb"} for obj in placed]
    return image, {
        "angulo": primary["angulo"], "radio": primary["radio"],
        "centro_x": primary["x"], "centro_y": primary["y"],
        "n_formas": n_total, "n_dominantes": n_primary,
        "n_distractores": n_other,
        "escena_json": json.dumps(scene, separators=(",", ":"), ensure_ascii=False),
    }


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _descriptors(path: Path):
    from vector.extract_features import ExtractFeatures
    return ExtractFeatures.local_descriptors(path, kind="image")


def _features(path: Path, model) -> str:
    from vector.extract_features import ExtractFeatures
    descriptors = ExtractFeatures.local_descriptors(path, kind="image")
    if not len(descriptors):
        raise ValueError(f"{path.name}: no se detectaron descriptores SIFT")
    vector = model.encode(descriptors)
    if not vector.any():
        raise ValueError(f"{path.name}: el vector BoVW quedó vacío")
    return json.dumps([round(float(v), 6) for v in vector], separators=(",", ":"))


def generate(*, output: Path, count: int = 3000, queries: int = 90,
             size: int = 160, seed: int = 2026, words: int = 32,
             training: int = 120, workers: int = 4) -> dict:
    """Produce datos etiquetados, modelo y vectores en directorio nuevo."""
    if not len(SHAPES) <= count <= 999999 or not len(SHAPES) <= queries <= 9999 or size < 96:
        raise ValueError("count/queries deben cubrir las figuras disponibles y size >= 96")
    if words < 2 or workers < 1 or training < 1:
        raise ValueError("words >= 2, workers >= 1 y training >= 1")
    from vector.sift import sift_backend
    backend = sift_backend()
    if backend != "opencv" and count > 100:
        raise RuntimeError("miles de imágenes requieren SIFT OpenCV: instala opencv-python-headless")
    output = Path(output)
    if any((output / file).exists() for file in ("productos.csv", "manifest.json")):
        raise FileExistsError(f"{output} ya contiene un corpus; elige otro --output")
    start = time.perf_counter()
    images = output / "imagenes"
    query_images = output / "consultas"
    images.mkdir(parents=True, exist_ok=True)
    query_images.mkdir(parents=True, exist_ok=True)
    products: list[dict] = []
    labels: list[dict] = []
    queries_data: list[dict] = []
    colors = tuple(COLORS)

    for i in range(count):
        product_id = i + 1
        shape = SHAPES[i % len(SHAPES)]
        color = colors[(i // len(SHAPES) + i) % len(colors)]
        filename = f"geom_{product_id:06d}.png"
        image, meta = render_shape(shape, color, size=size, seed=seed + 104729 * product_id)
        image.save(images / filename, optimize=False)
        products.append({"id": product_id, "nombre": f"Composicion {shape} {color} {product_id}",
                         "categoria": shape, "precio": round(10 + (i % 197) * 0.1, 2),
                         "descripcion": f"Tablero de figuras dispersas; predomina {shape}, color {color}; otras formas, posiciones y rotaciones aleatorias.",
                         "imagen": filename})
        labels.append({"id": product_id, "figura": shape, "color": color,
                       "imagen": filename, **meta})
    for i in range(queries):
        query_id = i + 1
        shape = SHAPES[i % len(SHAPES)]
        color = colors[(i // len(SHAPES) + 2 * i) % len(colors)]
        filename = f"consulta_geom_{query_id:04d}.png"
        image, scene_meta = render_shape(shape, color, size=size, seed=seed + 15485863 * query_id + 42)
        image.save(query_images / filename, optimize=False)
        queries_data.append({"id": query_id, "figura": shape, "color": color, "imagen": filename,
                             "n_formas": scene_meta["n_formas"]})

    _write_csv(output / "productos.csv", PRODUCT_COLUMNS, products)
    _write_csv(output / "etiquetas.csv", LABEL_COLUMNS, labels)
    _write_csv(output / "consultas.csv", QUERY_COLUMNS, queries_data)

    # Muestrario compacto para revisar visualmente la variedad del corpus.
    columns, rows = 6, min(3, math.ceil(count / 6))
    preview = Image.new("RGB", (columns * size, rows * (size + 22)), "white")
    caption = ImageDraw.Draw(preview)
    for i in range(min(count, columns * rows)):
        x, y = (i % columns) * size, (i // columns) * (size + 22)
        with Image.open(images / products[i]["imagen"]) as tile:
            preview.paste(tile, (x, y))
        caption.text((x + 5, y + size + 3), products[i]["categoria"], fill=(30, 41, 59))
    preview.save(output / "preview.png")

    from vector.bow import model_path, train_model
    with ThreadPoolExecutor(max_workers=workers) as pool:
        sample = list(pool.map(_descriptors, (images / p["imagen"] for p in products[:min(training, count)])))
    model = train_model("image", sample, words, seed=seed, max_descriptors=4000,
                        max_iter=15, descriptor_backend=backend)
    model.save(model_path(output / "modelo", "image"))
    indexed = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        vectors = pool.map(lambda p: _features(images / p["imagen"], model), products)
        for p, vector in zip(products, vectors):
            indexed.append({**p, "embedding": vector})
    _write_csv(output / "productos_indexados.csv", INDEXED_COLUMNS, indexed)

    manifest = {"version": 2, "seed": seed, "count": count, "queries": queries,
                "size": size, "words": model.n_words, "training": min(training, count),
                "sift_backend": backend, "duration_s": round(time.perf_counter() - start, 2),
                "ground_truth": "figura dominante por frecuencia; color principal evaluado independientemente",
                "layout": "random_scattered_multi_shape_no_squares", "available_shapes": list(SHAPES)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    verify_dataset(output)
    return manifest


def verify_dataset(output: Path) -> dict:
    """Valida esquema, IDs, referencias, tamaño, tipo y dimensión de vectores."""
    output = Path(output)
    def rows(name: str, expected: tuple[str, ...]) -> list[dict]:
        with (output / name).open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != expected:
                raise ValueError(f"{name}: columnas inválidas; se esperan {expected}")
            return list(reader)

    products = rows("productos.csv", PRODUCT_COLUMNS)
    indexed = rows("productos_indexados.csv", INDEXED_COLUMNS)
    labels = rows("etiquetas.csv", LABEL_COLUMNS)
    queries_data = rows("consultas.csv", QUERY_COLUMNS)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    from vector.bow import FeatureModel, model_path
    from vector.sift import sift_backend
    if manifest.get("version") != 2 or manifest.get("layout") != "random_scattered_multi_shape_no_squares":
        raise ValueError("este validador espera el dataset scattered v2, no la versión anterior")
    model = FeatureModel.load(model_path(output / "modelo", "image"))
    if (model.n_words != manifest["words"] or model.kind != "image"
            or model.descriptor_backend != manifest["sift_backend"]):
        raise ValueError("modelo BoVW y manifest.json no coinciden")
    if model.descriptor_backend != sift_backend():
        raise ValueError("el backend SIFT instalado no coincide con el vocabulario entrenado")
    if not products or len(products) != len(indexed) or len(products) != len(labels):
        raise ValueError("cantidad de productos, vectores y etiquetas no coincide")
    if len(products) != manifest["count"] or len(queries_data) != manifest["queries"]:
        raise ValueError("conteos de filas incompatibles con manifest.json")
    if (len(list((output / "imagenes").glob("*.png"))) != len(products)
            or len(list((output / "consultas").glob("*.png"))) != len(queries_data)):
        raise ValueError("el número de archivos PNG no coincide con los CSV")
    seen: set[int] = set()
    names: set[str] = set()
    for base, row, label in zip(products, indexed, labels):
        pid = int(base["id"])
        name = base["imagen"]
        if pid != len(seen) + 1 or pid in seen or pid != int(row["id"]) or pid != int(label["id"]):
            raise ValueError(f"producto duplicado/desordenado: {pid}")
        if not base["nombre"].strip() or not base["descripcion"].strip() or not math.isfinite(float(base["precio"])) or float(base["precio"]) <= 0:
            raise ValueError(f"atributos de producto inválidos: id={pid}")
        if name in names or name != label["imagen"] or any(base[k] != row[k] for k in PRODUCT_COLUMNS):
            raise ValueError(f"CSV no coincide con etiquetas o índices: id={pid}")
        if base["categoria"] != label["figura"] or label["figura"] not in SHAPES or label["color"] not in COLORS:
            raise ValueError(f"etiqueta inconsistente: id={pid}")
        try:
            scene = json.loads(label["escena_json"])
            total, majority, distractors = (int(label[key]) for key in ("n_formas", "n_dominantes", "n_distractores"))
            frequencies = {figure: sum(o["figura"] == figure for o in scene) for figure in SHAPES}
            if (len(scene) != total or majority <= total // 2 or majority + distractors != total
                    or not 7 <= total <= 12 or frequencies[label["figura"]] != majority
                    or len({o["figura"] for o in scene}) < 2 or
                    any(o["figura"] not in SHAPES for o in scene)):
                raise ValueError("conteos de composición incorrectos")
            if any(not all(k in obj for k in ("x","y","angulo","radio","color"))
                   or not 0 <= float(obj["angulo"]) <= 360 or int(obj["radio"]) < 1
                   or obj["color"] not in COLORS for obj in scene):
                raise ValueError("metadatos de forma incorrectos")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"escena inválida para id={pid}: {exc}") from exc
        try:
            vector = json.loads(row["embedding"])
            if len(vector) != manifest["words"] or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in vector):
                raise ValueError("vector inválido")
            if not any(vector):
                raise ValueError("vector nulo")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"embedding inválido para id={pid}") from exc
        if not re.fullmatch(r"geom_\d{6}\.png", name) or not (output / "imagenes" / name).is_file():
            raise ValueError(f"imagen faltante/insegura: {name}")
        with Image.open(output / "imagenes" / name) as image:
            if image.size != (manifest["size"], manifest["size"]) or image.format != "PNG":
                raise ValueError(f"imagen con formato/tamaño incorrecto: {name}")
            image.verify()
        seen.add(pid)
        names.add(name)
    query_names: set[str] = set()
    query_ids: set[int] = set()
    for query in queries_data:
        name = query["imagen"]
        qid = int(query["id"])
        if (not re.fullmatch(r"consulta_geom_\d{4}\.png", name) or qid in query_ids or name in query_names
                or query["figura"] not in SHAPES or query["color"] not in COLORS or not 7 <= int(query["n_formas"]) <= 12):
            raise ValueError(f"consulta inválida: {name}")
        with Image.open(output / "consultas" / name) as image:
            if image.size != (manifest["size"], manifest["size"]) or image.format != "PNG":
                raise ValueError(f"consulta con formato/tamaño incorrecto: {name}")
            image.verify()
        query_ids.add(qid)
        query_names.add(name)
    return {"products": len(products), "queries": len(queries_data),
            "image_size": manifest["size"], "embedding_dim": manifest["words"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("data/geometric"))
    parser.add_argument("--count", type=int, default=3000)
    parser.add_argument("--queries", type=int, default=90)
    parser.add_argument("--size", type=int, default=160)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--words", type=int, default=32)
    parser.add_argument("--training", type=int, default=120)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--verify", action="store_true", help="solo revisa un corpus ya generado")
    args = parser.parse_args(argv)
    if args.verify:
        print(json.dumps(verify_dataset(args.output), indent=2))
    else:
        print(json.dumps(generate(output=args.output, count=args.count, queries=args.queries,
                                  size=args.size, seed=args.seed, words=args.words,
                                  training=args.training, workers=args.workers), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
