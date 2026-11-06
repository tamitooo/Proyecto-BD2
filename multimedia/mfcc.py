"""MFCC audio descriptors, shape ``(frames, n_mfcc)`` (Part 4)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np


def _librosa() -> Any:
    try:
        import librosa
    except ImportError as exc:
        raise ImportError("MFCC extraction requires librosa>=0.10.2") from exc
    return librosa


def _waveform_float32(samples: np.ndarray) -> np.ndarray:
    if samples.ndim == 2:
        if samples.shape[1] not in (1, 2):
            raise ValueError("audio must be mono or samples-by-channels stereo")
    if samples.ndim not in (1, 2):
        raise ValueError("audio must be a mono vector or samples-by-channels array")
    if np.issubdtype(samples.dtype, np.integer):
        info = np.iinfo(samples.dtype)
        if info.min < 0:
            samples = samples.astype(np.float64) / max(abs(info.min), info.max)
        else:
            center = (info.max + 1) / 2
            samples = (samples.astype(np.float64) - center) / center
    elif not np.issubdtype(samples.dtype, np.floating):
        raise TypeError("audio samples must be floating-point or PCM integers")
    samples = np.asarray(samples, dtype=np.float32)
    if not np.isfinite(samples).all():
        raise ValueError("audio samples must be finite")
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    return np.ascontiguousarray(samples)


class MFCCFeatureExtractor:
    """Reusable MFCC extractor, configured for one shared auditory vocabulary."""

    def __init__(
        self,
        *,
        sample_rate: int = 22_050,
        n_mfcc: int = 13,
        n_mels: int = 40,
        n_fft: int = 2048,
        hop_length: int = 512,
    ) -> None:
        for name, value, minimum in (
            ("sample_rate", sample_rate, 1),
            ("n_mfcc", n_mfcc, 1),
            ("n_mels", n_mels, 1),
            ("n_fft", n_fft, 2),
            ("hop_length", hop_length, 1),
        ):
            if type(value) is not int or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if n_mfcc > n_mels:
            raise ValueError("n_mfcc must not exceed n_mels")
        self.sample_rate = sample_rate
        self.n_mfcc = n_mfcc
        self.n_mels = n_mels
        self.n_fft = n_fft
        self.hop_length = hop_length

    def extract(
        self,
        audio: str | Path | bytes | bytearray | np.ndarray,
        *,
        sample_rate: int | None = None,
    ) -> np.ndarray:
        """MFCC frame by frame; ``sample_rate`` is required only for raw waveforms."""
        librosa = _librosa()
        if isinstance(audio, (str, Path)):
            if sample_rate is not None:
                raise ValueError("sample_rate must not override an audio file's metadata")
            path = Path(audio)
            if not path.is_file():
                raise FileNotFoundError(path)
            samples, _ = librosa.load(str(path), sr=self.sample_rate, mono=True)
        elif isinstance(audio, (bytes, bytearray)):
            if sample_rate is not None:
                raise ValueError("sample_rate must not override encoded audio metadata")
            import soundfile as sf
            try:
                samples, original_rate = sf.read(io.BytesIO(audio), dtype="float32", always_2d=True)
            except (RuntimeError, ValueError) as exc:
                raise ValueError("cannot decode audio bytes") from exc
            samples = _waveform_float32(samples)
            if original_rate != self.sample_rate:
                samples = librosa.resample(samples, orig_sr=original_rate, target_sr=self.sample_rate)
        elif isinstance(audio, np.ndarray):
            if type(sample_rate) is not int or sample_rate < 1:
                raise ValueError("raw waveform requires a positive sample_rate")
            samples = _waveform_float32(audio)
            if sample_rate != self.sample_rate and samples.size:
                samples = librosa.resample(samples, orig_sr=sample_rate, target_sr=self.sample_rate)
        else:
            raise TypeError("audio must be a filename, encoded audio or NumPy waveform")

        if samples.size == 0:
            return np.empty((0, self.n_mfcc), dtype=np.float32)
        result = librosa.feature.mfcc(
            y=np.asarray(samples, dtype=np.float32),
            sr=self.sample_rate,
            n_mfcc=self.n_mfcc,
            n_mels=self.n_mels,
            n_fft=self.n_fft,
            hop_length=self.hop_length,
            center=True,
            pad_mode="constant",
        ).T
        result = np.ascontiguousarray(result, dtype=np.float32)
        if result.ndim != 2 or result.shape[1] != self.n_mfcc or not np.isfinite(result).all():
            raise RuntimeError("MFCC returned invalid descriptors")
        return result


def extract_mfcc_descriptors(
    audio: str | Path | bytes | bytearray | np.ndarray,
    *,
    sample_rate: int | None = None,
    **configuration: Any,
) -> np.ndarray:
    """One-shot convenience wrapper; reuse the class for many audio files."""
    return MFCCFeatureExtractor(**configuration).extract(audio, sample_rate=sample_rate)
