from backend.engine import DemoEngine
from query.csv_loader import infer_schema_from_csv


def test_varchar_se_mide_en_bytes_utf8():
    esquema = dict(infer_schema_from_csv("id,nombre\n1,ñandú\n2,abc\n", primary_key="id"))
    assert esquema["nombre"] == f"VARCHAR({len('ñandú'.encode('utf-8'))})"


def test_texto_con_tildes_no_se_corta_al_importar(tmp_path):
    engine = DemoEngine(data_dir=tmp_path, seed=False)
    texto = "Mochila acolchada, resistente al agua y con compartimento para portátil."
    engine.import_csv_as_table(name="productos", filename="p.csv", primary_key="id",
                               content=f'id,descripcion\n1,"{texto}"\n'.encode("utf-8"))
    fila = engine.run("SELECT descripcion FROM productos WHERE id = 1").rows[0]
    assert fila["descripcion"] == texto
