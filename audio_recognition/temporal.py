"""Timestamp-aware audio retrieval for 1-second windows of 20-second tracks.

MFCC(20) -> per-second mean/std (40D) -> corpus standardization -> L2 cosine.
Silence is deliberately excluded from the search, not treated as a match.
The existing BoAW/TF-IDF engine is left unchanged; SQL IVF uses these
fingerprints in a separate audio_segmentos table.
"""
from __future__ import annotations

import io
import math
import subprocess
import wave
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

RATE = 16000
WINDOW = RATE
N_MFCC = 20
VECTOR_SIZE = 2 * N_MFCC
SILENCE_DBFS = -48.0


class AudioError(ValueError):
    """Invalid or silent audio source; safe to show in the client."""


def wav_bytes(audio: np.ndarray, rate: int = RATE) -> bytes:
    """16-bit mono PCM WAV. Caller owns the audio and sampling rate."""
    arr = np.asarray(audio)
    if arr.ndim != 1 or rate != RATE:
        raise AudioError("expected mono 16 kHz samples")
    arr = np.clip(np.nan_to_num(arr, nan=0.0), -1.0, 1.0)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(rate)
        fh.writeframes((arr * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def read_wav_bytes(data: bytes) -> np.ndarray:
    try:
        with wave.open(io.BytesIO(data), "rb") as fh:
            if fh.getnchannels() != 1 or fh.getsampwidth() != 2 or fh.getframerate() != RATE or fh.getcomptype() != "NONE":
                raise AudioError("WAV must be uncompressed 16 kHz mono PCM16")
            raw = fh.readframes(fh.getnframes())
    except (wave.Error, EOFError) as exc:
        raise AudioError(f"invalid WAV: {exc}") from exc
    result = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0
    if result.size < RATE:
        raise AudioError("audio must contain at least one second")
    return result


def decode_audio(data: bytes, filename: str = "query.wav", *, max_seconds: int = 30) -> np.ndarray:
    """Use ffmpeg for compressed uploads; WAV PCM16 decodes natively.

    No shell, no filenames passed as arbitrary commands, a strict size/duration
    limit, and no user-controlled filesystem locations.
    """
    if not 1 <= max_seconds <= 120 or not data or len(data) > 40_000_000:
        raise AudioError("audio exceeds accepted upload limits")
    suffix = Path(filename).suffix.lower()
    if suffix in (".wav", ".wave"):
        try:
            return read_wav_bytes(data)[:max_seconds * RATE]
        except AudioError as exc:
            if "WAV must be" not in str(exc):
                raise
    elif suffix not in (".mp3", ".ogg", ".flac", ".m4a", ".aac", ".opus"):
        raise AudioError("unsupported audio format; use WAV, MP3, OGG, FLAC, M4A or AAC")
    try:
        job = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
             "-i", "pipe:0", "-t", str(max_seconds), "-ac", "1", "-ar", str(RATE),
             "-f", "s16le", "-acodec", "pcm_s16le", "pipe:1"],
            input=data, capture_output=True, timeout=35, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AudioError(f"ffmpeg decoding unavailable or timed out: {exc}") from exc
    if job.returncode or len(job.stdout) < 2 * RATE:
        raise AudioError("audio could not be decoded to 16 kHz mono PCM")
    return np.frombuffer(job.stdout, dtype="<i2").astype(np.float64) / 32768.0


def energy_db(signal: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.asarray(signal, dtype=np.float64) ** 2))) if len(signal) else 0.0
    return 20 * math.log10(max(rms, 1e-12))


