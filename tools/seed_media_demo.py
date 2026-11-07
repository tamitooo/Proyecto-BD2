"""Deja datos de demostración para probar el panel multimedia en el navegador.

Genera imágenes con textura y WAV en ``<data_dir>/media``, entrena el
vocabulario BoVW (SIFT/MFCC + K-Means + TF-IDF) y crea dos tablas ya indexadas:

* ``fotos_demo`` con vectores de K palabras visuales.
* ``audios_demo`` con vectores de K palabras auditivas.

Uso (con el backend detenido o antes de levantarlo):

    python -m tools.seed_media_demo

Por defecto usa ``backend/data``, que es el ``data_dir`` del API. Si el backend
ya está corriendo, hay que reiniciarlo para que cargue las tablas nuevas.
"""

from __future__ import annotations

import argparse
import os
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from backend.engine import DemoEngine
from vector.bow import model_path, train_model
from vector.extract_features import ExtractFeatures
from vector.sift import sift_backend

IMAGE_WORDS = 16
AUDIO_WORDS = 8

IMAGE_FILES = ("rojo.png", "rojo_2.png", "azul.png", "verde.png")
AUDIO_FILES = ("tono_440.wav", "tono_440_b.wav", "tono_880.wav")


def _bars(path: Path, color, *, count=4, width=8, offset=0, circle=None) -> None:
    image = Image.new("RGB", (96, 96), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for index in range(count):
        y = 10 + index * 20 + offset
        draw.rectangle((8, y, 88, y + width), fill=color)
    if circle is not None:
        draw.ellipse(circle, outline=color, width=4)
    image.save(path)


def _checker(path: Path, color, *, size=12) -> None:
    image = Image.new("RGB", (96, 96), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for y in range(0, 96, size):
        for x in range(0, 96, size):
            if (x // size + y // size) % 2 == 0:
                draw.rectangle((x, y, x + size - 1, y + size - 1), fill=color)
    image.save(path)


def _rings(path: Path, color) -> None:
    image = Image.new("RGB", (96, 96), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    for radius in range(10, 50, 10):
        draw.ellipse(
            (48 - radius, 48 - radius, 48 + radius, 48 + radius),
            outline=color,
            width=4,
        )
    image.save(path)


def _wav(path: Path, frequency: float, *, phase: float = 0.0, rate: int = 16000) -> None:
    time_axis = np.arange(rate // 2) / rate
    samples = (
        0.5 * np.sin(2.0 * np.pi * frequency * time_axis + phase) * 32767
    ).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())


def _run(engine: DemoEngine, sql: str):
    result = engine.run(sql)
    if not result.success:
        raise RuntimeError(f"falló: {sql}\n{result.error}")
    return result


def _train_models(data_dir: Path, media: Path) -> None:
    image_documents = [
        ExtractFeatures.local_descriptors(media / name, kind="image")
        for name in IMAGE_FILES
    ]
    image_model = train_model(
        "image",
        image_documents,
        IMAGE_WORDS,
        seed=7,
        descriptor_backend=sift_backend(),
    )
    image_model.save(model_path(data_dir / "models", "image"))

    audio_documents = [
        ExtractFeatures.local_descriptors(media / name, kind="audio")
        for name in AUDIO_FILES
    ]
    audio_model = train_model(
        "audio", audio_documents, AUDIO_WORDS, seed=7
    )
    audio_model.save(model_path(data_dir / "models", "audio"))

    print(
        f"Vocabulario imagen: {image_model.n_words} palabras "
        f"({sum(document.shape[0] for document in image_documents)} descriptores, "
        f"backend {image_model.descriptor_backend})"
    )
    print(
        f"Vocabulario audio: {audio_model.n_words} palabras "
        f"({sum(document.shape[0] for document in audio_documents)} descriptores)"
    )


def seed(data_dir: Path) -> None:
    media = data_dir / "media"
    media.mkdir(parents=True, exist_ok=True)

    # Patrones con textura: SIFT usa gradientes en escala de grises, así que
    # imágenes de color liso no producen descriptores.
    _bars(media / "rojo.png", (180, 20, 20), count=4, width=8)
    _bars(
        media / "rojo_2.png",
        (200, 30, 30),
        count=4,
        width=9,
        offset=3,
        circle=(30, 30, 66, 66),
    )
    _checker(media / "azul.png", (20, 20, 180))
    _rings(media / "verde.png", (20, 150, 30))
    _bars(media / "consulta_rojo.png", (190, 25, 25), count=4, width=8, offset=1)
    _checker(media / "consulta_azul.png", (25, 25, 190))
    _bars(media / "foto.jpg", (185, 22, 22), count=4, width=8, offset=2)

    _wav(media / "tono_440.wav", 440.0)
    _wav(media / "tono_440_b.wav", 440.0, phase=1.0)
    _wav(media / "tono_880.wav", 880.0)
    _wav(media / "consulta_440.wav", 440.0, phase=0.5)

    _train_models(data_dir, media)

    engine = DemoEngine(data_dir=data_dir, seed=False)

    _run(engine, "DROP TABLE IF EXISTS fotos_demo")
    _run(
        engine,
        "CREATE TABLE fotos_demo (id INT PRIMARY KEY, nombre VARCHAR(64), "
        "embedding VARCHAR(4096), categoria VARCHAR(16))",
    )
    for doc_id, name, category in [
        (1, "rojo.png", "rojo"),
        (2, "rojo_2.png", "rojo"),
        (3, "azul.png", "azul"),
        (4, "verde.png", "verde"),
    ]:
        _run(
            engine,
            f"INSERT INTO fotos_demo VALUES ({doc_id}, '{name}', "
            f"EXTRACT_FEATURES('{name}'), '{category}')",
        )

    _run(engine, "DROP TABLE IF EXISTS audios_demo")
    _run(
        engine,
        "CREATE TABLE audios_demo (id INT PRIMARY KEY, nombre VARCHAR(64), "
        "embedding VARCHAR(2048), categoria VARCHAR(16))",
    )
    for doc_id, name, category in [
        (1, "tono_440.wav", "440"),
        (2, "tono_440_b.wav", "440"),
        (3, "tono_880.wav", "880"),
    ]:
        _run(
            engine,
            f"INSERT INTO audios_demo VALUES ({doc_id}, '{name}', "
            f"EXTRACT_FEATURES('{name}'), '{category}')",
        )

    print(f"\nMedios en: {media}")
    print(f"Modelos en: {data_dir / 'models'}")
    for table in ("fotos_demo", "audios_demo"):
        result = _run(engine, f"SELECT id, nombre, categoria FROM {table} ORDER BY id")
        print(f"{table}: {len(result.rows)} filas")
        for row in result.rows:
            print(f"  {row['id']:>2} {row['nombre']:<16} {row['categoria']}")
    print("\nArchivos de consulta para subir desde el panel:")
    print("  backend/data/media/consulta_rojo.png")
    print("  backend/data/media/consulta_azul.png")
    print("  backend/data/media/consulta_440.wav")
    print("  backend/data/media/foto.jpg")


def main() -> None:
    parser = argparse.ArgumentParser(description="Datos de demo para el panel multimedia")
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("BD2_DATA_DIR", "backend/data"),
        help="directorio de datos del motor (por defecto backend/data)",
    )
    args = parser.parse_args()
    seed(Path(args.data_dir))


if __name__ == "__main__":
    main()
