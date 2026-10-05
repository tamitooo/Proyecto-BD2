from __future__ import annotations
import csv
from collections import defaultdict
from pathlib import Path
import matplotlib.pyplot as plt

ROOT=Path('benchmark_results');PLOTS=ROOT/'plots';PLOTS.mkdir(parents=True,exist_ok=True)

def load(name):
 p=ROOT/name
 if not p.exists():return []
 with p.open(encoding='utf-8') as f:return list(csv.DictReader(f))

def chart_storage():
 rows=[r for r in load('storage_benchmark.csv') if r['metric'] in {'insert','search_pk','reorganize'} and r.get('supported')=='True']
 if not rows:return
 for metric in ('insert','search_pk','reorganize'):
  data=[r for r in rows if r['metric']==metric]
  if not data:continue
  fig,ax=plt.subplots();
  for storage in sorted({r['storage'] for r in data}):
   part=sorted([r for r in data if r['storage']==storage],key=lambda r:int(r['dataset_size']))
   ax.plot([int(r['dataset_size']) for r in part],[float(r['avg_us']) for r in part],marker='o',label=storage)
  ax.set_xscale('log');ax.set_yscale('log');ax.set_xlabel('N');ax.set_ylabel('microsegundos');ax.set_title(metric);ax.legend();fig.tight_layout();fig.savefig(PLOTS/f'storage_{metric}.png',dpi=150);plt.close(fig)

def chart_indexes():
 rows=[r for r in load('index_benchmark.csv') if r.get('supported')=='True' and r['metric'] in {'exact_lookup','range_search','build'}]
 for metric in ('build','exact_lookup','range_search'):
  data=[r for r in rows if r['metric']==metric]
  if not data:continue
  fig,ax=plt.subplots()
  for typ in sorted({r['index_type'] for r in data}):
   part=sorted([r for r in data if r['index_type']==typ],key=lambda r:int(r['dataset_size']))
   y=[float(r['build_ms']) if metric=='build' else float(r['avg_us']) for r in part]
   ax.plot([int(r['dataset_size']) for r in part],y,marker='o',label=typ)
  ax.set_xscale('log');ax.set_yscale('log');ax.set_xlabel('N');ax.set_ylabel('ms' if metric=='build' else 'microsegundos');ax.set_title(metric);ax.legend();fig.tight_layout();fig.savefig(PLOTS/f'index_{metric}.png',dpi=150);plt.close(fig)

def chart_spatial():
 rows=[r for r in load('spatial_benchmark.csv') if r.get('supported')=='True' and r['query'] in {'range','knn'}]
 for query in ('range','knn'):
  params=sorted({r['parameter'] for r in rows if r['query']==query})
  for param in params:
   data=[r for r in rows if r['query']==query and r['parameter']==param]
   fig,ax=plt.subplots()
   for tech in sorted({r['technique'] for r in data}):
    part=sorted([r for r in data if r['technique']==tech],key=lambda r:int(r['dataset_size']))
    ax.plot([int(r['dataset_size']) for r in part],[float(r['avg_query_ms']) for r in part],marker='o',label=tech)
   ax.set_xscale('log');ax.set_yscale('log');ax.set_xlabel('N');ax.set_ylabel('ms / consulta');ax.set_title(f'{query} {param}');ax.legend();fig.tight_layout();safe=param.replace(' ','_').replace('=','');fig.savefig(PLOTS/f'spatial_{query}_{safe}.png',dpi=150);plt.close(fig)

if __name__=='__main__':chart_storage();chart_indexes();chart_spatial();print('plots:',PLOTS)
