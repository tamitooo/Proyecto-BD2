"""Almacenamiento y extracción de archivos multimedia subidos por el panel.

El panel no puede enviar la ruta local del archivo (el navegador la oculta por
seguridad). Por eso se sube el contenido, se guarda en ``<data_dir>/media`` y
se devuelve el nombre con el que el SQL puede referenciarlo::

    POST /api/media/extract  (multipart/form-data, campo ``file``)

    {
      "name": "foto.jpg",
      "kind": "image",
      "dimension": 16,
      "mode": "bow",
      "n_words": 16,
      "vector": [...],
      "json": "[...]"
    }

Con ese nombre, la consulta del enunciado funciona tal cual::

    SELECT * FROM fotos
    WHERE SIMILAR_TO('foto.jpg', k=5) USING HNSW WITH METRIC=cosine;
"""

from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Optional

from vector.extract_features import ExtractFeatures, FeatureExtractionError

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_media_name(filename: Optional[str]) -> str:
    """Nombre de archivo seguro; conserva la extensión que decide el extractor."""
    base = os.path.basename(filename or "archivo")
    cleaned = _SAFE_NAME.sub("_", base).strip("._")
    if not cleaned:
        cleaned = "archivo"
    return cleaned[:120]


def save_media(media_dir: Path, filename: Optional[str], content: bytes) -> Path:
    """Guarda ``content`` sin pisar un archivo distinto con el mismo nombre.

    Si ya existe un archivo con ese nombre y el mismo contenido, se reutiliza.
    Si el contenido es distinto, se agrega un hash corto al nombre. Así el
    panel puede volver a subir ``foto.jpg`` sin perder la versión anterior.
    """
    media_dir = Path(media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    name = safe_media_name(filename)
    target = media_dir / name

    if target.exists():
        existing = target.read_bytes()
        if existing == content:
            return target
        digest = hashlib.sha256(content).hexdigest()[:8]
        stem, suffix = Path(name).stem, Path(name).suffix
        target = media_dir / f"{stem}_{digest}{suffix}"
        if target.exists() and target.read_bytes() == content:
            return target

    target.write_bytes(content)
    return target


def extract_media(
    media_dir: Path,
    filename: Optional[str],
    content: bytes,
    *,
    kind: Optional[str] = None,
    model_root: Optional[Path] = None,
) -> dict:
    """Guarda el archivo y devuelve el vector BoVW/TF-IDF y sus metadatos."""
    if not content:
        raise FeatureExtractionError("el archivo subido está vacío")

    started = time.perf_counter()
    path = save_media(media_dir, filename, content)
    try:
        features = ExtractFeatures.extract(
            path, kind=kind, model_root=model_root
        )
    except Exception:
        # Un archivo que no se pudo decodificar no debe quedar en el directorio.
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise

    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "name": path.name,
        "path": str(path),
        "kind": features.kind,
        "dimension": features.dimension,
        "vector": list(features.values),
        "json": features.to_json(),
        "mode": features.mode,
        "n_words": features.n_words,
        "sift_backend": features.backend,
        "size_bytes": path.stat().st_size,
        "elapsed_ms": round(elapsed_ms, 3),
    }


__all__ = ["extract_media", "safe_media_name", "save_media"]
