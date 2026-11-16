import os
import tempfile

import pytest

os.environ.setdefault("BD2_DATA_DIR", tempfile.mkdtemp(prefix="bd2-media-api-"))
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

import backend.api as api
from backend.engine import DemoEngine

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = DemoEngine(data_dir=tmp_path, seed=False)
    engine.media_dir.mkdir(parents=True, exist_ok=True)
    (engine.media_dir / "laptop.png").write_bytes(PNG)
    (engine.media_dir / "tono.wav").write_bytes(b"RIFF0000WAVE")
    (tmp_path / "catalog.json").write_text("{}")
    monkeypatch.setattr(api, "engine", engine)
    return TestClient(api.app)


def test_sirve_una_imagen_con_su_tipo(client):
    respuesta = client.get("/api/media/laptop.png")
    assert respuesta.status_code == 200
    assert respuesta.content == PNG
    assert respuesta.headers["content-type"] == "image/png"


def test_sirve_un_audio(client):
    respuesta = client.get("/api/media/tono.wav")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] in {"audio/wav", "audio/x-wav"}


def test_archivo_inexistente_da_404(client):
    assert client.get("/api/media/no_existe.png").status_code == 404


@pytest.mark.parametrize("nombre", ["..%2Fcatalog.json", "..", "%2E%2E%2Fcatalog.json", ".oculto"])
def test_no_sale_de_la_carpeta_media(client, nombre):
    assert client.get(f"/api/media/{nombre}").status_code == 404


def test_una_carpeta_no_es_un_archivo(client, tmp_path):
    (tmp_path / "media" / "sub").mkdir()
    assert client.get("/api/media/sub").status_code == 404


@pytest.mark.parametrize("nombre", ["pagina.html", "dibujo.svg", "script.js", "notas.txt"])
def test_no_sirve_archivos_que_no_son_imagen_ni_audio(client, tmp_path, nombre):
    (tmp_path / "media" / nombre).write_text("<script>alert(1)</script>")
    assert client.get(f"/api/media/{nombre}").status_code == 404


def test_manda_nosniff_y_acepta_extension_en_mayusculas(client, tmp_path):
    (tmp_path / "media" / "FOTO.JPG").write_bytes(b"\xff\xd8\xff")
    respuesta = client.get("/api/media/FOTO.JPG")
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"] == "image/jpeg"
    assert respuesta.headers["x-content-type-options"] == "nosniff"
