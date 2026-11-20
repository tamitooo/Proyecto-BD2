"""Build -> manifest -> temporal IVF-style queries -> API payload regression.

WAV audio is original, locally synthesized musical motifs solely for tests.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from audio_recognition.temporal import RATE, wav_bytes, read_wav_bytes
from tools.build_music20 import build, verify
from tests.test_music20_temporal import melody


def fixture_dataset(tmp_path):
    source = tmp_path / 'licensed'
    source.mkdir()
    rows = []
    for index in range(1, 4):
        # 6s silent intro; clip picker should select music from t=6 through 26.
        signal = np.concatenate((np.zeros(RATE * 6), melody(index, 20)))
        name = f'track{index}.wav'
        (source / name).write_bytes(wav_bytes(signal))
        rows.append({'id':index,'title':f'Original motif {index}', 'artist':'Self-composed demo',
                     'genre':['jazz','rock','folk'][index-1], 'source_url':name,
                     'license_url':'local-user-authorized','source_page':'','source_id':str(index)})
    manifest = source / 'manifest.csv'
    with manifest.open('w',newline='',encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader();w.writerows(rows)
    dest = tmp_path / 'music20'
    return manifest, dest


def test_build_verify_resume_preserves_source_offset(tmp_path):
    manifest, dest = fixture_dataset(tmp_path)
    result = build(manifest, dest)
    assert result['accepted'] == 3
    assert result['rejected'] == 0
    assert result['segments'] == 60
    summary = verify(dest)
    assert summary['tracks'] == 3 and summary['all_sha256_valid']
    with (dest/'catalog.csv').open(newline='', encoding='utf8') as f:
        entries=list(csv.DictReader(f))
    assert {int(x['source_start_s']) for x in entries} == {6}
    assert all(len(read_wav_bytes((dest/'media'/x['audio']).read_bytes())) == 20*RATE for x in entries)
    # Rerun using the local cache: must retain source offset and file checksum.
    assert build(manifest,dest)['accepted']==3
    with (dest/'catalog.csv').open(newline='',encoding='utf8') as f:
        again=list(csv.DictReader(f))
    assert {int(x['source_start_s']) for x in again} == {6}
    assert [x['sha256'] for x in again]==[x['sha256'] for x in entries]


def test_exact_and_sql_search_routes(tmp_path,monkeypatch):
    manifest, dest = fixture_dataset(tmp_path)
    build(manifest,dest)
    import backend.audio_routes as routes

    class Engine:
        data_dir=tmp_path
        calls=0
        class catalog:
            @staticmethod
            def has_table(name): return name=='audio_segmentos'
        def run(self,sql):
            self.calls+=1
            with np.load(dest/'audio_index.npz',allow_pickle=False) as idx:
                db=idx['embedding'];track=idx['track_id'];seconds=idx['segundo']
            m=re.search(r'SIMILAR_TO\(\[([^\]]+)\]',sql)
            assert m,sql
            vector=np.array([float(n) for n in m.group(1).split(',')])
            similarities=db@vector
            pick=np.argsort(-similarities)[:40]
            class Result:
                success=True
                error=None
            result=Result()
            result.rows=[{'track_id':int(track[j]),'segundo':int(seconds[j]),
                          'score':float(similarities[j])} for j in pick]
            return result
    fake=Engine()
    monkeypatch.setattr(routes,'engine',lambda: fake)
    routes._load_assets.cache_clear()
    app=FastAPI()
    app.include_router(routes.router)
    client=TestClient(app)
    query=(dest/'media'/'music20_000002.wav').read_bytes()
    result=client.post('/api/audio/search?mode=exact&k=3',
                       files={'file':('clip.wav',query,'audio/wav')})
    assert result.status_code==200,result.text
    data=result.json()
    assert data['status']=='ok'
    assert data['matches'][0]['track_id']==2
    assert data['matches'][0]['audio_url'].endswith('music20_000002.wav')
    assert data['matches'][0]['reference_start_s']==0
    assert data['matches'][0]['clip_start_s']==6

    live=client.post('/api/audio/search?mode=sql&k=3',
                     files={'file':('clip.wav',query,'audio/wav')})
    assert live.status_code==200,live.text
    data=live.json()
    assert fake.calls>0
    assert data['matches'][0]['track_id']==2
    assert data['search_method'].startswith('sql_ivf')

    silence=client.post('/api/audio/search?mode=exact',
                        files={'file':('quiet.wav',wav_bytes(np.zeros(12*RATE)),'audio/wav')})
    assert silence.status_code==200,silence.text
    assert silence.json()['status']=='silent_or_too_short'
    assert silence.json()['matches']==[]


def test_offline_recognition_benchmark_does_not_fabricate_metrics(tmp_path):
    from tools.evaluate_music20 import evaluate
    manifest, dest=fixture_dataset(tmp_path)
    build(manifest, dest)
    report=evaluate(dest,limit=3)
    assert report['queries']==3
    assert 0 <= report['top1_accuracy'] <= 1
    assert 0 <= report['recall_at_5'] <= 1
    assert (dest/'evaluation'/'summary.json').is_file()
    assert (dest/'evaluation'/'results.csv').is_file()


def test_verify_strict_genre_quotas(tmp_path):
    from audio_recognition.temporal import AudioError
    import pytest
    manifest,dest=fixture_dataset(tmp_path)
    build(manifest,dest)
    with pytest.raises(AudioError, match='does not meet'):
        verify(dest,minimum_per_genre=100)
