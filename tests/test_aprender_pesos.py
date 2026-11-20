import math
import os
import tempfile

import pytest

from tools.aprender_pesos import (
    Caso,
    buscar_pesos,
    casos_de,
    cocompra,
    escribir_ts,
    evaluar,
    fusionar,
    normalizar,
    pliegues,
    precision,
)


# Mismos casos que frontend/src/tienda/fusion.test.ts, para que ambas fusiones coincidan.

def test_normalizar_como_fusion_ts():
    assert normalizar([(1, 10), (2, 5), (3, 0)]) == [(1, 1), (2, 0.5), (3, 0)]
    assert normalizar([(1, 3), (2, 3)]) == [(1, 1), (2, 1)]
    assert normalizar([(1, 2), (1, 8), (2, math.nan), (3, 4), (4, math.inf)]) == [(1, 1), (3, 0)]
    assert normalizar([]) == []


def test_fusionar_como_fusion_ts():
    assert fusionar(1, {"texto": [(1, 9), (2, 4), (3, 2)], "visual": [(3, 6), (4, 1)]}, {}) == [3, 2, 4]
    assert fusionar(1, {"texto": [(1, 100), (2, 4), (3, 2)]}, {})[0] == 2
    assert fusionar(0, {"a": [(1, 1), (2, 0)], "b": [(2, 1), (1, 0)]}, {"a": 3, "b": 1}) == [1, 2]
    assert fusionar(0, {"a": [(1, 1)], "b": [(2, 1)], "c": [(3, 1)]}, {"b": 0, "c": -2}) == [1]
    assert fusionar(0, {"a": [(5, 1), (4, 1), (3, 1)], "b": [(3, 1), (2, 0)]}, {}, k=2) == [3, 4]
    assert fusionar(1, {}, {}) == []


def test_cocompra_igual_a_la_fuente_de_diego(tmp_path):
    from backend.engine import DemoEngine
    from recommender import create_schema, recommend_by_copurchase
    from recommender.fixture import load_sample

    engine = DemoEngine(data_dir=tmp_path, seed=False)
    create_schema(engine)
    load_sample(engine)
    compras = {}
    for fila in engine.run("SELECT usuario_id, producto_id FROM compras").rows:
        compras.setdefault(int(fila["usuario_id"]), set()).add(int(fila["producto_id"]))
    for producto in {p for ps in compras.values() for p in ps}:
        esperado = [(r.producto_id, pytest.approx(r.score)) for r in recommend_by_copurchase(engine, producto)]
        assert cocompra(producto, compras, sorted(compras)) == esperado


def test_cocompra_no_cuenta_al_usuario_excluido():
    compras = {1: {10, 20}, 2: {10, 30}}
    assert cocompra(10, compras, [1, 2]) == [(20, 0.5), (30, 0.5)]
    assert cocompra(10, compras, [1, 2], excluir=1) == [(30, 1.0)]
    assert cocompra(10, compras, [1], excluir=1) == []


def test_casos_por_compra_y_solo_de_los_usuarios_pedidos():
    cestas = {(1, "d1"): {10, 20}, (1, "d2"): {30}, (2, "d1"): {10, 40, 50}}
    assert casos_de(cestas, [1]) == [Caso(1, 10, frozenset({20})), Caso(1, 20, frozenset({10}))]
    assert len(casos_de(cestas, [1, 2])) == 5


def test_pliegues_son_una_particion_determinista():
    a = pliegues(range(1, 23), 5, 7)
    assert a == pliegues(range(1, 23), 5, 7)
    assert sorted(u for p in a for u in p) == list(range(1, 23))
    assert max(map(len, a)) - min(map(len, a)) <= 1


# 12 productos que empatan con el relevante y le ganan por id: con pesos iguales lo sacan del top 10.
DISTRACTORES = [(-i, 1.0) for i in range(1, 13)] + [(-99, 0.0)]


def test_buscar_pesos_elige_la_fuente_que_acierta():
    casos = [Caso(1, 1, frozenset({2})), Caso(2, 3, frozenset({4}))]
    por_caso = {
        casos[0]: {"buena": [(2, 1.0), (9, 0.0)], "mala": DISTRACTORES},
        casos[1]: {"buena": [(4, 1.0), (8, 0.0)], "mala": DISTRACTORES},
    }
    assert precision(casos, por_caso.__getitem__, {"buena": 1, "mala": 1}) == 0
    pesos = buscar_pesos(casos, por_caso.__getitem__, fuentes=("buena", "mala"), rejilla=(0, 1))
    assert pesos == {"buena": 1, "mala": 0}
    assert precision(casos, por_caso.__getitem__, pesos) == pytest.approx(0.1)


def test_evaluar_aprende_cocompra_cuando_las_compras_van_en_pares():
    # Cada usuario compra un par (2k+1, 2k+2); la fuente fija solo recomienda distractores.
    compras, cestas = {}, {}
    for usuario in range(1, 31):
        par = {2 * (usuario % 5) + 1, 2 * (usuario % 5) + 2}
        compras[usuario] = par
        cestas[(usuario, "d")] = par
    fijas = {p: {"visual": DISTRACTORES, "texto": [], "metadatos": []} for p in range(1, 11)}
    resultado = evaluar(fijas, compras, cestas, k_pliegues=3, semilla=1, rejilla=(0, 1))
    assert resultado["pesos"]["cocompra"] == 1
    assert resultado["pesos"]["visual"] == 0
    assert resultado["precision_aprendidos"] > resultado["precision_iguales"]
    assert len(resultado["pliegues"]) == 3


def test_escribir_ts(tmp_path):
    destino = tmp_path / "pesos.ts"
    escribir_ts({"pesos": {"visual": 0.5}, "semilla": 1, "usuarios": 2, "casos": 3,
                 "precision_iguales": 0.1, "precision_aprendidos": 0.2, "pliegues": []}, destino)
    texto = destino.read_text(encoding="utf-8")
    assert 'export const PESOS_APRENDIDOS: Record<string, number> = {"visual": 0.5};' in texto
    assert '"precision_aprendidos": 0.2' in texto
    assert "pliegues" not in texto


def test_de_punta_a_punta_con_la_muestra(tmp_path, monkeypatch):
    os.environ.setdefault("BD2_DATA_DIR", tempfile.mkdtemp(prefix="bd2-pesos-"))
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    pytest.importorskip("cv2")
    from fastapi.testclient import TestClient

    import backend.api as api_module
    from backend.engine import DemoEngine
    from tools import aprender_pesos
    from tools.seed_tienda import DATOS_MUESTRA, Api, seed

    class ApiDePrueba(Api):
        def __init__(self, client):
            super().__init__("")
            self.client = client

        def _request(self, method, path, body=None, headers=None, timeout=600):
            r = self.client.request(method, path, content=body, headers=headers or {})
            return r.status_code, r.json()

    monkeypatch.setattr(api_module, "engine", DemoEngine(data_dir=tmp_path / "datos", seed=False))
    api = ApiDePrueba(TestClient(api_module.app))
    seed(api, DATOS_MUESTRA, tmp_path / "datos", espera=5)
    monkeypatch.setattr(aprender_pesos, "Api", lambda _base: api)

    salida = tmp_path / "pesos.ts"
    assert aprender_pesos.main(["--salida", str(salida), "--pliegues", "3"]) == 0
    texto = salida.read_text(encoding="utf-8")
    assert "PESOS_APRENDIDOS" in texto and '"casos": ' in texto