def _mel_filters(rate: int = RATE, nfft: int = 512, n_mels: int = 26) -> np.ndarray:
    def hz_to_mel(f): return 2595 * np.log10(1 + np.asarray(f) / 700)
    def mel_to_hz(m): return 700 * (np.power(10.0, np.asarray(m) / 2595) - 1)
    points = mel_to_hz(np.linspace(hz_to_mel(0), hz_to_mel(rate/2), n_mels + 2))
    bins = np.clip(np.floor((nfft + 1) * points / rate).astype(int), 0, nfft//2)
    filters = np.zeros((n_mels, nfft//2 + 1), dtype=np.float64)
    for i in range(n_mels):
        left, center, right = int(bins[i]), int(bins[i+1]), int(bins[i+2])
        center = max(center, left + 1)
        right = max(right, center + 1)
        right = min(right, nfft//2 + 1)
        if left < right:
            for j in range(left, min(center, right)):
                filters[i, j] = (j - left) / (center - left)
            for j in range(center, right):
                filters[i, j] = (right - j) / max(1, right - center)
    return filters


def mfcc_frames(samples: np.ndarray) -> np.ndarray:
    """20 per-frame MFCC coefficients. 25 ms frames; 10 ms hop.

    Same parameterization and pre-emphasis convention as the existing
    ``vector.extract_features.ExtractFeatures._mfcc_frames`` implementation.
    """
    samples = np.asarray(samples, dtype=np.float64)
    samples = samples - samples.mean()
    samples = np.concatenate(([samples[0]], samples[1:] - .97 * samples[:-1]))
    frame_len, hop, nfft = 400, 160, 512
    if samples.size < frame_len:
        raise AudioError("too little audio for MFCC")
    # Avoid copying frames until window multiplication.
    frames = np.lib.stride_tricks.sliding_window_view(samples, frame_len)[::hop]
    weighted = frames * np.hamming(frame_len)
    spectrum = np.fft.rfft(weighted, n=nfft, axis=1)
    power = (np.abs(spectrum) ** 2) / nfft
    mels = np.log(power @ _mel_filters().T + 1e-10)
    n = np.arange(26)[None, :] + .5
    k = np.arange(1, N_MFCC+1)[:, None]
    dct = np.cos(np.pi / 26 * (k * n)) * np.sqrt(2 / 26)
    return mels @ dct.T


@dataclass(frozen=True)
class Window:
    second: int
    rms_db: float
    active: bool
    raw: np.ndarray


def windows(samples: np.ndarray, *, relative_db: float = 32) -> list[Window]:
    """Ignore quiet seconds relative to both noise floor and the clip peak.

    No normalization of near-silent tracks into loud fingerprints: whole-silent
    queries produce zero active windows and must never return false matches.
    """
    signal = np.asarray(samples, dtype=np.float64)
    count = len(signal) // WINDOW
    if count == 0:
        raise AudioError("audio must contain at least one complete second")
    energies = np.array([energy_db(signal[i*WINDOW:(i+1)*WINDOW]) for i in range(count)])
    threshold = max(SILENCE_DBFS, float(energies.max()) - relative_db)
    frames = mfcc_frames(signal[:count*WINDOW])
    # MFCC temporal frame centers are ~0.0125s from the audio start.
    frame_seconds = np.arange(len(frames)) * 0.01
    out = []
    for i in range(count):
        frame_slice = frames[(frame_seconds >= i) & (frame_seconds < i+1)]
        if len(frame_slice) < 2:
            raise AudioError("insufficient MFCC frames")
        raw = np.concatenate((frame_slice.mean(axis=0), frame_slice.std(axis=0)))
        active = bool(energies[i] >= threshold)
        out.append(Window(i, float(energies[i]), active, raw))
    return out


def normalize(raw: np.ndarray, mean: np.ndarray, std: np.ndarray) -> np.ndarray:
    z = (np.asarray(raw, np.float64) - mean) / np.maximum(std, 1e-4)
    norm = np.linalg.norm(z, axis=-1, keepdims=True)
    return np.divide(z, norm, out=np.zeros_like(z), where=norm > 1e-12).astype(np.float32)


def temporal_align(query_windows: list[Window], candidates: list[list[tuple[int, int, float]]],
                   *, top_k: int = 10, min_similarity: float = 0.60,
                   min_matched_seconds: int = 2) -> list[dict]:
    """Align (track_id, reference second) to each active query second.

    Match offset = reference_second - query_second. For each song/offset,
    count only the best match for a given query second to prevent inflation
    from repeated frames or dense candidate output.
    """
    active = [w for w in query_windows if w.active]
    if len(active) < min_matched_seconds:
        return []
    if len(active) != len(candidates):
        raise ValueError("one candidate list required per active query window")
    groups: dict[tuple[int, int], dict[int, float]] = defaultdict(dict)
    for window, hits in zip(active, candidates):
        for track_id, second, score in hits:
            if track_id < 1 or second < 0 or not np.isfinite(score) or score < min_similarity:
                continue
            key = (int(track_id), int(second) - window.second)
            old = groups[key].get(window.second, -1.)
            groups[key][window.second] = max(old, float(score))
    best_by_track: dict[int, dict] = {}
    for (track_id, offset), hits in groups.items():
        if len(hits) < min_matched_seconds:
            continue
        coverage = len(hits) / len(active)
        mean_score = sum(hits.values()) / len(hits)
        # Require temporal consistency, not one impressive but isolated match.
        score = float(coverage * mean_score)
        row = {"track_id": track_id, "score": round(score, 6),
               "mean_similarity": round(mean_score, 6), "coverage": round(coverage, 6),
               "matched_seconds": len(hits), "query_active_seconds": len(active),
               "offset_seconds": offset, "reference_start_s": max(0, offset),
               "query_start_s": max(0, -offset)}
        previous = best_by_track.get(track_id)
        if previous is None or score > previous["score"]:
            best_by_track[track_id] = row
    return sorted(best_by_track.values(), key=lambda x: (-x["score"], x["track_id"]))[:top_k]


def query_candidates(index_vectors: np.ndarray, track_ids: np.ndarray,
                     seconds: np.ndarray, query_vectors: np.ndarray,
                     *, k: int = 25) -> list[list[tuple[int,int,float]]]:
    """Offline exact-cosine baseline. The online route uses SQL IVF by default."""
    if not 1 <= k <= 1000 or len(index_vectors) != len(track_ids) or len(seconds) != len(track_ids):
        raise ValueError("invalid audio index shape or candidate count")
    scores = query_vectors @ np.asarray(index_vectors).T
    result = []
    for vals in scores:
        length = min(k, len(vals))
        if length == 0:
            result.append([]); continue
        picks = np.argpartition(vals, len(vals)-length)[-length:]
        picks = sorted(picks, key=lambda j:(-float(vals[j]), int(track_ids[j]), int(seconds[j])))
        result.append([(int(track_ids[j]), int(seconds[j]), float(vals[j])) for j in picks])
    return result


def match_audio(audio: np.ndarray, *, mean: np.ndarray, std: np.ndarray,
                candidate_provider, top_k: int = 10, min_similarity: float = .60) -> dict:
    frames = windows(audio)
    active = [f for f in frames if f.active]
    seconds = [{"second": f.second, "active": f.active,
                "rms_db": round(f.rms_db, 2)} for f in frames]
    if len(active) < 2:
        return {"status": "silent_or_too_short", "total_seconds": len(frames),
                "active_seconds": len(active), "silent_seconds": len(frames)-len(active),
                "seconds": seconds, "matches": []}
    query = normalize(np.stack([w.raw for w in active]), mean, std)
    candidates = candidate_provider(query)
    return {"status": "ok", "total_seconds": len(frames),
            "active_seconds": len(active), "silent_seconds": len(frames)-len(active),
            "seconds": seconds,
            "matches": temporal_align(frames, candidates, top_k=top_k, min_similarity=min_similarity)}
