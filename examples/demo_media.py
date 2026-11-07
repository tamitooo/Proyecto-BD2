"""Demo reproducible de búsqueda por archivo (Parte 4, 2.4.1 / #107).

Genera imágenes con textura y audios sintéticos, entrena el vocabulario BoVW
(SIFT/MFCC + K-Means + TF-IDF), los indexa con ``EXTRACT_FEATURES('archivo')``
y consulta con ``SIMILAR_TO('archivo', k=N)``. No requiere servidor ni
descargas.

    python -m examples.demo_media
"""

from __future__ import annotations

import shutil
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from backend.engine import DemoEngine
from vector.bow import model_path, train_model
from vector.extract_features import ExtractFeatures
from vector.metrics import cosine_similarity
from vector.sift import sift_backend

IMAGE_WORDS = 16
AUDIO_WORDS = 8
IMAGE_FILES = ("rojo.png", "rojo_2.png", "azul.png", "verde.png")
AUDIO_FILES = ("tono_440.wav", "tono_440_b.wav", "tono_880.wav")


class _WorkspaceDemoDir:
    """Directorio temporal dentro del repo (``.demo_media``)."""

    def __enter__(self) -> Path:
        self.root = Path(".demo_media")
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def __exit__(self, *_exc) -> bool:
        shutil.rmtree(self.root, ignore_errors=True)
        return False


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


def _train_models(root: Path, media: Path) -> tuple[int, int]:
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
    image_model.save(model_path(root / "models", "image"))

    audio_documents = [
        ExtractFeatures.local_descriptors(media / name, kind="audio")
        for name in AUDIO_FILES
    ]
    audio_model = train_model("audio", audio_documents, AUDIO_WORDS, seed=7)
    audio_model.save(model_path(root / "models", "audio"))
    return image_model.n_words, audio_model.n_words


def _ids(result):
    return [row["id"] for row in result.rows]


def main() -> None:
    with _WorkspaceDemoDir() as directory:
        root = Path(directory)
        media = root / "media"
        media.mkdir()

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
        _wav(media / "tono_440.wav", 440.0)
        _wav(media / "tono_440_b.wav", 440.0, phase=1.0)
        _wav(media / "tono_880.wav", 880.0)
        _wav(media / "consulta_440.wav", 440.0, phase=0.5)

        image_words, audio_words = _train_models(root, media)
        print(
            f"Vocabulario BoVW: {image_words} palabras visuales, "
            f"{audio_words} palabras auditivas (SIFT {sift_backend()})"
        )

        db = DemoEngine(data_dir=root, seed=False)

        print("\n== Tabla de imágenes ==")
        print(db.run(
            "CREATE TABLE fotos (id INT PRIMARY KEY, nombre VARCHAR(64), "
            "embedding VARCHAR(4096), categoria VARCHAR(16))"
        ).success)
        for doc_id, name, category in [
            (1, "rojo.png", "rojo"),
            (2, "rojo_2.png", "rojo"),
            (3, "azul.png", "azul"),
            (4, "verde.png", "verde"),
        ]:
            result = db.run(
                f"INSERT INTO fotos VALUES ({doc_id}, '{name}', "
                f"EXTRACT_FEATURES('{name}'), '{category}')"
            )
            print(f"  INSERT {name}: {result.success} {result.error or ''}")

        query = (
            "SELECT id, nombre, categoria, SIMILARITY_SCORE() AS score FROM fotos "
            "WHERE SIMILAR_TO('consulta_rojo.png', k=3) "
            "USING HNSW WITH METRIC=cosine"
        )
        print("\n>", query)
        result = db.run(query)
        print(result.success, result.error or "")
        for row in result.rows:
            print(f"  {row['id']:>2} {row['nombre']:<16} {row['categoria']:<6} {row['score']:.4f}")
        details = result.execution_plan["steps"][0]["details"]
        print(
            "  plan:", result.execution_plan["access_path"],
            "| origen:", details["query_source"],
            "| tipo:", details["media_kind"],
            "| dimensión:", details["dimension"],
            "| palabras:", details.get("n_words"),
            "| extracción ms:", details["extract_ms"],
        )

        # Verificación independiente: coseno calculado fuera del motor.
        query_vector = ExtractFeatures.extract(
            media / "consulta_rojo.png", model_root=root / "models"
        ).values
        rows = db.run("SELECT id, nombre, embedding, categoria FROM fotos").rows
        expected = sorted(
            (
                (
                    row["id"],
                    cosine_similarity(
                        query_vector,
                        ExtractFeatures.extract(
                            media / row["nombre"], model_root=root / "models"
                        ).values,
                    ),
                )
                for row in rows
            ),
            key=lambda item: (-item[1], item[0]),
        )[:3]
        print("  fuerza bruta:", [(doc_id, round(score, 4)) for doc_id, score in expected])
        print("  coincide:", [row["id"] for row in result.rows] == [doc_id for doc_id, _ in expected])

        # ------------------------------------------------------------- audio
        print("\n== Tabla de audios ==")
        print(db.run(
            "CREATE TABLE audios (id INT PRIMARY KEY, nombre VARCHAR(64), "
            "embedding VARCHAR(2048), categoria VARCHAR(16))"
        ).success)
        for doc_id, name, category in [
            (1, "tono_440.wav", "440"),
            (2, "tono_440_b.wav", "440"),
            (3, "tono_880.wav", "880"),
        ]:
            result = db.run(
                f"INSERT INTO audios VALUES ({doc_id}, '{name}', "
                f"EXTRACT_FEATURES('{name}'), '{category}')"
            )
            print(f"  INSERT {name}: {result.success} {result.error or ''}")

        query = (
            "SELECT id, nombre, categoria, SIMILARITY_SCORE() AS score FROM audios "
            "WHERE SIMILAR_TO('consulta_440.wav', k=2) "
            "USING IVF WITH METRIC=cosine"
        )
        print("\n>", query)
        result = db.run(query)
        print(result.success, result.error or "")
        for row in result.rows:
            print(f"  {row['id']:>2} {row['nombre']:<16} {row['categoria']:<6} {row['score']:.4f}")
        print("  coincide:", set(_ids(result)) == {1, 2})

        print("\n== EXPLAIN ANALYZE ==")
        explained = db.run(
            "EXPLAIN ANALYZE SELECT id FROM fotos "
            "WHERE SIMILAR_TO('consulta_rojo.png', k=2) USING HNSW WITH METRIC=cosine"
        )
        print(explained.success, explained.error or "")
        print("  filas:", explained.execution_plan["analyze"]["rows"])
        print("  origen:", explained.execution_plan["steps"][0]["details"]["query_source"])


if __name__ == "__main__":
    main()
