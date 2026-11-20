import csv
import gzip
import io
import json
from pathlib import Path

import pytest

pytest.importorskip("PIL")
pytest.importorskip("cv2")

from PIL import Image

from tools import preparar_abo
from tools.preparar_abo import LISTINGS, PRECIOS, preparar
from vector.bow import FeatureModel

MUESTRA = Path(__file__).resolve().parents[1] / "examples" / "tienda" / "imagenes"


def _listing(item_id, tipo, nombre_es, vinetas_es, imagen, nombre_en="English name"):
    return {
        "item_id": item_id,
        "product_type": [{"value": tipo}],
        "main_image_id": imagen,
        "item_name": [{"language_tag": "en_US", "value": nombre_en},
                      {"language_tag": "es_MX", "value": nombre_es}] if nombre_es else
                     [{"language_tag": "en_US", "value": nombre_en}],
        "bullet_point": [{"language_tag": "es_MX", "value": v} for v in vinetas_es],
    }


@pytest.fixture
def raw(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    listados = []
    for i in range(6):
        listados.append(_listing(f"S{i}", "CHAIR", f"Marca Amazon - Silla modelo {i}, gris",
                                 ["Madera maciza", "Fácil de armar"], f"img{i}"))
    for i in range(6):
        listados.append(_listing(f"J{i}", "FINERING", f"Anillo de plata &amp; circonia {i}",
                                 ["Plata de ley"], f"img{10 + i}"))
    listados += [
        _listing("V1", "CHAIR", "Silla modelo 1, azul", ["Variante"], "img20"),
        _listing("V2", "CHAIR", "Otra silla con la misma foto", ["Repetida"], "img2"),
        _listing("X1", "SOFA", "Muestra de tela para sofá", ["Tela"], "img21"),
        _listing("X2", "SOFA", "Sofá sin imagen principal", ["Tela"], None),
        _listing("X3", "SOFA", "", ["Tela"], "img23"),
        _listing("X4", "CELLULAR_PHONE_CASE", "Funda de celular", ["Plástico"], "img24"),
        _listing("X5", "SOFA", "Sofá sin viñetas", [], "img25"),
        _listing("R1", "RUG", "Remache alfombra de lana", ["Lana"], "img26"),
    ]
    with gzip.open(raw / Path(LISTINGS[0]).name, "wt", encoding="utf-8") as f:
        for d in listados:
            f.write(json.dumps(d) + "\n")
    for key in LISTINGS[1:]:
        with gzip.open(raw / Path(key).name, "wt", encoding="utf-8"):
            pass
    with gzip.open(raw / "images.csv.gz", "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["image_id", "height", "width", "path"])
        for i in range(30):
            w.writerow([f"img{i}", 256, 256, f"{i:02x}/img{i}.jpg"])

    fotos = sorted(MUESTRA.glob("*.png"))
    pedidas = []

    class Respuesta(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(url, timeout=None):
        pedidas.append(url)
        n = int(url.rsplit("img", 1)[1].split(".")[0])
        return Respuesta(fotos[n % len(fotos)].read_bytes())

    monkeypatch.setattr(preparar_abo.urllib.request, "urlopen", urlopen)
    return raw, pedidas


def _productos(salida):
    with (salida / "productos.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_elige_productos_en_espanol_sin_variantes(raw, tmp_path):
    raw, pedidas = raw
    salida = tmp_path / "tienda"
    reporte = preparar(raw=raw, salida=salida, por_cat=10, palabras=4)
    filas = _productos(salida)
    assert reporte["productos"] == len(filas) == 13
    assert reporte["por_categoria"] == {"alfombras": 1, "joyas": 6, "sillas": 6}
    nombres = [f["nombre"] for f in filas]
    assert "Silla modelo 0, gris" in nombres
    assert sum(n.startswith("Silla modelo 1,") for n in nombres) == 1
    assert not any(n.startswith("Marca Amazon") for n in nombres)
    assert "Anillo de plata & circonia 0" in nombres
    assert "Rivet alfombra de lana" in nombres
    assert not any("Muestra" in n or "Funda" in n or "Sofá" in n for n in nombres)
    assert all(f["descripcion"] for f in filas)
    assert not any(url.endswith(("img21.jpg", "img24.jpg")) for url in pedidas)


def test_imagenes_precios_modelo_y_licencia(raw, tmp_path):
    raw, _ = raw
    salida = tmp_path / "tienda"
    preparar(raw=raw, salida=salida, por_cat=10, palabras=4)
    for f in _productos(salida):
        with Image.open(salida / "imagenes" / f["imagen"]) as img:
            assert img.size == (160, 160) and img.format == "JPEG"
        bajo, alto = PRECIOS[f["categoria"]]
        assert bajo <= float(f["precio"]) <= alto + 1
    assert FeatureModel.load(salida / "modelo" / "bow_image.npz").n_words == 4
    assert "CC BY-NC 4.0" in (salida / "LICENCIA.txt").read_text(encoding="utf-8")
    with (salida / "origen.csv").open(encoding="utf-8") as f:
        origen = list(csv.DictReader(f))
    assert {o["abo_item_id"] for o in origen} >= {"S0", "J0", "R1"}


def test_es_determinista_y_no_sobrescribe(raw, tmp_path):
    raw, _ = raw
    a, b = tmp_path / "a", tmp_path / "b"
    preparar(raw=raw, salida=a, por_cat=3, palabras=4)
    preparar(raw=raw, salida=b, por_cat=3, palabras=4)
    assert (a / "productos.csv").read_bytes() == (b / "productos.csv").read_bytes()
    with pytest.raises(FileExistsError):
        preparar(raw=raw, salida=a, por_cat=3, palabras=4)
