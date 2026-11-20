import os
import tempfile

import pytest

os.environ.setdefault("BD2_DATA_DIR", tempfile.mkdtemp(prefix="bd2-recommend-api-"))
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

import backend.api as api
from backend.engine import DemoEngine
from recommender import create_schema, recommend_by_copurchase, recommend_by_metadata
from recommender.fixture import load_sample


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    engine = DemoEngine(data_dir=tmp_path_factory.mktemp("recommend"), seed=False)
    create_schema(engine)
    load_sample(engine)
    return engine


@pytest.fixture
def client(engine, monkeypatch):
    monkeypatch.setattr(api, "engine", engine)
    return TestClient(api.app)


@pytest.mark.parametrize("ruta, funcion", [
    ("copurchase", recommend_by_copurchase),
    ("metadata", recommend_by_metadata),
])
def test_devuelve_lo_mismo_que_la_fuente(client, engine, ruta, funcion):
    respuesta = client.get(f"/api/recommend/{ruta}/1")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    esperado = [r.as_dict() for r in funcion(engine, 1, k=10)]
    assert esperado
    assert cuerpo["producto_id"] == 1
    assert cuerpo["recomendaciones"] == esperado


@pytest.mark.parametrize("ruta", ["copurchase", "metadata"])
def test_respeta_k(client, ruta):
    cuerpo = client.get(f"/api/recommend/{ruta}/1?k=2").json()
    assert len(cuerpo["recomendaciones"]) <= 2


@pytest.mark.parametrize("ruta", ["copurchase", "metadata"])
def test_producto_inexistente_devuelve_lista_vacia(client, ruta):
    respuesta = client.get(f"/api/recommend/{ruta}/99999")
    assert respuesta.status_code == 200
    assert respuesta.json()["recomendaciones"] == []


@pytest.mark.parametrize("k", [0, 101])
def test_k_fuera_de_rango_da_422(client, k):
    assert client.get(f"/api/recommend/metadata/1?k={k}").status_code == 422


def test_sin_tablas_da_400(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "engine", DemoEngine(data_dir=tmp_path, seed=False))
    respuesta = TestClient(api.app).get("/api/recommend/metadata/1")
    assert respuesta.status_code == 400
