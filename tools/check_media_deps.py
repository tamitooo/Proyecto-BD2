"""Diagnóstico de dependencias opcionales para la demo multimedia.

Comprueba:

* qué backend SIFT está disponible (OpenCV o denso);
* si ``ffmpeg`` está en el PATH (MP3/OGG/FLAC/M4A);
* qué backend tienen los vocabularios guardados y si coinciden con el actual.

Uso::

    python -m tools.check_media_deps
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from vector.bow import FeatureModel, model_path
from vector.sift import sift_backend


def _check_model(model_dir: Path, kind: str, current_backend: str) -> None:
    path = model_path(model_dir, kind)
    if not path.is_file():
        print(f"  modelo {kind}: no existe ({path})")
        return
    try:
        model = FeatureModel.load(path)
    except Exception as exc:  # modelo viejo o corrupto
        print(f"  modelo {kind}: no se pudo leer ({exc})")
        return
    backend = model.descriptor_backend or "sin metadato"
    if kind == "image":
        print(
            f"  modelo {kind}: {model.n_words} palabras, "
            f"descriptor {model.descriptor_dim}-D, backend={backend}"
        )
    else:
        print(
            f"  modelo {kind}: {model.n_words} palabras, "
            f"descriptor {model.descriptor_dim}-D (MFCC)"
        )
    if (
        kind == "image"
        and model.descriptor_backend is not None
        and model.descriptor_backend != current_backend
    ):
        print(
            "    ADVERTENCIA: el modelo se entrenó con otro backend SIFT; "
            "reentrena antes de consultar."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnóstico de deps multimedia")
    parser.add_argument(
        "--data-dir",
        default="backend/data",
        help="directorio de datos del motor (por defecto backend/data)",
    )
    parser.add_argument(
        "--model-dir",
        default=None,
        help="directorio de modelos (por defecto <data-dir>/models)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    model_dir = Path(args.model_dir) if args.model_dir else data_dir / "models"
    backend = sift_backend()
    ffmpeg = shutil.which("ffmpeg")

    print("== Dependencias multimedia ==")
    print(f"SIFT backend disponible: {backend}")
    if backend == "opencv":
        print("  OpenCV: OK (cv2.SIFT_create)")
    else:
        print("  OpenCV: no instalado -> pip install opencv-python-headless")

    if ffmpeg:
        print(f"  ffmpeg: {ffmpeg}")
    else:
        print("  ffmpeg: no encontrado -> winget install Gyan.FFmpeg")
        print("          (o choco install ffmpeg; luego reinicia el backend)")

    print("\n== Vocabularios ==")
    _check_model(model_dir, "image", backend)
    _check_model(model_dir, "audio", backend)

    print("\n== Qué funciona ahora ==")
    print("  imágenes JPG/PNG/...: sí")
    print("  audio WAV:           sí")
    print(
        "  audio MP3/OGG/...:   "
        + ("sí (ffmpeg disponible)" if ffmpeg else "no hasta instalar ffmpeg")
    )
    print(
        "  SIFT OpenCV:         "
        + ("sí" if backend == "opencv" else "no; se usa SIFT denso")
    )

    if backend == "dense" or not ffmpeg:
        print("\nPara la exposición:")
        if backend == "dense":
            print("  pip install opencv-python-headless")
        if not ffmpeg:
            print("  winget install Gyan.FFmpeg")
        print("  # detener el backend, luego:")
        print("  python -m tools.seed_media_demo   # reentrena y reindexa")
        print("  # volver a levantar backend/api.py")
    else:
        print("\nTodo listo: OpenCV y ffmpeg disponibles.")


if __name__ == "__main__":
    main()
