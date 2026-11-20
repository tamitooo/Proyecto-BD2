"""Synthetic audio generator format, consistency, and corruption checks."""
from __future__ import annotations

import hashlib
import wave

import numpy as np
import pytest

from tools.generate_audio_dataset import FAMILIES, RATE, generate, make_waveform, verify


def test_audio_has_correct_format_classes_and_ground_truth(tmp_path):
    out = tmp_path / "audio"
    generate(output=out, count=15, queries=10, seed=41, seconds=0.35)
    assert verify(out) == {"count": 15, "queries": 10}
    assert len(list((out / "audios").glob("*.wav"))) == 15
    assert len(list((out / "consultas").glob("*.wav"))) == 10
    with wave.open(str(out / "audios" / "audio_000001.wav"), "rb") as f:
        assert f.getframerate() == RATE
        assert f.getnchannels() == 1
        assert f.getsampwidth() == 2


def test_audio_deterministic_by_seed_even_across_runs(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    generate(output=first, count=5, queries=5, seed=17, seconds=0.25)
    generate(output=second, count=5, queries=5, seed=17, seconds=0.25)
    assert (first / "audios.csv").read_bytes() == (second / "audios.csv").read_bytes()
    assert (first / "audios" / "audio_000002.wav").read_bytes() == (
        second / "audios" / "audio_000002.wav").read_bytes()


def test_audio_waveforms_are_not_clipping_or_silent():
    for family in FAMILIES:
        samples, freq = make_waveform(family, seed=123, seconds=0.3)
        assert samples.dtype == np.dtype("int16")
        assert 0 < np.max(np.abs(samples.astype(np.int32))) < 32767
        assert 200 < freq < 850
        assert len(samples) == round(0.3 * RATE)


def test_audio_rejects_corrupted_file(tmp_path):
    out = tmp_path / "x"
    generate(output=out, count=5, queries=5, seconds=0.25)
    file = out / "audios" / "audio_000001.wav"
    file.write_bytes(file.read_bytes()[:-40])
    with pytest.raises(ValueError, match="missing or corrupt"):
        verify(out)


def test_audio_refuses_existing_directory(tmp_path):
    out = tmp_path / "existing"
    out.mkdir()
    with pytest.raises(FileExistsError):
        generate(output=out, count=5, queries=5)
