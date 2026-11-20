"""Local real-product import: alias mapping, provenance, images and failures."""
from __future__ import annotations

import csv
import json

import pytest
from PIL import Image
from tools.prepare_real_products import _number, prepare


def test_price_normalization():
    assert _number("₹1,234.56") == 1234.56
    assert _number("$1.234,56") == 1234.56
    assert _number("S/ 900") == 900
    with pytest.raises(ValueError):
        _number("0")


def test_valid_export_preserves_provenance_and_normalizes_size(tmp_path):
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    Image.new("RGB", (120, 80), "red").save(imgs / "a.png")
    Image.new("RGB", (80, 120), "green").save(imgs / "b.png")
    vendor = tmp_path / "flipkart.csv"
    with vendor.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(("uniq_id", "product_name", "product_category_tree", "discounted_price", "description", "image_path"))
        w.writerow(("src-01", "Laptop A", "Electronics", "₹1,234.56", "Laptop original", "a.png"))
        w.writerow(("src-02", "Laptop B", "Electronics", "₹900", "Laptop B original", "b.png"))
    result = prepare(source="Flipkart", input_csv=vendor, images=imgs,
                     output=tmp_path / "result", min_count=2, max_count=2, currency="INR")
    assert result["rows"] == 2
    assert result["currency"] == "INR"
    with (tmp_path / "result" / "productos.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["precio"] == '1234.56'
    assert rows[0]["imagen"] == 'real_000001.png'
    with Image.open(tmp_path / "result" / "imagenes" / "real_000001.png") as img:
        assert img.size == (160,160)
    metadata = json.loads((tmp_path / "result" / "provenance.json").read_text())
    assert metadata["source"] == "Flipkart"
    assert (tmp_path / "result" / "source_mapping.csv").is_file()


def test_import_rejects_missing_or_corrupt_images(tmp_path):
    folder = tmp_path / "images"
    folder.mkdir()
    (folder / "bad.png").write_bytes(b"not a PNG")
    csv_file = tmp_path / "input.csv"
    csv_file.write_text("id,name,category,price,description,image_path\n1,X,Electronics,100,Product description,bad.png\n")
    with pytest.raises(ValueError, match="unreadable product image"):
        prepare(source="Amazon", input_csv=csv_file, images=folder,
                output=tmp_path / "result", min_count=1, max_count=1)
    assert not (tmp_path / "result").exists()
