"""Build licensed 20-second song clips, 1-s fingerprints and an offline index.

Reads a manifest from discover_licensed_music.py or a user-supplied manifest
with the same fields. Sources must be approved local files or explicitly
permitted Jamendo HTTPS download URLs; no copyrighted chart scraping.

This script saves genuine (not generated-noise) audio with provenance, computes
silence-aware MFCC vectors, and prepares the CSV for SQL IVF import.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import numpy as np

from audio_recognition.temporal import (RATE, AudioError, energy_db, normalize,
                                        read_wav_bytes, wav_bytes, windows)

CATALOG_FIELDS = ("id", "title", "artist", "genre", "audio", "source_page",
                  "license_url", "source_id", "source_start_s", "sha256")
SEGMENT_FIELDS = ("id", "track_id", "segundo", "rms_db", "embedding")


def read_manifest(path: Path) -> list[dict]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        required = {"id", "title", "artist", "genre", "source_url", "license_url", "source_page"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise AudioError(f"manifest needs columns: {sorted(required)}")
        rows = list(reader)
    if not rows:
        raise AudioError("empty music manifest")
    ids = [int(r["id"]) for r in rows]
    if len(set(ids)) != len(ids) or min(ids) < 1:
        raise AudioError("duplicate or invalid track ID")
    return rows


def fetch_source(row: dict, base: Path, *, allow_download: bool = False) -> bytes:
    src = str(row["source_url"])
    parsed = urlparse(src)
    if parsed.scheme in ("https", "http"):
        if not allow_download:
            raise AudioError("download not enabled; pass --allow-download for licensed Jamendo tracks")
        from tools.discover_licensed_music import permitted_track
        if not permitted_track({"license_ccurl": row["license_url"], "audiodownload": src,
                                "audiodownload_allowed": True, "duration": 20}):
            raise AudioError("remote source/Creative Commons license is not approved")
        request = Request(src, headers={"User-Agent": "BD2-Academic-CC-Audio/1.0"})
        with urlopen(request, timeout=50) as response:
            # Reject an unexpected redirect to a non-Jamendo host.
            final = urlparse(response.geturl())
            host = (final.hostname or "").lower()
            if final.scheme != "https" or not (host == "storage.jamendo.com" or host.endswith(".storage.jamendo.com")):
                raise AudioError("download redirected outside approved Jamendo CDN")
            data = response.read(30_000_001)
        if len(data) > 30_000_000:
            raise AudioError("download exceeds 30 MB cap")
        return data
    if parsed.scheme:
        raise AudioError("unsupported source URL scheme")
    path = (base / src).resolve()
    if not path.is_relative_to(base.resolve()):
        raise AudioError("source path escapes the authorized manifest directory")
    if not path.is_file():
        raise AudioError(f"missing local licensed audio: {path}")
    if path.stat().st_size > 30_000_000:
        raise AudioError("local input exceeds 30 MB cap")
    return path.read_bytes()


def prepare_clip(source: bytes, name: str, *, clip_seconds: int = 20,
                 scan_seconds: int = 90) -> tuple[np.ndarray, int]:
    from audio_recognition.temporal import decode_audio
    if not 2 <= clip_seconds <= 30 or not clip_seconds <= scan_seconds <= 120:
        raise AudioError("invalid clipping duration")
    decoded = decode_audio(source, name, max_seconds=scan_seconds)
    if len(decoded) < clip_seconds * RATE:
        raise AudioError(f"track shorter than {clip_seconds}s")
    seconds = len(decoded) // RATE
    # Highest-energy 20s region in the first scan_seconds (avoids silent intros).
    one_second = np.asarray([np.mean(decoded[j*RATE:(j+1)*RATE] ** 2) for j in range(seconds)])
    sums = np.convolve(one_second, np.ones(clip_seconds), mode="valid")
    offset = int(np.argmax(sums))
    clip = decoded[offset*RATE:(offset+clip_seconds)*RATE]
    if energy_db(clip) < -55:
        raise AudioError("track contains no meaningful non-silent 20s segment")
    return clip, offset


def write_csv(path: Path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build(manifest: Path, output: Path, *, allow_download: bool = False,
          limit: int | None = None) -> dict:
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    media = output / "media"
    media.mkdir(exist_ok=True)
    manifest = Path(manifest)
    rows = read_manifest(manifest)
    if limit is not None:
        if limit < 1: raise ValueError("limit must be positive")
        rows = rows[:limit]
    catalog, raw_segments = [], []
    old_catalog = {}
    old_path = output / "catalog.csv"
    if old_path.is_file():
        with old_path.open(encoding="utf-8", newline="") as stream:
            old_catalog = {int(x["id"]): x for x in csv.DictReader(stream)}
    failures = []
    for i, row in enumerate(rows, 1):
        track_id = int(row["id"])
        filename = f"music20_{track_id:06d}.wav"
        target = media / filename
        try:
            if target.is_file():
                previous = old_catalog.get(track_id)
                if previous is None or previous.get("source_id", "") != row.get("source_id", ""):
                    raise AudioError("existing clip lacks matching provenance; use a fresh output directory")
                existing = target.read_bytes()
                if hashlib.sha256(existing).hexdigest() != previous.get("sha256"):
                    raise AudioError("existing clip checksum changed; use fresh output directory")
                audio = read_wav_bytes(existing)
                offset = int(previous["source_start_s"])
            else:
                content = fetch_source(row, manifest.parent, allow_download=allow_download)
                audio, offset = prepare_clip(content, row["source_url"].rsplit("/",1)[-1])
                target.write_bytes(wav_bytes(audio))
            if len(audio) != 20 * RATE:
                raise AudioError("expected exactly 20 seconds per index track")
            features = windows(audio)
            if sum(w.active for w in features) < 3:
                raise AudioError("too much silence to index a song")
            raw_segments.extend((track_id, w.second, w.rms_db, w.raw) for w in features if w.active)
            catalog.append({"id": track_id, "title": row["title"], "artist": row["artist"],
                            "genre": row["genre"], "audio": filename,
                            "source_page": row["source_page"],
                            "license_url": (row["license_url"].replace("http://creativecommons.org/", "https://creativecommons.org/")),
                            "source_id": row.get("source_id", ""),
                            "source_start_s": offset,
                            "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        except (AudioError, OSError, ValueError, subprocess.SubprocessError) as exc:
            if not target.exists() or track_id not in old_catalog:
                target.unlink(missing_ok=True)
            failures.append({"id": row["id"], "error": str(exc)})
        if i % 25 == 0 or i == len(rows):
            print(f"processed {i}/{len(rows)} tracks, accepted {len(catalog)}", flush=True)
    if not catalog:
        raise AudioError("no valid licensed audio clips were indexed")
    matrix = np.stack([item[3] for item in raw_segments])
    mean = matrix.mean(axis=0)
    std = np.maximum(matrix.std(axis=0), 1e-4)
    normalized = normalize(matrix, mean, std)
    segment_rows = [dict(id=k+1, track_id=int(item[0]), segundo=int(item[1]),
                         rms_db=round(float(item[2]), 3),
                         embedding=json.dumps([round(float(x), 6) for x in normalized[k]], separators=(",", ":")))
                    for k,item in enumerate(raw_segments)]
    write_csv(output / "catalog.csv", CATALOG_FIELDS, catalog)
    write_csv(output / "audio_segmentos.csv", SEGMENT_FIELDS, segment_rows)
    np.savez_compressed(output / "audio_index.npz", embedding=normalized,
                        track_id=np.asarray([item[0] for item in raw_segments], dtype=np.int32),
                        segundo=np.asarray([item[1] for item in raw_segments], dtype=np.int32),
                        mean=mean, std=std)
    (output / "failures.json").write_text(json.dumps(failures, indent=2), encoding="utf-8")
    report = {"requested": len(rows), "accepted": len(catalog), "rejected": len(failures),
              "segments": len(segment_rows), "seconds_per_clip": 20,
              "genre_counts": {g:sum(x["genre"]==g for x in catalog) for g in sorted(set(x["genre"] for x in catalog))},
              "note": "MFCC temporal fingerprints; songs were not synthetically generated"}
    (output / "build_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    return report


def verify(output: Path, *, minimum_per_genre: int = 0) -> dict:
    from audio_recognition.temporal import RATE
    output=Path(output)
    with (output / "catalog.csv").open(encoding="utf-8",newline="") as f:
        rows=list(csv.DictReader(f))
    with (output / "audio_segmentos.csv").open(encoding="utf-8",newline="") as f:
        segments=list(csv.DictReader(f))
    if not rows or not segments or len(set(int(r["id"]) for r in rows)) != len(rows):
        raise AudioError("missing, duplicated, or empty dataset records")
    ids = {int(r["id"]) for r in rows}
    index = np.load(output / "audio_index.npz", allow_pickle=False)
    n = len(segments)
    if index["embedding"].shape != (n, 40) or len(index["track_id"]) != n:
        raise AudioError("segment vector/index dimensions mismatch")
    for row in rows:
        filename = row["audio"]
        if filename != Path(filename).name or not filename.endswith(".wav"):
            raise AudioError("unsafe media filename")
        raw = (output / "media" / filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise AudioError("audio checksum mismatch")
        if len(read_wav_bytes(raw)) != RATE * 20:
            raise AudioError("wrong WAV duration")
    for row in segments:
        if int(row["track_id"]) not in ids or int(row["segundo"]) not in range(20):
            raise AudioError("orphan or invalid segment")
        v=json.loads(row["embedding"])
        if len(v)!=40 or not all(math.isfinite(float(x)) for x in v):
            raise AudioError("invalid segment embedding")
    genre_counts = {g:sum(r["genre"] == g for r in rows) for g in set(r["genre"] for r in rows)}
    if minimum_per_genre:
        from tools.discover_licensed_music import GENRES
        if any(genre_counts.get(g, 0) < minimum_per_genre for g in GENRES):
            raise AudioError(f"dataset does not meet {minimum_per_genre} tracks in each of {len(GENRES)} genres")
    return {"tracks": len(rows), "segments": n, "all_sha256_valid": True,
            "genre_counts": genre_counts}


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--manifest",type=Path)
    p.add_argument("--output",type=Path,default=Path("data/music20"))
    p.add_argument("--allow-download",action="store_true")
    p.add_argument("--limit",type=int)
    p.add_argument("--verify",action="store_true")
    p.add_argument("--minimum-per-genre",type=int,default=0)
    args=p.parse_args(argv)
    if args.verify:
        print(json.dumps(verify(args.output,minimum_per_genre=args.minimum_per_genre), indent=2)); return 0
    if not args.manifest:
        p.error("--manifest required unless --verify")
    print(json.dumps(build(args.manifest, args.output, allow_download=args.allow_download, limit=args.limit), indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
