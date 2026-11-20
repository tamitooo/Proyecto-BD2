"""Manifest filtering, license provenance, and local path safety."""
from __future__ import annotations

from pathlib import Path
import pytest

from audio_recognition.temporal import AudioError
from tools.discover_licensed_music import GENRES, permitted_track, discover
from tools.build_music20 import fetch_source, read_manifest


def track(identifier=7, genre='rock', license_url='https://creativecommons.org/licenses/by/4.0/'):
    return {'id':str(identifier), 'name':f'Piece {identifier}', 'artist_name':'Artist',
            'duration':100, 'musicinfo':{'tags':{'genres':[genre]}},
            'license_ccurl':license_url,'audiodownload_allowed':True,
            'audiodownload':'https://prod-1.storage.jamendo.com/download/track/7/mp32/',
            'shareurl':'https://www.jamendo.com/track/7'}


def test_accepts_jamendo_storage_license_by_only():
    assert permitted_track(track())
    assert permitted_track(track(license_url='https://creativecommons.org/publicdomain/zero/1.0/'))
    assert not permitted_track(track(license_url='http://creativecommons.org/licenses/by-nc/4.0/'))
    assert not permitted_track(track() | {'audiodownload_allowed':False})
    assert not permitted_track(track() | {'audiodownload':'https://untrusted.example/record.mp3'})


def test_manifest_discovery_uses_real_tag_and_unique_ids():
    def pages(client_id, genre, offset, limit):
        return [track(100,genre), track(101,genre),track(102,'not-the-requested-tag')]
    with pytest.raises(RuntimeError,match='eligible'):
        discover('demo', per_genre=3, page_fetcher=pages,pause=0)
    assert len(GENRES) == 10


def test_local_file_restricted_to_manifest_directory(tmp_path):
    outer = tmp_path/'outside.wav'
    outer.write_bytes(b'private')
    inner=tmp_path/'manifest'
    inner.mkdir()
    with pytest.raises(AudioError,match='escapes'):
        fetch_source({'source_url':'../outside.wav'},inner)
    sample=inner/'safe.wav'
    sample.write_bytes(b'permitted local bytes')
    assert fetch_source({'source_url':'safe.wav'},inner)==b'permitted local bytes'
