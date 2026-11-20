"""Normalize a *locally obtained* Amazon/Flipkart product export for Part 5.

No network scraping or remote-image downloading. Requires legitimate source
rights and local image files supplied by the operator. Preserve provenance in
source_mapping.csv / provenance.json. Invalid fields fail rather than impute.

    python -m tools.prepare_real_products --source Amazon --input vendor.csv \\
      --images images --output data/real_products --min-count 2000 --max-count 5000

The result is the existing six-column CSV + images/ for seed_tienda, but the
visual model/embeddings must be trained using tools/train_feature_model.py.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from pathlib import Path

from PIL import Image, ImageOps
from tools.generate_part5_data import PRODUCT_FIELDS, read_products

ALIASES = {
    "original_id": ("asin", "uniq_id", "product_id", "pid", "id", "sku"),
    "nombre": ("product_name", "product_title", "name", "title"),
    "categoria": ("product_category_tree", "category", "main_category", "product_category"),
    "precio": ("discounted_price", "actual_price", "selling_price", "price", "retail_price"),
    "descripcion": ("description", "about_product", "product_description", "details"),
    "imagen": ("image_path", "local_image", "image_file", "image", "imagen"),
}
SAFE_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.(?:png|jpe?g|webp|bmp)$", re.I)


def _column(header: list[str], field: str, selected: dict[str, str] | None) -> str:
    if selected and field in selected:
        candidate = selected[field]
        if candidate not in header:
            raise ValueError(f"missing mapped {field} column {candidate!r}")
        return candidate
    for alias in ALIASES[field]:
        for name in header:
            if name.lower() == alias.lower():
                return name
    raise ValueError(f"no {field} field found in input; use --columns-map JSON")


def _number(raw: str) -> float:
    text = str(raw).strip().replace("\u00a0", "")
    # Accept 1,234.56, 1.234,56, $1234, ₹1234 and plain decimals.
    text = re.sub(r"[^\d.,-]", "", text)
    if text.count(",") and text.count("."):
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else text.replace(".", "").replace(",", ".")
    elif text.count(",") == 1 and len(text.rsplit(",", 1)[1]) != 3:
        text = text.replace(",", ".")
    else:
        text = text.replace(",", "")
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"invalid price: {raw!r}")
    return value


def prepare(*, source: str, input_csv: Path, images: Path, output: Path,
            min_count: int = 2000, max_count: int = 5000,
            columns_map: dict[str, str] | None = None, currency: str = "source") -> dict:
    if source.lower() not in ("amazon", "flipkart") or min_count < 1 or max_count < min_count:
        raise ValueError("source must be Amazon or Flipkart; invalid count bounds")
    input_csv, images, output = Path(input_csv), Path(images), Path(output)
    if output.exists():
        raise FileExistsError(output)
    with input_csv.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError("input has no CSV header")
        fields = {name: _column(list(reader.fieldnames), name, columns_map) for name in ALIASES}
        rows = []
        mapping = []
        original_ids = set()
        for source_row in reader:
            if len(rows) == max_count:
                break
            source_id = source_row[fields["original_id"]].strip()
            if not source_id or source_id in original_ids:
                raise ValueError(f"empty or duplicate original product id: {source_id!r}")
            original_ids.add(source_id)
            name = source_row[fields["nombre"]].strip()
            description = source_row[fields["descripcion"]].strip()
            category = source_row[fields["categoria"]].strip()
            if category.startswith("["):
                try:
                    value = json.loads(category.replace("'", '"'))
                    if isinstance(value, list) and value:
                        category = str(value[0])
                except json.JSONDecodeError:
                    pass
            category = category.split(">>")[0].strip().strip('"')
            image_name = Path(source_row[fields["imagen"]].strip()).name
            if (not name or not description or not category or len(category) > 32
                    or not SAFE_IMAGE.fullmatch(image_name) or ".." in image_name):
                raise ValueError(f"missing/invalid attributes for source product {source_id}")
            source_image = images / image_name
            if not source_image.is_file():
                raise FileNotFoundError(f"missing local image for {source_id}: {source_image}")
            # Validate actual image bytes, not only filename/extension.
            try:
                with Image.open(source_image) as check:
                    check.verify()
            except Exception as exc:
                raise ValueError(f"unreadable product image: {source_image}") from exc
            # Existing Heap pages/metadata have limited space. Refuse silent truncation.
            if len(name.encode("utf-8")) > 120 or len(description.encode("utf-8")) > 900:
                raise ValueError(f"name/description too long for store schema: {source_id}")
            price = _number(source_row[fields["precio"]])
            pid = len(rows) + 1
            final_name = f"real_{pid:06d}.png"
            rows.append([pid, name, category, price, description, final_name])
            mapping.append([pid, source_id, image_name, final_name,
                            hashlib.sha256(source_image.read_bytes()).hexdigest()])
    if len(rows) < min_count:
        raise ValueError(f"only {len(rows)} complete rows; at least {min_count} required")
    output.mkdir(parents=True, exist_ok=False)
    (output / "imagenes").mkdir()
    with (output / "productos.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(PRODUCT_FIELDS)
        writer.writerows(rows)
    with (output / "source_mapping.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("id", "original_id", "original_image", "copied_image", "sha256"))
        writer.writerows(mapping)
    # Normalize images without cropping: consistent 160×160 square canvas,
    # RGB mode, aspect ratio preserved with white letterboxing.
    for row in mapping:
        with Image.open(images / row[2]) as source_image:
            normalized = ImageOps.contain(source_image.convert("RGB"), (160, 160))
            canvas = Image.new("RGB", (160, 160), "white")
            canvas.paste(normalized, ((160 - normalized.width) // 2, (160 - normalized.height) // 2))
            canvas.save(output / "imagenes" / row[3], format="PNG")
    read_products(output / "productos.csv", image_dir=output / "imagenes")
    for row in mapping:
        with Image.open(output / "imagenes" / row[3]) as image:
            if image.size != (160, 160) or image.mode != "RGB":
                raise ValueError(f"nonstandard product image: {row[3]}")
    report = {"source": source, "rows": len(rows), "currency": currency,
              "input_csv": str(input_csv), "image_folder": str(images),
              "copyright_and_license": "verify license/permission with dataset owner before redistribution",
              "model_status": "not trained; run tools.train_feature_model on images"}
    (output / "provenance.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", required=True, choices=("Amazon", "Flipkart"))
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--images", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--min-count", type=int, default=2000)
    p.add_argument("--max-count", type=int, default=5000)
    p.add_argument("--currency", default="source")
    p.add_argument("--columns-map", type=Path, help="JSON mapping logical fields to source headers")
    args = p.parse_args(argv)
    mapping = json.loads(args.columns_map.read_text(encoding="utf-8")) if args.columns_map else None
    print(json.dumps(prepare(source=args.source, input_csv=args.input, images=args.images,
                             output=args.output, min_count=args.min_count,
                             max_count=args.max_count, columns_map=mapping,
                             currency=args.currency), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
