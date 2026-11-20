"""Part 4 multimedia index experiment: IVF versus HNSW versus exact.

Uses the PROJECT'S actual vector.ivf.IVFIndex and vector.hnsw.HNSWIndex.
For images: --mode image --indexed <productos_indexados.csv> [--labels <etiquetas.csv>]
For audio: --mode audio --corpus <audios.csv> --queries <consultas.csv>
           --audio-dir <audios/> --query-dir <consultas/>
The audio experiment trains the same BoAW/TF-IDF vocabulary as the engine,
using its MFCC extractor. It uses independent audio queries (not catalog rows).
Image queries default to leave-one-out catalog images; provide --query-csv and
--query-dir with --model-root to evaluate independent query images.
Results are a SYNTHETIC retrieval experiment, not shopping Precision@10.
No additional claims about SQL query plans are made.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
import tracemalloc
from pathlib import Path

import numpy as np


def read_csv(path: Path) -> list[dict]:
    with Path(path).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def norm_rows(v: np.ndarray) -> np.ndarray:
    v=np.asarray(v,dtype=np.float64)
    if v.ndim!=2 or len(v)==0 or not np.isfinite(v).all(): raise ValueError('invalid matrix')
    size=np.linalg.norm(v,axis=1,keepdims=True)
    if (size<1e-12).any(): raise ValueError('zero-norm vector')
    return v/size


def exact_topk(ids, vectors:np.ndarray, q:np.ndarray, k:int, *, exclude=None, metric='cosine') -> list[int]:
    if metric=='cosine':
        score=norm_rows(vectors) @ (q / np.linalg.norm(q))
    elif metric=='euclidean':
        score=-np.linalg.norm(vectors-q[None,:],axis=1)
    else: raise ValueError('metric unsupported')
    order=sorted(range(len(ids)),key=lambda i:(-float(score[i]),str(ids[i])))
    return [ids[i] for i in order if ids[i]!=exclude][:k]


def metric_row(pred:list, ground:list, relevant:set, k:int) -> dict:
    if k<1: raise ValueError('k must be positive')
    hits=len(set(pred[:k]) & relevant)
    return {'retrieval_recall_at_k':len(set(pred[:k])&set(ground[:k]))/min(k,len(ground)) if ground else 0.0,
            'label_precision_at_k':hits/k,
            'label_hit_rate_at_k':float(hits>0)}


def load_image(indexed:Path, limit:int, labels:Path|None, query_csv:Path|None,
               query_dir:Path|None, model_root:Path|None, query_limit:int):
    rows=read_csv(indexed)
    if not rows or not {'id','embedding'}.issubset(rows[0]): raise ValueError('indexed csv with id, embedding needed')
    chosen=rows[:limit]
    ids=[int(x['id']) for x in chosen]
    vectors=np.asarray([json.loads(x['embedding']) for x in chosen],dtype=np.float64)
    meta={int(x['id']):x for x in read_csv(labels)} if labels else {}
    def tag(r):
        if 'figura' in r and 'color' in r: return (r['figura'],r['color'])
        return (r.get('categoria',''),)
    catalog_tags={int(x['id']):tag(meta.get(int(x['id']),x)) for x in chosen}
    if query_csv:
        if query_dir is None or model_root is None:
            raise ValueError('independent image queries need --query-dir and --model-root')
        from vector.extract_features import ExtractFeatures
        queries=[]
        for r in read_csv(query_csv)[:query_limit]:
            p=query_dir/Path(r['imagen']).name
            v=np.asarray(ExtractFeatures.extract(p,kind='image',model_root=model_root).values,dtype=float)
            queries.append((str(r['id']),v,tuple(r[x] for x in ('figura','color'))))
    else:
        # Self excluded, so this tests catalog-to-catalog retrieval, NOT query-image recognition.
        queries=[(str(x),vectors[j],catalog_tags[x]) for j,x in enumerate(ids[:query_limit])]
    return ids,vectors,catalog_tags,queries,'independent' if query_csv else 'leave-one-out gallery'


def load_audio(corpus:Path,queries:Path,audio_dir:Path,query_dir:Path,limit:int,query_limit:int,words:int):
    from vector.extract_features import ExtractFeatures
    from vector.bow import train_model
    original=read_csv(corpus)[:limit]
    probes=read_csv(queries)[:query_limit]
    if not original or not probes: raise ValueError('empty audio dataset')
    def wav_rows(rows,folder):
        return [ExtractFeatures.local_descriptors(folder/Path(r['archivo']).name,kind='audio') for r in rows]
    audio=wav_rows(original,audio_dir)
    queries_mfcc=wav_rows(probes,query_dir)
    if any(len(a)==0 for a in audio+queries_mfcc): raise ValueError('silent/unreadable audio cannot be encoded')
    # Vocab from catalog data ONLY. Query MFCCs do not fit any model.
    model=train_model('audio',audio,max(2,words),seed=2026)
    mat=np.asarray([model.encode(x) for x in audio],dtype=float)
    ids=[int(r['id']) for r in original]
    tags={int(r['id']):(r['familia'],) for r in original}
    query_data=[(str(r['id']),np.asarray(model.encode(x),dtype=float),(r['familia'],)) for r,x in zip(probes,queries_mfcc)]
    return ids,mat,tags,query_data,'independent synthetic audio queries'


def evaluate(ids:list[int],vectors:np.ndarray,labels:dict,queries:list[tuple], *,
             k:int=10,n_lists:int=16,n_probe:int=4,m:int=8,ef_search:int=40,
             metric:str='cosine', exclude_self:bool=False) -> dict:
    from vector.ivf import IVFIndex
    from vector.hnsw import HNSWIndex
    if not (len(ids)>=k+1 and len(set(ids))==len(ids)):
        raise ValueError('need >=k+1 unique gallery ids')
    vectors=norm_rows(vectors)
    if any(len(q)!=vectors.shape[1] or not np.isfinite(q).all() or np.linalg.norm(q)==0 for _,q,_ in queries):
        raise ValueError('bad query embedding')
    n_lists=min(n_lists,len(ids))
    entries=[(pid,tuple(map(float,v))) for pid,v in zip(ids,vectors)]
    records=[]
    resources={}
    for method in ('exact','IVF','HNSW'):
        t0=time.perf_counter();tracemalloc.start()
        try:
            if method=='IVF':
                idx=IVFIndex(n_lists=n_lists,n_probe=n_probe,metric_name=metric,random_seed=2026)
                idx.build(entries)
            elif method=='HNSW':
                idx=HNSWIndex(M=m,ef_construction=50,ef_search=ef_search,metric_name=metric,random_seed=2026)
                for pid,v in entries: idx.insert(pid,v)
            else: idx=None
            build_s=time.perf_counter()-t0
            _,peak=tracemalloc.get_traced_memory()
        finally:tracemalloc.stop()
        timings=[];obs=[];details=[]
        for qid,q,tag in queries:
            q=np.asarray(q,dtype=np.float64);q=q/np.linalg.norm(q)
            exclude=int(qid) if exclude_self else None
            baseline=exact_topk(ids,vectors,q,k,exclude=exclude,metric=metric)
            t=time.perf_counter()
            if method=='exact':hits=baseline
            else:
                # Ask k+1 when source is part of the gallery; avoids self-ranking inflation.
                found=idx.knn(q,k=k+1 if exclude is not None else k)
                hits=[int(x[0]) for x in found if x[0]!=exclude][:k]
            timings.append((time.perf_counter()-t)*1000)
            relevant={pid for pid in ids if pid!=exclude and labels[pid]==tag}
            value=metric_row(hits,baseline,relevant,k)
            obs.append(value)
            details.append({'query':qid,'method':method,'matches':" ".join(map(str,hits)),
                            'label_relevant_count':len(relevant),**value})
        resources[method]={
            'build_seconds':round(build_s,4),'peak_allocated_bytes':int(peak),
            'queries':len(queries),'mean_query_ms':round(statistics.mean(timings),4),
            'p95_query_ms':round(sorted(timings)[min(len(timings)-1,math.ceil(.95*len(timings))-1)],4),
            **{key:round(statistics.mean(v[key] for v in obs),6) for key in obs[0]},
            'index_type':method}
        records.extend(details)
    return {'scope':'project IVFIndex/HNSWIndex classes, exact numpy reference; in-process not SQL timing',
            'metric':metric,'gallery_size':len(ids),'k':k,'methods':resources,'detail':records}


def write_result(output:Path,result:dict):
    output.mkdir(parents=True,exist_ok=True)
    copy={k:v for k,v in result.items() if k!='detail'}
    (output/'p4_media_indices.json').write_text(json.dumps(copy,indent=2,ensure_ascii=False)+'\n',encoding='utf8')
    rows=result['detail']
    with (output/'p4_media_queries.csv').open('w',newline='',encoding='utf8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(json.dumps(copy,indent=2,ensure_ascii=False))
    return copy


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__.splitlines()[0]);p.add_argument('--mode',choices=['image','audio'],required=True)
    p.add_argument('--indexed',type=Path);p.add_argument('--labels',type=Path)
    p.add_argument('--query-csv',type=Path);p.add_argument('--query-dir',type=Path);p.add_argument('--model-root',type=Path)
    p.add_argument('--corpus',type=Path);p.add_argument('--queries',type=Path);p.add_argument('--audio-dir',type=Path)
    p.add_argument('--output',type=Path,default=Path('benchmarks/results/parte4'))
    p.add_argument('--limit',type=int,default=300);p.add_argument('--query-limit',type=int,default=30)
    p.add_argument('--k',type=int,default=10);p.add_argument('--n-lists',type=int,default=16)
    p.add_argument('--n-probe',type=int,default=4);p.add_argument('--words',type=int,default=24)
    p.add_argument('--metric',choices=['cosine','euclidean'],default='cosine')
    a=p.parse_args(argv)
    if a.limit<1 or a.query_limit<1: p.error('positive limits required')
    if a.mode=='image':
        if not a.indexed: p.error('image needs --indexed')
        ids,mat,labels,qs,scope=load_image(a.indexed,a.limit,a.labels,a.query_csv,a.query_dir,a.model_root,a.query_limit)
    else:
        if not (a.corpus and a.queries and a.audio_dir and a.query_dir):p.error('audio needs --corpus, --queries, --audio-dir and --query-dir')
        ids,mat,labels,qs,scope=load_audio(a.corpus,a.queries,a.audio_dir,a.query_dir,a.limit,a.query_limit,a.words)
    result=evaluate(ids,mat,labels,qs,k=a.k,n_lists=a.n_lists,n_probe=a.n_probe,metric=a.metric,exclude_self=(a.mode=='image' and a.query_csv is None))
    result['query_source']=scope
    write_result(a.output,result)


if __name__=='__main__':main()
