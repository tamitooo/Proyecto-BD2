"""Real MFCC extraction tests (#103, #80)."""

import io

import numpy as np
import pytest

pytest.importorskip("librosa")
sf = pytest.importorskip("soundfile")

from multimedia.mfcc import MFCCFeatureExtractor, extract_mfcc_descriptors


@pytest.fixture
def tone():
    rate = 16_000
    t = np.arange(rate // 3, dtype=np.float32) / rate
    return np.sin(2 * np.pi * 440 * t).astype(np.float32), rate


def test_dimensions_finiteness_and_determinism(tone):
    y, sr = tone
    extractor = MFCCFeatureExtractor(n_mfcc=13, n_fft=512, hop_length=128)
    first = extractor.extract(y, sample_rate=sr)
    second = extractor.extract(y, sample_rate=sr)
    assert first.ndim == 2 and first.shape[1] == 13 and len(first) > 0
    assert first.dtype == np.float32 and first.flags.c_contiguous
    assert np.isfinite(first).all()
    np.testing.assert_array_equal(first, second)


def test_wav_file_bytes_and_raw_array_are_consistent(tmp_path, tone):
    y, sr = tone
    path = tmp_path / "música ñ.wav"
    sf.write(path, y, sr, subtype="FLOAT")
    encoded = io.BytesIO()
    sf.write(encoded, y, sr, format="WAV", subtype="FLOAT")
    extractor = MFCCFeatureExtractor(n_fft=512, hop_length=128)
    expected = extractor.extract(y, sample_rate=sr)
    np.testing.assert_allclose(expected, extractor.extract(path), rtol=1e-4, atol=1e-4)
    np.testing.assert_allclose(expected, extractor.extract(encoded.getvalue()), rtol=1e-4, atol=1e-4)
    assert extract_mfcc_descriptors(path, n_fft=512).shape[1] == 13


def test_stereo_downmix_and_integer_pcm(tone):
    y, sr = tone
    stereo = np.column_stack((y, y))
    extractor = MFCCFeatureExtractor(n_fft=512)
    np.testing.assert_allclose(
        extractor.extract(y, sample_rate=sr),
        extractor.extract(stereo, sample_rate=sr), atol=1e-4,
    )
    pcm = np.round(y * 32767).astype(np.int16)
    assert extractor.extract(pcm, sample_rate=sr).shape[1] == 13


def test_empty_audio_and_silence(tone):
    extractor = MFCCFeatureExtractor(n_fft=512)
    assert extractor.extract(np.empty(0, dtype=np.float32), sample_rate=16000).shape == (0, 13)
    zeros = extractor.extract(np.zeros(1024, dtype=np.float32), sample_rate=16000)
    assert zeros.shape[1] == 13 and np.isfinite(zeros).all()


def test_invalid_waveforms_and_missing_sample_rate():
    extractor = MFCCFeatureExtractor()
    with pytest.raises(ValueError, match="sample_rate"):
        extractor.extract(np.ones(100, dtype=np.float32))
    with pytest.raises(ValueError):
        extractor.extract(np.array([np.nan], dtype=np.float32), sample_rate=16000)
    with pytest.raises(ValueError):
        extractor.extract(np.ones((10, 4), dtype=np.float32), sample_rate=16000)
    with pytest.raises(TypeError):
        extractor.extract(123)


@pytest.mark.parametrize("kwargs", [
    {"n_mfcc": 0}, {"n_mfcc": 25, "n_mels": 20},
    {"sample_rate": 0}, {"n_fft": 1}, {"hop_length": -2},
])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        MFCCFeatureExtractor(**kwargs)
