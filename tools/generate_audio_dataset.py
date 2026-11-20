"""Deterministic WAV corpus for MFCC / SIMILAR_TO integration testing.

Purely synthetic audio, not speech or copyrighted material. Five independently
labeled signal families supply a stable reference for Precision@10.

    python -m tools.generate_audio_dataset --count 1000 --queries 100 --output data/audio_synthetic
    python -m tools.generate_audio_dataset --verify data/audio_synthetic

Use isolated backend/data for any media training: audio vocabulary is shared.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import wave
from pathlib import Path

import numpy as np

FAMILIES = ("tono", "doble_tono", "barrido", "pulsos", "ruido_filtrado")
FIELDS = ("id", "familia", "archivo", "frecuencia_hz", "duracion_s", "sha256")
RATE = 16000


def make_waveform(family: str, *, seed: int, seconds: float = 0.75, rate: int = RATE) -> tuple[np.ndarray, float]:
    if family not in FAMILIES or not 0.2 <= seconds <= 5 or rate < 8000:
        raise ValueError("invalid family, duration or sample rate")
    rng = random.Random(seed)
    n = round(seconds * rate)
    time = np.arange(n, dtype=np.float64) / rate
    base = rng.uniform(220, 800)
    phase = rng.uniform(0, 2 * math.pi)
    if family == "tono":
        signal = np.sin(2 * np.pi * base * time + phase)
    elif family == "doble_tono":
        signal = (0.75 * np.sin(2 * np.pi * base * time + phase)
                  + 0.40 * np.sin(2 * np.pi * base * 1.8 * time + phase))
    elif family == "barrido":
        # Linear chirp, increasing frequency 30-80% across the recording.
        sweep = rng.uniform(0.3, 0.8)
        signal = np.sin(2 * np.pi * (base * time + base * sweep * time ** 2 / (2 * seconds)) + phase)
    elif family == "pulsos":
        hz = rng.uniform(7, 13)
        signal = np.sin(2 * np.pi * base * time + phase) * (np.sin(2 * np.pi * hz * time) > 0)
    else:
        # Smooth synthetic band-limited noise: moving average reduces high-frequency power.
        raw = np.random.default_rng(seed).standard_normal(n + 32)
        width = rng.randint(4, 13)
        signal = np.convolve(raw, np.ones(width) / width, mode="valid")[:n]
    # All recordings use equal sample rate, amplitude bounds and fade duration.
    fade = max(1, round(rate * 0.018))
    envelope = np.ones(n, dtype=np.float64)
    envelope[:fade] = np.linspace(0.0, 1.0, fade)
    envelope[-fade:] = np.linspace(1.0, 0.0, fade)
    signal = signal * envelope
    peak = float(np.max(np.abs(signal)))
    if not peak or not np.isfinite(peak):
        raise ValueError("generated silence or nonfinite samples")
    samples = np.rint(signal * (0.8 / peak) * 32767).astype("<i2")
    return samples, round(base, 2)


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _wav(path: Path, samples: np.ndarray, rate: int) -> str:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(samples.tobytes())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(*, output: Path, count: int = 1000, queries: int = 100,
             seconds: float = 0.75, seed: int = 2026) -> dict:
    if count < len(FAMILIES) or queries < len(FAMILIES):
        raise ValueError("count and queries must include every family")
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    files = output / "audios"
    separate = output / "consultas"
    files.mkdir(parents=True)
    separate.mkdir()
    products = []
    tests = []
    for total, prefix, folder, offset, destination in (
        (count, "audio", files, 0, products),
        (queries, "consulta_audio", separate, 1000003, tests),
    ):
        for i in range(total):
            family = FAMILIES[i % len(FAMILIES)]
            filename = f"{prefix}_{i + 1:06d}.wav"
            waveform, freq = make_waveform(family, seed=seed + offset + 7919 * (i + 1), seconds=seconds)
            sha = _wav(folder / filename, waveform, RATE)
            destination.append({"id": i + 1, "familia": family,
                                "archivo": filename, "frecuencia_hz": freq,
                                "duracion_s": seconds, "sha256": sha})
    _write_csv(output / "audios.csv", products)
    _write_csv(output / "consultas.csv", tests)
    manifest = {"seed": seed, "count": count, "queries": queries,
                "sample_rate": RATE, "channels": 1, "bit_depth": 16,
                "duration_s": seconds, "classes": list(FAMILIES),
                "synthetic": True, "independent_queries": True}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    verify(output)
    return manifest


def verify(output: Path) -> dict:
    output = Path(output)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    counts = {}
    for csv_name, folder, key in (("audios.csv", "audios", "count"),
                                  ("consultas.csv", "consultas", "queries")):
        with (output / csv_name).open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != FIELDS:
                raise ValueError(f"incorrect CSV schema: {csv_name}")
            rows = list(reader)
        if len(rows) != manifest[key]:
            raise ValueError(f"incorrect row count: {csv_name}")
        names = set()
        for row in rows:
            name = row["archivo"]
            if name in names or name.startswith(".") or "/" in name or "\\" in name:
                raise ValueError(f"duplicate or unsafe name: {name}")
            if row["familia"] not in FAMILIES:
                raise ValueError(f"invalid class: {name}")
            path = output / folder / name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError(f"missing or corrupt WAV: {name}")
            with wave.open(str(path), "rb") as wav:
                if (wav.getnchannels() != 1 or wav.getsampwidth() != 2
                        or wav.getframerate() != manifest["sample_rate"]
                        or abs(wav.getnframes() / wav.getframerate() - float(row["duracion_s"])) > 1e-5):
                    raise ValueError(f"invalid WAV format: {name}")
            names.add(name)
        if len(list((output / folder).glob("*.wav"))) != len(rows):
            raise ValueError(f"unlisted WAV files: {folder}")
        counts[key] = len(rows)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=Path("data/audio_synthetic"))
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--queries", type=int, default=100)
    parser.add_argument("--seconds", type=float, default=0.75)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    result = (verify(args.verify) if args.verify else generate(output=args.output, count=args.count,
              queries=args.queries, seconds=args.seconds, seed=args.seed))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
