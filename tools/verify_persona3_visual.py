"""Verificación reproducible de la fuente visual de Persona 3 (g/h).

Carga los 30 productos de ``examples/tienda`` en un ``data_dir`` temporal,
entrena un vocabulario BoVW denso, calcula los embeddings con
``EXTRACT_FEATURES``, crea el IVF y ejecuta:

* ``recommend_by_visual(1)``: vecinos visuales de un producto, sin X;
* ``search_by_image(producto_001.png)``: búsqueda subiendo una imagen;
* ``EXPLAIN`` de la consulta visual para comprobar el índice persistente.

No requiere servidor, OpenCV ni librosa: usa el SIFT denso de respaldo.

    python -m tools.verify_persona3_visual
    python -m tools.verify_persona3_visual --keep
"""

from __future__ import annotations

import argparse
import csv
import shutil
import uuid
from pathlib import Path

from backend.engine import DemoEngine
from recommender import create_schema, recommend_by_visual, search_by_image
from recommender.visual import product_embedding
from vector.bow import model_path, train_model
from vector.extract_features import ExtractFeatures

RAIZ = Path(__file__).resolve().parents[1]
DATOS = RAIZ / "examples" / "tienda"
BASE_TEMP = RAIZ / ".bd2-tests"


def _filas(engine, sql: str, what: str):
    result = engine.run(sql)
    if not result.success:
        raise SystemExit(f"ERROR en {what}: {result.error}\nSQL: {sql}")
    return result.rows


def _insertar_productos(engine, productos_csv: Path) -> int:
    campos = None
    with productos_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        campos = reader.fieldnames
        total = 0
        for row in reader:
            nombre = row["nombre"].replace("'", "''")
            descripcion = row["descripcion"].replace("'", "''")
            sql = (
                "INSERT INTO productos VALUES ("
                f"{int(row['id'])}, '{nombre}', '{row['categoria']}', {float(row['precio'])}, "
                f"'{descripcion}', '{row['imagen']}', EXTRACT_FEATURES('{row['imagen']}', 'image'))"
            )
            _filas(engine, sql, f"insertar producto {row['id']}")
            total += 1
    if not campos:
        raise SystemExit("productos.csv está vacío")
    return total


def _preparar_modelo(media: Path, models: Path) -> int:
    documentos = [
        ExtractFeatures.local_descriptors(media / f"producto_{index:03d}.png", kind="image")
        for index in range(1, 31)
    ]
    if not any(document.shape[0] for document in documentos):
        raise SystemExit("las imágenes de muestra no produjeron descriptores SIFT")
    model = train_model("image", documentos, 16, seed=7, descriptor_backend="dense")
    model.save(model_path(models, "image"))
    return model.n_words


def verificar(keep: bool = False) -> None:
    if not DATOS.is_dir():
        raise SystemExit(f"no existe la carpeta de muestra: {DATOS}")
    imagenes = sorted((DATOS / "imagenes").glob("*.png"))
    if len(imagenes) != 30:
        raise SystemExit(f"se esperaban 30 imágenes de muestra; hay {len(imagenes)}")

    BASE_TEMP.mkdir(parents=True, exist_ok=True)
    root = BASE_TEMP / f"verify-p3-{uuid.uuid4().hex}"
    media = root / "media"
    models = root / "models"
    media.mkdir(parents=True)
    for imagen in imagenes:
        shutil.copy2(imagen, media / imagen.name)

    try:
        palabras = _preparar_modelo(media, models)
        print(f"1. vocabulario BoVW: {palabras} palabras, {len(imagenes)} imágenes")

        engine = DemoEngine(data_dir=str(root), seed=False)
        create_schema(engine)
        total = _insertar_productos(engine, DATOS / "productos.csv")
        print(f"2. productos cargados con EXTRACT_FEATURES: {total}")

        _filas(
            engine,
            "CREATE INDEX idx_productos_embedding ON productos (embedding) "
            "USING IVF WITH METRIC=cosine",
            "crear IVF",
        )
        print("3. IVF creado con CREATE INDEX ... USING IVF WITH METRIC=cosine")

        recomendaciones = recommend_by_visual(engine, 1, k=5)
        if not recomendaciones:
            raise SystemExit("ERROR: recommend_by_visual(1) devolvió vacío")
        ids = [item.producto_id for item in recomendaciones]
        if 1 in ids:
            raise SystemExit("ERROR: la recomendación incluye el producto X")
        if ids != [item.producto_id for item in sorted(
            recomendaciones, key=lambda item: (-item.score, item.producto_id)
        )]:
            raise SystemExit("ERROR: las recomendaciones no están ordenadas por score")
        print("4. recommend_by_visual(1):")
        for item in recomendaciones:
            print(f"   producto {item.producto_id:>2}  score={item.score:.4f}")

        subida = search_by_image(
            engine,
            media / "producto_001.png",
            k=5,
            media_root=media,
            model_root=models,
        )
        if not subida:
            raise SystemExit("ERROR: search_by_image devolvió vacío")
        if subida[0].producto_id != 1:
            raise SystemExit(
                f"ERROR: la imagen de producto_001.png debería recuperar 1; "
                f"devolvió {subida[0].producto_id}"
            )
        print("5. search_by_image(producto_001.png):")
        for item in subida:
            print(f"   producto {item.producto_id:>2}  score={item.score:.4f}")

        vector = product_embedding(engine, 1)
        if vector is None:
            raise SystemExit("ERROR: el producto 1 no tiene embedding")
        literal = "[" + ", ".join(repr(value) for value in vector) + "]"
        plan = engine.run(
            "EXPLAIN SELECT id FROM productos "
            f"WHERE SIMILAR_TO({literal}, k=3) USING IVF WITH METRIC=cosine"
        )
        if not plan.success:
            raise SystemExit(f"ERROR en EXPLAIN: {plan.error}")
        texto = str(plan.rows) + str(plan.execution_plan)
        if "idx_productos_embedding" not in texto and "persistent" not in texto:
            raise SystemExit(f"ERROR: el plan no muestra el IVF persistente: {texto[:500]}")
        print("6. EXPLAIN: el IVF persistente aparece en el plan")

        print("\nOK: la fuente visual funciona con los 30 productos de muestra.")
        print(f"   data_dir temporal: {root}")
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
        else:
            print(f"   se conserva para inspección: {root}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep",
        action="store_true",
        help="no borra el data_dir temporal al terminar",
    )
    args = parser.parse_args()
    verificar(keep=args.keep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
