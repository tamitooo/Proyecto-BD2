"""Extracción de características multimedia (Parte 4, sección 2.4.1).

Este módulo conecta un archivo con el motor vectorial mediante la pipeline del
enunciado:

```text
imagen  -> SIFT denso  -> descriptores locales (128-D)
audio   -> MFCC        -> descriptores locales (20-D)
        -> K-Means (vocabulario compartido, K palabras)
        -> histograma de K palabras
        -> TF-IDF -> vector de dimensión K
```

El vocabulario y el IDF se entrenan una vez sobre una muestra del corpus y se
guardan en ``<model_root>/bow_image.npz`` y ``bow_audio.npz``. La misma
representación se usa al indexar (``EXTRACT_FEATURES``) y al consultar
(``SIMILAR_TO('archivo')``); si se usaran vocabularios distintos, los vectores
no serían comparables.

Para entrenar el vocabulario:

```powershell
python -m tools.train_feature_model --images backend/data/media --audio backend/data/media
```

Los detalles de SIFT, K-Means y TF-IDF están en
``docs/extraccion_caracteristicas.md``.
"""

from __future__ import annotations

import io
import json
import math
import os
import shutil
import subprocess
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple, Union

AUDIO_DESCRIPTOR_DIM = 20

AUDIO_FRAME_SECONDS = 0.025
AUDIO_HOP_SECONDS = 0.010
AUDIO_MELS = 26
AUDIO_MFCC = AUDIO_DESCRIPTOR_DIM
AUDIO_MAX_FRAMES = 2000

_IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".gif",
    ".webp",
    ".tif",
    ".tiff",
    ".ppm",
    ".pgm",
    ".pnm",
}
_AUDIO_EXTENSIONS = {".wav", ".wave"}
# Formatos que ffmpeg puede convertir a WAV PCM. No se decodifican en Python.
_COMPRESSED_AUDIO_EXTENSIONS = {
    ".mp3",
    ".ogg",
    ".oga",
    ".flac",
    ".m4a",
    ".aac",
    ".wma",
    ".opus",
}
_UNSUPPORTED_MEDIA_EXTENSIONS = {
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".webm",
    ".heic",
}

MediaSource = Union[str, os.PathLike, bytes, bytearray]


class FeatureExtractionError(Exception):
    """El archivo no existe, no se puede decodificar o falta el vocabulario."""


@dataclass(frozen=True)
class FeatureVector:
    """Vector BoVW/TF-IDF listo para guardar como JSON o usar en una consulta."""

    values: Tuple[float, ...]
    kind: str
    source: str
    mode: str = "bow"
    n_words: Optional[int] = None
    backend: Optional[str] = None

    @property
    def dimension(self) -> int:
        return len(self.values)

    def to_json(self) -> str:
        return json.dumps(
            [round(float(value), 6) for value in self.values],
            separators=(",", ":"),
        )

    def preview(self, count: int = 6) -> str:
        non_zero = [value for value in self.values if abs(value) > 1e-9]
        selected = non_zero[:count] if non_zero else list(self.values[:count])
        head = ", ".join(f"{value:.6f}" for value in selected)
        return f"[{head}, ...] ({self.dimension} dims)"


def default_media_root(catalog=None) -> Optional[Path]:
    """Directorio donde el API guarda los archivos subidos."""
    env = os.environ.get("BD2_MEDIA_DIR")
    if env:
        return Path(env)
    data_dir = getattr(catalog, "data_dir", None) if catalog is not None else None
    return Path(data_dir) / "media" if data_dir is not None else None


def default_model_root(catalog=None) -> Path:
    """Directorio de los vocabularios BoVW (``bow_image.npz``, ``bow_audio.npz``)."""
    env = os.environ.get("BD2_MODEL_DIR")
    if env:
        return Path(env)
    data_dir = getattr(catalog, "data_dir", None) if catalog is not None else None
    if data_dir is not None:
        return Path(data_dir) / "models"
    return Path(__file__).resolve().parents[1] / "models"


def _media_roots(media_root: Optional[Path]) -> list[Path]:
    roots: list[Path] = []
    if media_root is not None:
        roots.append(Path(media_root))
    env = os.environ.get("BD2_MEDIA_DIR")
    if env:
        roots.append(Path(env))
    roots.append(Path.cwd())
    repo = Path(__file__).resolve().parents[1]
    roots.append(repo)
    roots.append(repo / "backend" / "data" / "media")
    roots.append(repo / "media")

    deduped: list[Path] = []
    seen = set()
    for root in roots:
        try:
            key = str(Path(root).resolve()).lower()
        except OSError:
            key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(Path(root))
    return deduped


