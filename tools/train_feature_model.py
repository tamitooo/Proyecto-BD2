"""Entrena el vocabulario BoVW y el IDF para SIFT/MFCC (Parte 4, 2.4.1).

El vocabulario se aprende de una muestra del corpus: se extraen descriptores
locales (SIFT para imágenes, MFCC para audio), se agrupan con K-Means y se
calculan las frecuencias de documento para TF-IDF. El resultado se guarda en::

    <data-dir>/models/bow_image.npz
    <data-dir>/models/bow_audio.npz

Ese vocabulario debe ser el mismo al indexar y al consultar. Si se cambia el
dataset, hay que reentrenar y reindexar las tablas.

Ejemplos::

    # usa backend/data/media (imágenes y WAV de la demo)
    python -m tools.train_feature_model

    # corpus propio
    python -m tools.train_feature_model ^
        --images C:\\datasets\\fotos ^
        --audio C:\\datasets\\audios ^
        --image-words 64 --audio-words 32

    # solo imágenes
    python -m tools.train_feature_model --images backend/data/media --image-words 64
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import List, Sequence

import numpy as np

from vector.bow import model_path, train_model
from vector.extract_features import (
    ExtractFeatures,
    FeatureExtractionError,
)
from vector.extract_features import _AUDIO_EXTENSIONS, _IMAGE_EXTENSIONS
from vector.sift import sift_backend


def _files_from(values: Sequence[str], extensions: set[str]) -> List[Path]:
    files: List[Path] = []
    for value in values:
        path = Path(value)
        if path.is_dir():
            files.extend(
                sorted(
                    item
                    for item in path.rglob("*")
                    if item.is_file() and item.suffix.lower() in extensions
                )
            )
        elif path.is_file() and path.suffix.lower() in extensions:
            files.append(path)
        else:
            print(f"[aviso] no es un archivo/directorio de {sorted(extensions)}: {path}")
    return files


def _documents(
    files: Sequence[Path], kind: str, max_files: int, max_per_file: int
):
    documents = []
    for index, path in enumerate(files[:max_files], start=1):
        try:
            descriptors = ExtractFeatures.local_descriptors(path, kind=kind)
        except (FeatureExtractionError, OSError) as exc:
            print(f"  [omitido] {path.name}: {exc}")
            continue
        if descriptors.shape[0] == 0:
            print(f"  [omitido] {path.name}: sin descriptores")
            continue
        if descriptors.shape[0] > max_per_file:
            selected = np.linspace(
                0, descriptors.shape[0] - 1, max_per_file
            ).astype(int)
            descriptors = descriptors[selected]
        documents.append(descriptors)
        if index % 25 == 0:
            print(f"  {index}/{min(len(files), max_files)} archivos procesados")
    return documents


def _train_modality(
    kind: str,
    files: Sequence[Path],
    *,
    n_words: int,
    model_dir: Path,
    max_files: int,
    max_descriptors: int,
    max_per_file: int,
    seed: int,
    descriptor_backend: str | None = None,
) -> bool:
    if not files:
        print(f"{kind}: no hay archivos; se omite")
        return False
    print(f"\n{kind}: {len(files)} archivos encontrados; extrayendo descriptores...")
    if descriptor_backend:
        print(f"{kind}: backend SIFT = {descriptor_backend}")
    documents = _documents(files, kind, max_files, max_per_file)
    if not documents:
        print(f"{kind}: no se obtuvieron descriptores; no se entrena")
        return False

    total_descriptors = sum(document.shape[0] for document in documents)
    descriptor_dim = documents[0].shape[1]
    print(
        f"{kind}: {len(documents)} documentos, {total_descriptors} descriptores "
        f"de {descriptor_dim} dimensiones"
    )
    model = train_model(
        kind,
        documents,
        n_words,
        max_descriptors=max_descriptors,
        seed=seed,
        descriptor_backend=descriptor_backend,
    )
    target = model_path(model_dir, kind)
    model.save(target)
    print(
        f"{kind}: vocabulario de {model.n_words} palabras, "
        f"{model.n_documents} documentos para IDF -> {target}"
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Entrena el vocabulario BoVW (SIFT/MFCC) y el IDF de TF-IDF"
    )
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("BD2_DATA_DIR", "backend/data"),
        help="directorio de datos del motor (por defecto backend/data)",
    )
    parser.add_argument(
        "--model-dir",
        default=None,
        help="directorio de salida (por defecto <data-dir>/models)",
    )
    parser.add_argument(
        "--images",
        nargs="*",
        default=None,
        help="archivos o carpetas de imágenes; por defecto <data-dir>/media",
    )
    parser.add_argument(
        "--audio",
        nargs="*",
        default=None,
        help="archivos o carpetas de audio WAV; por defecto <data-dir>/media",
    )
    parser.add_argument("--image-words", type=int, default=64, help="K visual")
    parser.add_argument("--audio-words", type=int, default=32, help="K auditivo")
    parser.add_argument(
        "--max-files",
        type=int,
        default=500,
        help="máximo de archivos por modalidad para entrenar (por defecto 500)",
    )
    parser.add_argument(
        "--max-descriptors",
        type=int,
        default=20000,
        help="máximo de descriptores para K-Means (por defecto 20000)",
    )
    parser.add_argument(
        "--max-descriptors-per-file",
        type=int,
        default=200,
        help="muestra de descriptores por archivo (por defecto 200)",
    )
    parser.add_argument("--seed", type=int, default=7, help="semilla de K-Means")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    model_dir = Path(args.model_dir) if args.model_dir else data_dir / "models"
    media_dir = data_dir / "media"

    image_values = args.images if args.images is not None else [str(media_dir)]
    audio_values = args.audio if args.audio is not None else [str(media_dir)]
    images = _files_from(image_values, _IMAGE_EXTENSIONS)
    audios = _files_from(audio_values, _AUDIO_EXTENSIONS)

    trained = False
    trained |= _train_modality(
        "image",
        images,
        n_words=args.image_words,
        model_dir=model_dir,
        max_files=args.max_files,
        max_descriptors=args.max_descriptors,
        max_per_file=args.max_descriptors_per_file,
        seed=args.seed,
        descriptor_backend=sift_backend(),
    )
    trained |= _train_modality(
        "audio",
        audios,
        n_words=args.audio_words,
        model_dir=model_dir,
        max_files=args.max_files,
        max_descriptors=args.max_descriptors,
        max_per_file=args.max_descriptors_per_file,
        seed=args.seed,
    )
    if not trained:
        raise SystemExit(
            "No se entrenó ningún vocabulario. Revisa --images/--audio o coloca "
            "archivos en <data-dir>/media."
        )
    print(f"\nModelos en: {model_dir}")


if __name__ == "__main__":
    main()
