"""Song-recognition API: one-second MFCC, silence awareness, SQL IVF, playback.

Loaded lazily so no music dataset is needed to start the normal BD2 application.
Never changes the existing /api/media/extract or /api/query behavior.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import numpy as np
from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from audio_recognition.temporal import (AudioError, decode_audio, match_audio,
                                        query_candidates)

router = APIRouter(prefix="/api/audio", tags=["Audio 20-second recognition"])


def engine():
    from backend.api import engine as current_engine
    return current_engine


@lru_cache(maxsize=4)
def _load_assets(root: str, stamp: int):
    path=Path(root)
    with (path / "catalog.csv").open(encoding="utf-8",newline="") as stream:
        catalog={int(r["id"]):r for r in csv.DictReader(stream)}
    with np.load(path / "audio_index.npz",allow_pickle=False) as idx:
        values={name:idx[name].copy() for name in ("mean", "std", "embedding", "track_id", "segundo")}
    return catalog, values


def assets():
    root=Path(engine().data_dir)/"music20"
    path=root/"audio_index.npz"
    if not path.is_file() or not (root/"catalog.csv").is_file():
        raise HTTPException(503,"Music dataset not installed; run tools.import_music20 first")
    try:
        return _load_assets(str(root.resolve()),path.stat().st_mtime_ns)
    except (OSError,ValueError,KeyError) as exc:
        raise HTTPException(503,f"Music index invalid: {exc}") from exc


@router.get("/health")
def audio_health():
    installed=(Path(engine().data_dir)/"music20"/"audio_index.npz").is_file()
    indexed=engine().catalog.has_table("audio_segmentos")
    return {"installed":installed,"sql_ivf_ready": indexed,
            "note":"uses SQL IVF by default; offline exact cosine available for comparison"}


@router.post("/search")
async def audio_search(file:UploadFile=File(...),mode:str=Query("sql",pattern="^(sql|exact)$"),
                       k:int=Query(5,ge=1,le=10), candidates:int=Query(40,ge=10,le=100)):
    content=await file.read(40_000_001)
    if len(content)>40_000_000:
        raise HTTPException(413,"audio upload larger than 40 MB")
    catalog,values=assets()
    try:
        decoded=decode_audio(content,file.filename or "query.wav",max_seconds=25)
        if mode=="sql":
            current=engine()
            if not current.catalog.has_table("audio_segmentos"):
                raise HTTPException(503,"audio_segmentos SQL table missing; run tools.import_music20")

            def provider(queries:np.ndarray):
                groups=[]
                for vector in queries:
                    literal="["+",".join(f"{float(x):.6f}" for x in vector)+"]"
                    sql=("SELECT track_id, segundo, SIMILARITY_SCORE() AS score FROM audio_segmentos "
                         f"WHERE SIMILAR_TO({literal}, k={candidates}) USING IVF WITH METRIC=cosine")
                    result=current.run(sql)
                    if not result.success:
                        raise AudioError(f"SQL IVF retrieval failed: {result.error}")
                    groups.append([(int(r["track_id"]),int(r["segundo"]),float(r["score"]))
                                   for r in result.rows])
                return groups
        else:
            def provider(queries:np.ndarray):
                return query_candidates(values["embedding"],values["track_id"],
                                        values["segundo"],queries,k=candidates)
        results=match_audio(decoded,mean=values["mean"],std=values["std"],
                            candidate_provider=provider,top_k=k,min_similarity=.60)
    except AudioError as exc:
        raise HTTPException(422,str(exc)) from exc
    enriched=[]
    for found in results["matches"]:
        metadata=catalog.get(found["track_id"])
        if metadata is None:
            continue
        filename=metadata["audio"]
        if filename!=Path(filename).name:
            continue
        enriched.append({**found,"title":metadata["title"],"artist":metadata["artist"],
                         "genre":metadata["genre"],"source_page":metadata["source_page"],
                         "license_url":metadata["license_url"],"audio_url":f"/api/media/{quote(filename)}",
                         "clip_start_s":float(metadata["source_start_s"])})
    return {**results,"matches":enriched,"search_method":
            "sql_ivf_40d_mfcc_1s" if mode=="sql" else "exact_cosine_40d_mfcc_1s",
            "disclaimer":"Similarity of acoustic MFCCs, not a copyright or song-identity guarantee"}
