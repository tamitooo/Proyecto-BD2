"""Independent deterministic checks of one-second MFCC retrieval and silence."""
from __future__ import annotations

import numpy as np
import pytest

from audio_recognition.temporal import (
    RATE, AudioError, decode_audio, energy_db, match_audio, normalize,
    query_candidates, read_wav_bytes, temporal_align, wav_bytes, windows,
)


def melody(seed: int, seconds: int = 23) -> np.ndarray:
    """Original multi-note synthetic music fixture; not a licensed song dataset."""
    rng = np.random.default_rng(seed)
    t = np.arange(RATE) / RATE
    out = []
    for index in range(seconds):
        freq = float(160 + 17 * seed + ((index * (7 + seed)) % 13) * 27)
        notes = np.sin(2 * np.pi * freq * t) + 0.23 * np.sin(2 * np.pi * 2.03 * freq * t)
        tremolo = 0.5 + 0.4 * np.sin(2 * np.pi * (2 + index % 3) * t)**2
        notes = notes * tremolo + 0.01 * rng.normal(size=t.shape)
        out.append(notes * 0.18)
    return np.concatenate(out)


def test_audio_pcm_20_seconds_roundtrip():
    music = melody(1, 20)
    encoded = wav_bytes(music)
    assert len(read_wav_bytes(encoded)) == RATE * 20
    assert abs(energy_db(read_wav_bytes(encoded)) - energy_db(music)) < 0.1
    assert len(decode_audio(encoded, "demo.wav")) == RATE * 20


def test_silent_audio_yields_no_match_without_index_call():
    silent = np.zeros(RATE * 10)
    def fail_provider(q):
        raise AssertionError("silent query should not search index")
    result = match_audio(silent, mean=np.zeros(40), std=np.ones(40),
                         candidate_provider=fail_provider)
    assert result["status"] == "silent_or_too_short"
    assert result["active_seconds"] == 0
    assert result["silent_seconds"] == 10


def test_silent_seconds_are_skipped_and_timestamps_retained():
    song = melody(1, 12)
    song[3*RATE:5*RATE] = 0
    bins = windows(song)
    assert [w.second for w in bins if not w.active] == [3, 4]
    assert sum(w.active for w in bins) == 10


def test_temporal_align_does_not_count_repeated_hits():
    ws = windows(melody(2, 4))
    active = [w for w in ws if w.active]
    assert len(active) == 4
    same = [(11, 8, .91)] * 7
    groups = [same for _ in active]
    assert temporal_align(ws, groups, min_matched_seconds=2) == []
    aligned = [[(11, 8 + w.second, .98), (12, 4, .97)] for w in active]
    matches = temporal_align(ws, aligned, min_matched_seconds=2)
    assert matches[0]["track_id"] == 11
    assert matches[0]["reference_start_s"] == 8
    assert matches[0]["matched_seconds"] == 4


def test_identifies_offset_with_silent_query_gap():
    song = melody(2, 20)
    other = melody(7, 20)
    songw, otherw = windows(song), windows(other)
    active = [w.raw for w in songw + otherw if w.active]
    data = np.stack(active)
    mean, std = data.mean(axis=0), np.maximum(data.std(axis=0), 1e-4)
    matrix = normalize(data, mean, std)
    n_song = sum(w.active for w in songw)
    ids = np.array([1]*n_song + [2]*(len(matrix)-n_song))
    stamps = np.array([w.second for w in songw if w.active] + [w.second for w in otherw if w.active])
    excerpt = song[5*RATE:16*RATE].copy()
    excerpt[3*RATE:5*RATE] = 0
    result = match_audio(excerpt, mean=mean, std=std,
                         candidate_provider=lambda q: query_candidates(matrix,ids,stamps,q,k=len(matrix)),
                         min_similarity=.30)
    assert result["status"] == "ok"
    assert result["silent_seconds"] == 2
    assert result["matches"]
    assert result["matches"][0]["track_id"] == 1
    assert abs(result["matches"][0]["reference_start_s"] - 5) <= 1


def test_reject_invalid_audio_and_short_wav():
    with pytest.raises(AudioError):
        decode_audio(b"not audio", "x.txt")
    with pytest.raises(AudioError):
        read_wav_bytes(wav_bytes(np.zeros(RATE//2)))
    with pytest.raises(AudioError):
        decode_audio(b"", "x.wav")
