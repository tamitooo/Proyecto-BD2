"""Generate reproducible synthetic Lima stores, stock, and meaningful purchases.

The input must be the *existing* six-column product CSV. No product properties
or images are altered. All generated stores are fictitious test locations.

    python -m tools.generate_part5_data --products examples/tienda/productos.csv \\
      --output data/store_fixture --stores 30 --users 500 --purchases 2000
    python -m tools.generate_part5_data --verify data/store_fixture

The output follows tools.seed_tienda's exact CSV contracts:
  tiendas.csv: id,nombre,lat,lon,distrito
  stock.csv:   id,tienda_id,producto_id,cantidad
  compras.csv: id,usuario_id,producto_id,fecha,cantidad
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import shutil
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

PRODUCT_FIELDS = ("id", "nombre", "categoria", "precio", "descripcion", "imagen")
STORE_FIELDS = ("id", "nombre", "lat", "lon", "distrito")
STOCK_FIELDS = ("id", "tienda_id", "producto_id", "cantidad")
PURCHASE_FIELDS = ("id", "usuario_id", "producto_id", "fecha", "cantidad")

# District reference centers only; generated store positions and business names
# are entirely fictitious. They must not be represented as actual businesses.
LIMA_CENTERS = (
    ("Cercado de Lima", -12.0464, -77.0428),
    ("Miraflores", -12.1211, -77.0297),
    ("San Isidro", -12.0975, -77.0365),
    ("Santiago de Surco", -12.1460, -76.9920),
    ("La Molina", -12.0790, -76.9420),
    ("Los Olivos", -11.9920, -77.0700),
    ("San Miguel", -12.0777, -77.0928),
    ("Pueblo Libre", -12.0752, -77.0625),
    ("Jesus Maria", -12.0703, -77.0475),
    ("Lince", -12.0821, -77.0309),
    ("Magdalena del Mar", -12.0923, -77.0684),
    ("Barranco", -12.1450, -77.0217),
    ("San Borja", -12.0969, -76.9958),
    ("Surquillo", -12.1141, -77.0108),
    ("Chorrillos", -12.1741, -77.0152),
)

# Category relationships shared by the image-store and co-purchase examples.
# If an input dataset lacks these categories, use observed categories only.
AFFINITIES = (
    ("laptops", "mochilas"),
    ("celulares", "audifonos"),
    ("zapatillas", "relojes"),
    ("camaras", "memorias"),
    ("consolas", "videojuegos"),
    ("televisores", "parlantes"),
    ("impresoras", "tintas"),
)


def _normalized(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold())
                   if not unicodedata.combining(c))


def _category(name: str) -> str:
    s = _normalized(name)
    for normalized, variants in (
        ("laptops", ("laptop", "notebook", "computadora portatil")),
        ("mochilas", ("mochila", "backpack", "maletin")),
        ("celulares", ("celular", "smartphone", "telefono movil", "phone")),
        ("audifonos", ("audifono", "auricular", "headphone", "earbud")),
        ("zapatillas", ("zapatilla", "sneaker", "zapato", "shoe")),
        ("relojes", ("reloj", "smartwatch", "watch")),
        ("camaras", ("camara", "camera")),
        ("memorias", ("memoria", "memory card", "tarjeta sd")),
        ("consolas", ("consola", "console")),
        ("videojuegos", ("videojuego", "video game")),
        ("televisores", ("televisor", "television", "smart tv")),
        ("parlantes", ("parlante", "speaker", "altavoz")),
        ("impresoras", ("impresora", "printer")),
        ("tintas", ("tinta", "cartridge", "cartucho")),
    ):
        if any(s.startswith(variant) or variant in s.split() for variant in variants):
            return normalized
    return s.strip()


def _read_csv(path: Path, columns: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != columns:
            raise ValueError(f"{path.name}: schema mismatch: {reader.fieldnames}, expected {columns}")
        rows = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError(f"{path.name}: malformed CSV line")
        return rows


def read_products(path: Path, *, image_dir: Path | None = None) -> list[dict]:
    rows = _read_csv(path, PRODUCT_FIELDS)
    if not rows:
        raise ValueError("product CSV is empty")
    ids = set()
    images = set()
    for row in rows:
        pid = int(row["id"])
        price = float(row["precio"])
        filename = row["imagen"]
        if pid <= 0 or pid in ids or not math.isfinite(price) or price <= 0:
            raise ValueError(f"duplicate or invalid product id/price: {row['id']}")
        if not row["nombre"].strip() or not row["categoria"].strip() or not row["descripcion"].strip():
            raise ValueError(f"missing product attributes for id {pid}")
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.(?:jpg|jpeg|png|webp|bmp)", filename, re.I)
                or ".." in filename or filename in images):
            raise ValueError(f"unsafe or duplicated image file: {filename}")
        if image_dir is not None and not (image_dir / filename).is_file():
            raise FileNotFoundError(image_dir / filename)
        row["id"] = pid
        row["precio"] = price
        ids.add(pid)
        images.add(filename)
    return rows


def _write(path: Path, columns: tuple[str, ...], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(columns)
        w.writerows(rows)


def _affinity_groups(categories: dict[str, list[int]]) -> list[tuple[str, str]]:
    pairs = [pair for pair in AFFINITIES if pair[0] in categories and pair[1] in categories]
    if pairs:
        return pairs
    keys = sorted(categories)
    if len(keys) == 1:
        return [(keys[0], keys[0])]
    return list(zip(keys, keys[1:] + keys[:1]))


def generate(*, products_csv: Path, output: Path, stores: int = 30,
             users: int = 500, purchases: int = 2000, seed: int = 2026,
             image_dir: Path | None = None) -> dict:
    """Builds three referentially consistent CSV files without replacing inputs."""
    if not 5 <= stores <= 50:
        raise ValueError("stores must be between 5 and 50")
    if users <= 0 or purchases < 2 * users:
        raise ValueError("at least two purchases per user are required")
    products = read_products(Path(products_csv), image_dir=image_dir)
    if purchases > users * len(products):
        raise ValueError("requested purchases exceed available distinct user/product pairs")
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"destination already exists: {output}")
    rng = random.Random(seed)
    categories = defaultdict(list)
    for product in products:
        categories[_category(product["categoria"])].append(product["id"])
    groups = _affinity_groups(categories)
    product_ids = [p["id"] for p in products]

    stores_rows = []
    for i in range(stores):
        district, lat, lon = LIMA_CENTERS[i % len(LIMA_CENTERS)]
        # Bounded displacement, inside a small area near the district center.
        lat += rng.uniform(-0.002, 0.002)
        lon += rng.uniform(-0.002, 0.002)
        stores_rows.append([i + 1, f"Tienda Ficticia {i + 1:02d}", round(lat, 6),
                            round(lon, 6), district])

    stock_rows = []
    for pid in product_ids:
        for store_id in sorted(rng.sample(range(1, stores + 1), k=rng.randint(1, min(stores, 4)))):
            stock_rows.append([len(stock_rows) + 1, store_id, pid, rng.randint(1, 40)])

    basket = {u: set() for u in range(1, users + 1)}
    user_category = {}
    for u in range(1, users + 1):
        a, b = groups[(u - 1) % len(groups)]
        user_category[u] = (a, b)
        primary = rng.choice(categories[a])
        secondary_pool = [x for x in categories[b] if x != primary]
        if not secondary_pool:
            # Single-product dataset cannot provide two distinct purchases.
            raise ValueError("at least two distinct product IDs are required")
        basket[u].update((primary, rng.choice(secondary_pool)))

    # Grow baskets in a deterministic round-robin order. Restrict each user
    # to their two preferred categories until those categories are exhausted.
    remaining = purchases - 2 * users
    while remaining:
        progressed = False
        for u in rng.sample(range(1, users + 1), users):
            if not remaining:
                break
            a, b = user_category[u]
            preferred = set(categories[a] + categories[b]) - basket[u]
            available = preferred or (set(product_ids) - basket[u])
            if not available:
                continue
            basket[u].add(rng.choice(sorted(available)))
            remaining -= 1
            progressed = True
        if not progressed:
            raise ValueError("cannot assign remaining purchases without duplicates")

    purchase_rows = []
    start_date = date(2026, 1, 1)
    for u in sorted(basket):
        basket_day = start_date + timedelta(days=rng.randint(0, 270))
        for pid in sorted(basket[u]):
            day = basket_day + timedelta(days=rng.randint(0, 3))
            purchase_rows.append([len(purchase_rows) + 1, u, pid, day.isoformat(), rng.randint(1, 2)])

    output.mkdir(parents=True, exist_ok=False)
    # Copy rather than symlink: output is portable to Docker/Windows and remains
    # independent of the input directory. Do not alter original image bytes.
    source_dir = Path(products_csv).parent
    assets_dir = image_dir if image_dir is not None else source_dir / "imagenes"
    if assets_dir.is_dir():
        target_dir = output / "imagenes"
        target_dir.mkdir()
        for product in products:
            src = assets_dir / product["imagen"]
            if not src.is_file():
                raise FileNotFoundError(src)
            shutil.copyfile(src, target_dir / product["imagen"])
    if (source_dir / "modelo" / "bow_image.npz").is_file():
        (output / "modelo").mkdir()
        shutil.copyfile(source_dir / "modelo" / "bow_image.npz", output / "modelo" / "bow_image.npz")
    if (source_dir / "productos_indexados.csv").is_file():
        shutil.copyfile(source_dir / "productos_indexados.csv", output / "productos_indexados.csv")
    _write(output / "tiendas.csv", STORE_FIELDS, stores_rows)
    _write(output / "stock.csv", STOCK_FIELDS, stock_rows)
    _write(output / "compras.csv", PURCHASE_FIELDS, purchase_rows)
    # Preserve product CSV verbatim to prevent breaking the existing importer.
    (output / "productos.csv").write_bytes(Path(products_csv).read_bytes())
    manifest = {"source": str(products_csv), "synthetic_stores": True,
                "synthetic_purchases": True, "seed": seed, "products": len(products),
                "stores": len(stores_rows), "stock": len(stock_rows),
                "users": users, "purchases": len(purchase_rows), "affinity_groups": groups,
                "schema": "tools.seed_tienda compatible",
                "assets_copied": (output / "imagenes").is_dir(),
                "precomputed_embeddings": (output / "productos_indexados.csv").is_file(),
                "visual_model": (output / "modelo" / "bow_image.npz").is_file()}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2,
                                                    ensure_ascii=False) + "\n", encoding="utf-8")
    verify(output, image_dir=image_dir)
    return manifest


def verify(output: Path, *, image_dir: Path | None = None) -> dict:
    """Check schemas, PK/FK, geographic bounds, quantities and data integrity."""
    output = Path(output)
    products = read_products(output / "productos.csv", image_dir=image_dir)
    stores = _read_csv(output / "tiendas.csv", STORE_FIELDS)
    stock = _read_csv(output / "stock.csv", STOCK_FIELDS)
    purchases = _read_csv(output / "compras.csv", PURCHASE_FIELDS)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    products_set = {p["id"] for p in products}
    store_ids = set()
    for row in stores:
        sid = int(row["id"])
        lat, lon = float(row["lat"]), float(row["lon"])
        if sid <= 0 or sid in store_ids or not (-12.3 < lat < -11.8 and -77.3 < lon < -76.7):
            raise ValueError(f"invalid/duplicated Lima store: {row}")
        if not row["nombre"].strip() or not row["distrito"].strip():
            raise ValueError(f"missing store attributes: {sid}")
        store_ids.add(sid)
    stocked = set()
    stock_keys = set()
    for row in stock:
        key = (int(row["tienda_id"]), int(row["producto_id"]))
        qty = int(row["cantidad"])
        if (int(row["id"]) <= 0 or key in stock_keys or key[0] not in store_ids
                or key[1] not in products_set or qty < 1):
            raise ValueError(f"invalid/duplicated stock: {row}")
        stocked.add(key[1])
        stock_keys.add(key)
    if stocked != products_set:
        raise ValueError(f"products without stock: {len(products_set - stocked)}")
    purchase_ids = set()
    purchase_keys = set()
    for row in purchases:
        pid = int(row["id"])
        user_id, product_id, amount = int(row["usuario_id"]), int(row["producto_id"]), int(row["cantidad"])
        _ = date.fromisoformat(row["fecha"])
        if (pid <= 0 or pid in purchase_ids or user_id < 1 or product_id not in products_set
                or amount <= 0 or (user_id, product_id) in purchase_keys):
            raise ValueError(f"invalid/duplicated purchase: {row}")
        purchase_ids.add(pid)
        purchase_keys.add((user_id, product_id))
    if (len(products) != manifest["products"] or len(stores) != manifest["stores"]
            or len(stock) != manifest["stock"] or len(purchases) != manifest["purchases"]):
        raise ValueError("manifest counts differ from CSV contents")
    if (output / "imagenes").is_dir():
        read_products(output / "productos.csv", image_dir=output / "imagenes")
    if (output / "productos_indexados.csv").is_file():
        with (output / "productos_indexados.csv").open(encoding="utf-8", newline="") as source:
            indexed = csv.DictReader(source)
            if tuple(indexed.fieldnames or ()) != (*PRODUCT_FIELDS, "embedding"):
                raise ValueError("indexed CSV has incorrect columns")
            index_ids = set()
            for row in indexed:
                pid = int(row["id"])
                if pid in index_ids or pid not in products_set:
                    raise ValueError(f"invalid indexed product ID {pid}")
                v = json.loads(row["embedding"])
                if not isinstance(v, list) or not v or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in v):
                    raise ValueError(f"invalid embedding for product {pid}")
                index_ids.add(pid)
            if index_ids != products_set:
                raise ValueError("indexed products do not match the product CSV")
    return {"products": len(products), "stores": len(stores),
            "stock": len(stock), "purchases": len(purchases),
            "users": len({u for u, _ in purchase_keys})}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--products", type=Path, help="existing six-column product CSV")
    parser.add_argument("--output", type=Path, default=Path("data/part5_synthetic"))
    parser.add_argument("--stores", type=int, default=30)
    parser.add_argument("--users", type=int, default=500)
    parser.add_argument("--purchases", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--images", type=Path, default=None)
    parser.add_argument("--verify", type=Path, help="validate a generated dataset instead of generating")
    args = parser.parse_args(argv)
    if args.verify:
        result = verify(args.verify, image_dir=args.images)
    else:
        if args.products is None:
            parser.error("--products is required when not using --verify")
        result = generate(products_csv=args.products, output=args.output,
                          stores=args.stores, users=args.users, purchases=args.purchases,
                          seed=args.seed, image_dir=args.images)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