def resolve_media_path(reference: str | os.PathLike, *, media_root=None) -> Path:
    """Resuelve ``'foto.jpg'`` contra el directorio de medios, el cwd y el repo."""
    text = str(reference).strip()
    if not text:
        raise FeatureExtractionError("la ruta del archivo multimedia está vacía")

    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        if candidate.is_file():
            return candidate.resolve()
        raise FeatureExtractionError(
            f"no se encontró el archivo multimedia '{text}'"
        )

    roots = _media_roots(media_root)
    for root in roots:
        path = root / candidate
        try:
            if path.is_file():
                return path.resolve()
        except OSError:
            continue
    searched = ", ".join(str(root) for root in roots)
    raise FeatureExtractionError(
        f"no se encontró el archivo multimedia '{text}'; se buscó en: {searched}"
    )


def _sniff_kind(head: bytes) -> Optional[str]:
    """Detecta el tipo por los primeros bytes (para archivos sin extensión)."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if head.startswith(b"\xff\xd8\xff"):
        return "image"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image"
    if head.startswith(b"BM"):
        return "image"
    if head.startswith((b"II*\x00", b"MM\x00*")):
        return "image"
    if head.startswith(b"RIFF") and len(head) >= 12 and head[8:12] == b"WAVE":
        return "audio"
    if head.startswith(b"ID3") or (
        len(head) >= 2 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0
    ):
        return "audio"  # MP3/ADTS; ffmpeg lo convierte a WAV
    return None


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def looks_like_media(reference: str, *, media_root=None) -> bool:
    """¿El objetivo de ``SIMILAR_TO`` parece un archivo y no una columna?"""
    if not isinstance(reference, str):
        return False
    text = reference.strip()
    if not text:
        return False
    suffix = Path(text).suffix.lower()
    if (
        suffix in _IMAGE_EXTENSIONS
        or suffix in _AUDIO_EXTENSIONS
        or suffix in _COMPRESSED_AUDIO_EXTENSIONS
        or suffix in _UNSUPPORTED_MEDIA_EXTENSIONS
    ):
        return True
    try:
        path = resolve_media_path(text, media_root=media_root)
        with open(path, "rb") as handle:
            head = handle.read(16)
    except (FeatureExtractionError, OSError):
        return False
    return _sniff_kind(head) is not None


def _normalize_kind(kind: Optional[str]) -> Optional[str]:
    if kind is None:
        return None
    normalized = kind.strip().lower()
    if normalized in {"image", "imagen", "img", "foto", "photo"}:
        return "image"
    if normalized in {"audio", "sonido", "sound", "wav"}:
        return "audio"
    raise FeatureExtractionError(
        f"tipo de medio no soportado: {kind!r}; usa 'image' o 'audio'"
    )


class ExtractFeatures:
    """Extrae un vector BoVW/TF-IDF de una imagen o un audio.

    Uso::

        vector = ExtractFeatures.extract("foto.jpg")
        vector.dimension   # K palabras del vocabulario
        vector.to_json()   # '[0.0,...]' para una columna VARCHAR

    El vocabulario debe existir en ``model_root`` (por defecto
    ``<data_dir>/models``). Para entrenarlo:

        python -m tools.train_feature_model --images <carpeta> --audio <carpeta>
    """

    @classmethod
    def local_descriptors(
        cls,
        source: MediaSource,
        *,
        kind: Optional[str] = None,
        filename: Optional[str] = None,
        media_root=None,
    ):
        """Descriptores locales antes de cuantizar: SIFT (n,128) o MFCC (n,20)."""
        data, display_name, path = cls._read_source(
            source, filename=filename, media_root=media_root
        )
        detected = _normalize_kind(kind) or cls._detect_kind(
            data, filename or display_name
        )
        return cls._descriptors_from_data(
            data,
            detected,
            display_name,
            path=path,
            filename=filename,
            media_root=media_root,
        )

    @classmethod
    def extract(
        cls,
        source: MediaSource,
        *,
        kind: Optional[str] = None,
        filename: Optional[str] = None,
        media_root=None,
        model_root=None,
        model=None,
    ) -> FeatureVector:
        data, display_name, path = cls._read_source(
            source, filename=filename, media_root=media_root
        )
        detected = _normalize_kind(kind) or cls._detect_kind(
            data, filename or display_name
        )
        descriptors = cls._descriptors_from_data(
            data,
            detected,
            display_name,
            path=path,
            filename=filename,
            media_root=media_root,
        )
        if descriptors.shape[0] == 0:
            raise FeatureExtractionError(
                f"no se detectaron descriptores {detected.upper()} en "
                f"'{display_name}'; usa una imagen con textura o un audio con "
                f"señal"
            )

        backend = None
        if detected == "image":
            try:
                from vector.sift import sift_backend
            except ImportError as exc:  # pragma: no cover
                raise FeatureExtractionError(
                    "SIFT requiere numpy y Pillow"
                ) from exc
            backend = sift_backend()

        if model is None:
            root = (
                Path(model_root)
                if model_root is not None
                else default_model_root()
            )
            try:
                from vector.bow import BowError, FeatureModel, model_path
            except ImportError as exc:  # pragma: no cover
                raise FeatureExtractionError(
                    "la cuantización BoVW requiere numpy"
                ) from exc
            target = model_path(root, detected)
            if not target.is_file():
                raise FeatureExtractionError(
                    f"no hay vocabulario BoVW para {detected} en '{target}'; "
                    f"entrena con `python -m tools.train_feature_model`"
                )
            try:
                model = FeatureModel.load(target)
            except BowError as exc:
                raise FeatureExtractionError(str(exc)) from exc

        if model.kind != detected:
            raise FeatureExtractionError(
                f"el vocabulario es de tipo '{model.kind}' y el archivo es "
                f"'{detected}'"
            )
        if (
            backend is not None
            and model.descriptor_backend is not None
            and model.descriptor_backend != backend
        ):
            raise FeatureExtractionError(
                f"el vocabulario de imagen se entrenó con SIFT backend "
                f"'{model.descriptor_backend}' y ahora está disponible "
                f"'{backend}'; reentrena con tools.train_feature_model"
            )

        encoded = model.encode(descriptors)
        if not any(abs(float(value)) > 1e-12 for value in encoded):
            raise FeatureExtractionError(
                f"el vector BoVW de '{display_name}' quedó vacío"
            )

        return FeatureVector(
            values=tuple(round(float(value), 6) for value in encoded),
            kind=detected,
            source=str(path) if path is not None else display_name,
            mode="bow",
            n_words=model.n_words,
            backend=backend,
        )

    # ------------------------------------------------------------- internos
    @staticmethod
    def _read_source(
        source: MediaSource,
        *,
        filename: Optional[str],
        media_root,
    ) -> tuple[bytes, str, Optional[Path]]:
        if isinstance(source, (bytes, bytearray)):
            return bytes(source), filename or "<memoria>", None
        if isinstance(source, (str, os.PathLike)):
            text = str(source)
            suffix = Path(text).suffix.lower()
            if suffix in _UNSUPPORTED_MEDIA_EXTENSIONS:
                raise FeatureExtractionError(
                    f"el formato '{suffix}' no está soportado; usa imágenes "
                    "JPG/PNG/BMP/GIF/WebP/TIFF o audio WAV/MP3/OGG/FLAC/M4A"
                )
            path = resolve_media_path(source, media_root=media_root)
            return path.read_bytes(), path.name, path
        raise FeatureExtractionError(
            "origen no soportado; usa una ruta de archivo o bytes"
        )

    @staticmethod
    def _detect_kind(data: bytes, name: Optional[str]) -> str:
        suffix = Path(name).suffix.lower() if name else ""
        if suffix in _IMAGE_EXTENSIONS:
            return "image"
        if suffix in _AUDIO_EXTENSIONS or suffix in _COMPRESSED_AUDIO_EXTENSIONS:
            return "audio"
        if suffix in _UNSUPPORTED_MEDIA_EXTENSIONS:
            raise FeatureExtractionError(
                f"el formato '{suffix}' no está soportado; usa imágenes "
                "JPG/PNG/BMP/GIF/WebP/TIFF o audio WAV/MP3/OGG/FLAC/M4A"
            )
        sniffed = _sniff_kind(data[:16])
        if sniffed is not None:
            return sniffed
        raise FeatureExtractionError(
            f"no se pudo determinar el tipo de medio de '{name or 'los bytes'}'; "
            "usa una extensión conocida o indica kind='image'/'audio'"
        )

    @classmethod
    def _descriptors_from_data(
        cls,
        data: bytes,
        kind: str,
        display_name: str,
        *,
        path: Optional[Path] = None,
        filename: Optional[str] = None,
        media_root=None,
    ):
        if kind == "image":
            try:
                from vector.sift import sift_descriptors_from_bytes
            except ImportError as exc:  # pragma: no cover
                raise FeatureExtractionError(
                    "SIFT requiere numpy y Pillow"
                ) from exc
            try:
                return sift_descriptors_from_bytes(data)
            except Exception as exc:
                raise FeatureExtractionError(
                    f"no se pudo calcular SIFT de '{display_name}': {exc}"
                ) from exc
        if kind == "audio":
            wav_data = cls._audio_as_wav(
                data,
                source_name=display_name,
                path=path,
                filename=filename,
                media_root=media_root,
            )
            return cls._mfcc_frames(wav_data, display_name)
        raise FeatureExtractionError(f"tipo de medio no soportado: {kind}")

    @classmethod
    def _audio_as_wav(
        cls,
        data: bytes,
        *,
        source_name: str,
        path: Optional[Path],
        filename: Optional[str],
        media_root,
    ) -> bytes:
        """Devuelve WAV PCM; los formatos comprimidos se convierten con ffmpeg."""
        suffix = Path(filename or (path.name if path else "")).suffix.lower()
        if suffix in _AUDIO_EXTENSIONS:
            return data
        if suffix in _COMPRESSED_AUDIO_EXTENSIONS:
            return cls._convert_audio_with_ffmpeg(
                data,
                source_name=source_name,
                suffix=suffix,
                path=path,
                media_root=media_root,
            )
        # Bytes sin extensión: si el magic es WAV, ya está listo; si es MP3,
        # intentar la conversión.
        sniffed = _sniff_kind(data[:16])
        if sniffed == "audio":
            if data.startswith(b"RIFF"):
                return data
            return cls._convert_audio_with_ffmpeg(
                data,
                source_name=source_name,
                suffix=suffix or ".audio",
                path=path,
                media_root=media_root,
            )
        raise FeatureExtractionError(
            f"'{source_name}' no parece un audio WAV/MP3/OGG/FLAC/M4A"
        )

    @staticmethod
    def _convert_audio_with_ffmpeg(
        data: bytes,
        *,
        source_name: str,
        suffix: str,
        path: Optional[Path],
        media_root,
    ) -> bytes:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise FeatureExtractionError(
                f"el formato '{suffix}' necesita ffmpeg para convertirse a WAV; "
                "instala ffmpeg o convierte el archivo a WAV PCM"
            )

        root = (
            Path(media_root)
            if media_root is not None
            else (path.parent if path is not None else Path.cwd())
        )
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FeatureExtractionError(
                f"no se pudo crear el directorio temporal de conversión: {exc}"
            ) from exc

        token = uuid.uuid4().hex
        temporary_input: Optional[Path] = None
        if path is None:
            temporary_input = root / f".upload_{token}{suffix}"
            temporary_input.write_bytes(data)
            input_path = temporary_input
        else:
            input_path = path
        output_path = root / f".convert_{token}.wav"

        try:
            command = [
                ffmpeg,
                "-nostdin",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(input_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-f",
                "wav",
                str(output_path),
            ]
            kwargs = {}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            completed = subprocess.run(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                **kwargs,
            )
            if completed.returncode != 0 or not output_path.is_file():
                raise FeatureExtractionError(
                    f"ffmpeg no pudo convertir '{source_name}' ({suffix}) a WAV"
                )
            return output_path.read_bytes()
        finally:
            output_path.unlink(missing_ok=True)
            if temporary_input is not None:
                temporary_input.unlink(missing_ok=True)

    # --------------------------------------------------------------- audio
    @classmethod
    def _mfcc_frames(cls, data: bytes, source_name: str):
        """MFCC por trama: matriz (n_tramas, 20), sin agregar en el tiempo."""
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover
            raise FeatureExtractionError("MFCC requiere numpy") from exc

        try:
            with wave.open(io.BytesIO(data), "rb") as handle:
                if handle.getcomptype() != "NONE":
                    raise FeatureExtractionError(
                        f"el WAV '{source_name}' está comprimido; usa PCM sin compresión"
                    )
                channels = handle.getnchannels()
                width = handle.getsampwidth()
                rate = handle.getframerate()
                raw = handle.readframes(handle.getnframes())
        except (wave.Error, EOFError, RuntimeError, ValueError) as exc:
            raise FeatureExtractionError(
                f"no se pudo leer el WAV '{source_name}': {exc}"
            ) from exc

        if not raw:
            raise FeatureExtractionError(f"el audio '{source_name}' no tiene muestras")

        dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
        if dtype is None:
            raise FeatureExtractionError(
                f"el WAV '{source_name}' usa {width * 8} bits por muestra; "
                "se soportan PCM de 8, 16 y 32 bits"
            )

        samples = np.frombuffer(raw, dtype=dtype).astype(np.float64)
        if width == 1:
            samples = (samples - 128.0) / 128.0
        else:
            samples = samples / float(1 << (8 * width - 1))

        if channels > 1:
            if samples.size % channels:
                samples = samples[: samples.size - samples.size % channels]
            samples = samples.reshape(-1, channels).mean(axis=1)
        if samples.size == 0:
            raise FeatureExtractionError(f"el audio '{source_name}' no tiene muestras")

        samples = samples - float(samples.mean())
        if samples.size > 1:
            samples = np.concatenate(
                ([samples[0]], samples[1:] - 0.97 * samples[:-1])
            )

        frame_length = max(16, int(round(rate * AUDIO_FRAME_SECONDS)))
        hop = max(1, int(round(rate * AUDIO_HOP_SECONDS)))
        if samples.size < frame_length:
            samples = np.pad(samples, (0, frame_length - samples.size))

        total_frames = 1 + (samples.size - frame_length) // hop
        if total_frames > AUDIO_MAX_FRAMES:
            indices = np.linspace(0, total_frames - 1, AUDIO_MAX_FRAMES).astype(int)
        else:
            indices = np.arange(total_frames)
        offsets = indices * hop

        window = np.hamming(frame_length)
        frames = np.stack(
            [samples[offset : offset + frame_length] * window for offset in offsets]
        )
        n_fft = 1 << (frame_length - 1).bit_length()
        if n_fft < 256:
            n_fft = 256

        spectrum = np.fft.rfft(frames, n=n_fft, axis=1)
        power = (np.abs(spectrum) ** 2) / n_fft
        filters = cls._mel_filterbank(rate, n_fft, AUDIO_MELS)
        log_mel = np.log(power @ filters.T + 1e-10)
        return log_mel @ cls._dct_matrix(AUDIO_MELS, AUDIO_MFCC).T

    @staticmethod
    def _mel_filterbank(rate: int, n_fft: int, n_mels: int):
        import numpy as np

        def hz_to_mel(frequency: float) -> float:
            return 2595.0 * math.log10(1.0 + frequency / 700.0)

        def mel_to_hz(mel: float) -> float:
            return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

        mel_points = np.linspace(
            hz_to_mel(0.0), hz_to_mel(rate / 2.0), n_mels + 2
        )
        hz_points = mel_to_hz(mel_points)
        bins = np.floor((n_fft + 1) * hz_points / rate).astype(int)
        bins = np.clip(bins, 0, n_fft // 2)

        filters = np.zeros((n_mels, n_fft // 2 + 1))
        for index in range(1, n_mels + 1):
            left, center, right = bins[index - 1], bins[index], bins[index + 1]
            if center <= left:
                center = left + 1
            if right <= center:
                right = center + 1
            if right > n_fft // 2:
                right = n_fft // 2
            for frequency in range(left, min(center, n_fft // 2 + 1)):
                filters[index - 1, frequency] = (frequency - left) / max(
                    1, center - left
                )
            for frequency in range(center, min(right, n_fft // 2 + 1)):
                filters[index - 1, frequency] = (right - frequency) / max(
                    1, right - center
                )
        return filters

    @staticmethod
    def _dct_matrix(n_mels: int, n_mfcc: int):
        import numpy as np

        mel = np.arange(n_mels)
        coefficient = np.arange(1, n_mfcc + 1)[:, None]
        return np.cos(
            np.pi / n_mels * (mel + 0.5) * coefficient
        ) * math.sqrt(2.0 / n_mels)


def extract_features(source: MediaSource, **kwargs) -> Tuple[float, ...]:
    """Atajo para scripts: devuelve solo la tupla de valores."""
    return ExtractFeatures.extract(source, **kwargs).values


__all__ = [
    "AUDIO_DESCRIPTOR_DIM",
    "ExtractFeatures",
    "FeatureExtractionError",
    "FeatureVector",
    "default_media_root",
    "default_model_root",
    "extract_features",
    "looks_like_media",
    "resolve_media_path",
]
