"""Integración de CSV, SIFT, API e IVF sobre figuras sintéticas etiquetadas."""

from __future__ import annotations

import csv
import io
import json

import pytest
from PIL import Image, ImageDraw

pytest.importorskip("cv2")
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

import backend.api as api_module
from backend.engine import DemoEngine
from benchmarks.benchmark_geometric_retrieval import evaluate, precision
from tools.generate_geometric_dataset import (
    PRODUCT_COLUMNS, generate, verify_dataset,
)
from tools.seed_geometric_dataset import seed
from tools.seed_tienda import Api, SeedError
from vector.sift import sift_descriptors_from_bytes


class LocalApi(Api):
    def __init__(self, client):
        super().__init__("")
        self.client = client

    def _request(self, method, path, body=None, headers=None, timeout=600):
        result = self.client.request(method, path, content=body, headers=headers or {})
        return result.status_code, result.json()


@pytest.fixture
def dataset(tmp_path):
    path = tmp_path / "corpus"
    generate(output=path, count=48, queries=12, training=24, workers=2)
    return path


def test_generate_csv_labels_and_size(dataset):
    assert verify_dataset(dataset) == {
        "products": 48, "queries": 12, "image_size": 160, "embedding_dim": 32,
    }
    assert (dataset / "preview.png").is_file()
    with (dataset / "productos.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert tuple(reader.fieldnames) == PRODUCT_COLUMNS
        assert len(list(reader)) == 48


def test_generator_deterministic_with_seed(tmp_path):
    left, right = tmp_path / "a", tmp_path / "b"
    generate(output=left, count=12, queries=6, training=12, workers=1, seed=17)
    generate(output=right, count=12, queries=6, training=12, workers=2, seed=17)
    for name in ("productos.csv", "etiquetas.csv", "consultas.csv", "productos_indexados.csv"):
        assert (left / name).read_bytes() == (right / name).read_bytes()
    assert (left / "imagenes" / "geom_000001.png").read_bytes() == (right / "imagenes" / "geom_000001.png").read_bytes()


def test_validator_catches_missing_images_and_damaged_csv(dataset):
    (dataset / "imagenes" / "geom_000001.png").unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        verify_dataset(dataset)


def test_sift_ignores_hue_when_luminance_is_equal():
    """Rojo (L=76) y verde (L=76) dejan los mismos descriptores SIFT."""
    arrays = []
    for fill in ((255, 0, 0), (0, 130, 0)):
        image = Image.new("RGB", (160, 160), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((30, 30, 130, 130), fill=fill, outline="black", width=4)
        for i in range(6):
            draw.ellipse((42 + i * 11, 65, 47 + i * 11, 70), fill="black")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        arrays.append((image.convert("L").tobytes(), sift_descriptors_from_bytes(buffer.getvalue())))
    import numpy as np
    assert arrays[0][0] == arrays[1][0]
    assert arrays[0][1].shape == arrays[1][1].shape
    np.testing.assert_array_equal(arrays[0][1], arrays[1][1])


def test_precision_uses_independent_shape_and_color_labels():
    labels = {1: {"figura": "circulo", "color": "azul"},
              2: {"figura": "circulo", "color": "rojo"},
              3: {"figura": "triangulo", "color": "rojo"}}
    result = precision([1, 2, 3], {"figura": "circulo", "color": "rojo"}, labels, k=3)
    assert result == {"p_shape": 2/3, "p_color": 2/3, "p_both": 1/3, "top1_shape": 1}


def test_batch_api_import_ivf_retrieval_and_evaluation(dataset, tmp_path, monkeypatch):
    data_dir = tmp_path / "backend"
    engine = DemoEngine(data_dir=data_dir, seed=False)
    monkeypatch.setattr(api_module, "engine", engine)
    client = TestClient(api_module.app)
    api = LocalApi(client)
    report = seed(api, dataset, data_dir, espera=2)
    assert report["products"] == 48
    assert len(engine.run("SELECT id FROM figuras").rows) == 48
    assert client.get("/api/media/geom_000001.png").status_code == 200
    assert client.get("/api/media/consulta_geom_0001.png").status_code == 200
    assert any(idx["name"] == "idx_figuras_embedding" for idx in engine.table_info("figuras")["indexes"])
    query = engine.run("SELECT id, imagen, SIMILARITY_SCORE() AS score FROM figuras "
                       "WHERE SIMILAR_TO('consulta_geom_0001.png', k=10) USING IVF WITH METRIC=cosine")
    assert query.success, query.error
    assert len(query.rows) == 10
    result = evaluate(api, dataset, tmp_path / "results", k=10, limit=6)
    assert result["queries"] == 6
    assert 0 <= result["averages"]["p_shape"] <= 1
    assert (tmp_path / "results" / "precision_queries.csv").is_file()
    assert (tmp_path / "results" / "precision_summary.json").is_file()
    assert (tmp_path / "results" / "precision_por_figura.png").is_file()
    seed(api, dataset, data_dir, espera=2)
    assert len(engine.run("SELECT id FROM figuras").rows) == 48


def test_import_protects_existing_model(dataset, tmp_path, monkeypatch):
    data_dir = tmp_path / "backend"
    engine = DemoEngine(data_dir=data_dir, seed=False)
    monkeypatch.setattr(api_module, "engine", engine)
    model_dir = data_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "bow_image.npz").write_bytes(b"modelo ajeno")
    with pytest.raises(SeedError, match="otro vocabulario"):
        seed(LocalApi(TestClient(api_module.app)), dataset, data_dir, espera=2)
    assert (model_dir / "bow_image.npz").read_bytes() == b"modelo ajeno"
