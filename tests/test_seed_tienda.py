import os
import shutil
import tempfile
import time

import pytest

os.environ.setdefault("BD2_DATA_DIR", tempfile.mkdtemp(prefix="bd2-seed-"))
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("cv2")

from fastapi.testclient import TestClient

import backend.api as api_module
from backend.engine import DemoEngine
from tools import seed_tienda
from tools.seed_tienda import DATOS_MUESTRA, MODELO, Api, SeedError, seed


class ApiDePrueba(Api):
    def __init__(self, client):
        super().__init__("")
        self.client = client

    def _request(self, method, path, body=None, headers=None, timeout=600):
        r = self.client.request(method, path, content=body, headers=headers or {})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    engine = DemoEngine(data_dir=tmp_path, seed=False)
    monkeypatch.setattr(api_module, "engine", engine)
    return ApiDePrueba(TestClient(api_module.app)), tmp_path, engine


def _filas(engine, sql):
    r = engine.run(sql)
    assert r.success, r.error
    return r.rows


def test_carga_todo_y_las_consultas_de_la_tienda_funcionan(entorno):
    api, data_dir, engine = entorno
    seed(api, DATOS_MUESTRA, data_dir, espera=5)

    assert {t["name"] for t in api.get("/api/tables")} >= {"productos", "tiendas", "stock", "compras"}
    assert len(_filas(engine, "SELECT id FROM productos")) == 30
    assert len(_filas(engine, "SELECT id FROM compras")) == 200
    assert (data_dir / "models" / MODELO).is_file()
    assert (data_dir / "media" / "producto_001.png").is_file()

    vecinos = _filas(engine, "SELECT id, categoria FROM productos "
                             "WHERE SIMILAR_TO('producto_001.png', k=3) USING IVF WITH METRIC=cosine")
    assert vecinos[0]["id"] == 1
    plan = engine.run("EXPLAIN SELECT id FROM productos "
                      "WHERE SIMILAR_TO('producto_001.png', k=3) USING IVF WITH METRIC=cosine")
    assert "idx_productos_embedding" in str(plan.rows) + str(plan.execution_plan)

    texto = _filas(engine, "SELECT id, categoria FROM productos "
                           "WHERE MATCH(descripcion, 'mochila para laptop') USING BM25 LIMIT 3")
    assert texto[0]["categoria"] == "mochilas"

    cerca = _filas(engine, "SELECT id FROM tiendas "
                           "WHERE distancia(ubicacion, POINT(-12.12, -77.03), HAVERSINE) < 1500")
    assert [f["id"] for f in cerca] == [1]


def test_las_descripciones_con_tildes_quedan_completas(entorno):
    api, data_dir, engine = entorno
    seed(api, DATOS_MUESTRA, data_dir, espera=5)
    fila = _filas(engine, "SELECT descripcion FROM productos WHERE id = 1")[0]
    assert fila["descripcion"].endswith(".")
    assert "portátil" in fila["descripcion"]


def test_correrlo_dos_veces_no_duplica(entorno):
    api, data_dir, engine = entorno
    seed(api, DATOS_MUESTRA, data_dir, espera=5)
    seed(api, DATOS_MUESTRA, data_dir, espera=5)
    assert len(_filas(engine, "SELECT id FROM productos")) == 30
    assert len(_filas(engine, "SELECT id FROM stock")) == len(
        (DATOS_MUESTRA / "stock.csv").read_text(encoding="utf-8").strip().splitlines()) - 1
    indices = [i["name"] for t in api.get("/api/tables") for i in t["indexes"]]
    assert indices.count("idx_tiendas_ubicacion") == 1
    assert indices.count("idx_productos_embedding") == 1


def test_completa_productos_si_la_carga_se_corto(entorno):
    api, data_dir, engine = entorno
    seed(api, DATOS_MUESTRA, data_dir, espera=5)
    assert engine.run("DELETE FROM productos WHERE id > 20").success
    seed(api, DATOS_MUESTRA, data_dir, espera=5)
    assert len(_filas(engine, "SELECT id FROM productos")) == 30


def test_no_pisa_otro_vocabulario_sin_permiso(entorno):
    api, data_dir, _ = entorno
    modelos = data_dir / "models"
    modelos.mkdir(parents=True)
    (modelos / MODELO).write_bytes(b"otro modelo")
    with pytest.raises(SeedError, match="otro vocabulario"):
        seed(api, DATOS_MUESTRA, data_dir, espera=5)
    assert (modelos / MODELO).read_bytes() == b"otro modelo"
    seed(api, DATOS_MUESTRA, data_dir, espera=5, reemplazar_modelo=True)
    assert (modelos / MODELO).read_bytes() == (DATOS_MUESTRA / "modelo" / MODELO).read_bytes()


def test_avisa_si_la_api_no_responde_sin_pasarse_del_limite(tmp_path):
    inicio = time.monotonic()
    with pytest.raises(SeedError, match="no respondió"):
        seed_tienda.esperar_api(Api("http://127.0.0.1:9"), 1)
    assert time.monotonic() - inicio < 10


def test_main_devuelve_1_con_mensaje_claro(tmp_path, capsys):
    datos = tmp_path / "datos"
    shutil.copytree(DATOS_MUESTRA, datos, ignore=shutil.ignore_patterns("__pycache__"))
    assert seed_tienda.main(["--api", "http://127.0.0.1:9", "--espera", "1",
                             "--datos", str(datos), "--data-dir", str(tmp_path / "data")]) == 1
    assert "error:" in capsys.readouterr().err
