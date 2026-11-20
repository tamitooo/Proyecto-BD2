"""API bulk-seeding behavior, idempotency and model-safety tests."""
from __future__ import annotations

import csv
import json
import re

import pytest

# This module is available when the patch is applied to the full BD2 repo.
pytest.importorskip("tools.seed_tienda")
from tools.generate_part5_data import generate
from tools.seed_part5_fast import seed
from tools.seed_tienda import SeedError


class FakeApi:
    def __init__(self):
        self.tables = {}
        self.imported = []
        self.created = []

    def get(self, path, timeout=600):
        if path == "/api/health":
            return {"status": "ok"}
        if path == "/api/tables":
            return list(self.tables.values())
        raise AssertionError(path)

    def post_form(self, path, fields, file):
        assert path == "/api/tables/import"
        name = fields["name"]
        rows = list(csv.DictReader(file[1].decode("utf-8").splitlines()))
        self.tables[name] = {"name": name, "row_count": len(rows), "indexes": []}
        self.imported.append(name)
        return {"imported_rows": len(rows)}

    def sql(self, text):
        if text.startswith("CREATE INDEX"):
            match = re.search(r"CREATE INDEX (\S+) ON (\S+)", text)
            assert match
            index, table = match.groups()
            self.tables[table]["indexes"].append({"name": index})
            self.created.append(index)
            return {"rows": []}
        if text.startswith("SELECT id, imagen FROM productos"):
            return {"rows": [{"id": 1, "imagen": "product.png"}]}
        raise AssertionError(text)


@pytest.fixture
def fixture_dataset(tmp_path):
    src = tmp_path / "source"
    src.mkdir()
    image_dir = src / "imagenes"
    image_dir.mkdir()
    model_dir = src / "modelo"
    model_dir.mkdir()
    (model_dir / "bow_image.npz").write_bytes(b"mock-model-bytes")
    source_csv = src / "productos.csv"
    with source_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(("id", "nombre", "categoria", "precio", "descripcion", "imagen"))
        for i in range(1, 13):
            filename = f"product_{i:03d}.png"
            (image_dir / filename).write_bytes(b"PNG" + bytes([i]))
            w.writerow([i, f"Laptop {i}", "laptops", i * 10, f"Laptop modelo {i}", filename])
    with (src / "productos_indexados.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(("id", "nombre", "categoria", "precio", "descripcion", "imagen", "embedding"))
        for i in range(1, 13):
            w.writerow([i, f"Laptop {i}", "laptops", i * 10, f"Laptop modelo {i}",
                        f"product_{i:03d}.png", json.dumps([i / 100, .25])])
    output = tmp_path / "store"
    generate(products_csv=source_csv, output=output, stores=5, users=10, purchases=40)
    return output


def test_import_batch_and_retry_without_duplication(tmp_path, fixture_dataset):
    api = FakeApi()
    out = seed(api, fixture_dataset, tmp_path / "backend", timeout=2)
    assert out["products"] == 12
    assert api.imported == ["tiendas", "stock", "compras", "productos"]
    assert set(api.created) == {"idx_productos_embedding", "idx_tiendas_ubicacion"}
    seed(api, fixture_dataset, tmp_path / "backend", timeout=2)
    assert len(api.imported) == 4
    assert len(api.created) == 2
    assert (tmp_path / "backend" / "media" / "product_001.png").is_file()


def test_rejects_conflicting_model_without_overwriting(tmp_path, fixture_dataset):
    data = tmp_path / "backend"
    target = data / "models" / "bow_image.npz"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"foreign-model")
    with pytest.raises(SeedError, match="different BoVW model"):
        seed(FakeApi(), fixture_dataset, data, timeout=1)
    assert target.read_bytes() == b"foreign-model"
