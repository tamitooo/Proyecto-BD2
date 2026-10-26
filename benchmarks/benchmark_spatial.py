"""Benchmark Parte 2: secuencial vs R-Tree propio vs PostgreSQL GiST/PostGIS.

Defaults are the exact matrix requested by the project: N=1K/10K/100K,
100 queries, radii 1/5/10 km and k=10/50/100. PostgreSQL is optional at runtime;
when ``--pg-dsn`` is supplied the script creates a temporary PostGIS table and
GiST index and measures the same query workload.
"""
from __future__ import annotations
import argparse, heapq, math, os, random, statistics, time, uuid
import numpy as np
from pathlib import Path
from benchmarks.common import deep_size,write_rows
from spatial.geo import haversine
from spatial.index import SpatialIndex

CENTER=(-12.0464,-77.0428);RADII=[1000,5000,10000];KS=[10,50,100]

def generate(n,seed=42):
 rng=random.Random(seed+n);return [(CENTER[0]+rng.uniform(-.35,.35),CENTER[1]+rng.uniform(-.35,.35)) for _ in range(n)]
def queries(count,seed=99):
 rng=random.Random(seed);return [(CENTER[0]+rng.uniform(-.15,.15),CENTER[1]+rng.uniform(-.15,.15)) for _ in range(count)]
def avg_ms(xs):return statistics.fmean(xs) if xs else None

def _np_distances(arr, q):
 lat=np.radians(arr[:,0]);lon=np.radians(arr[:,1]);lat0=math.radians(q[0]);lon0=math.radians(q[1]);dlat=lat-lat0;dlon=lon-lon0
 a=np.sin(dlat/2.0)**2+math.cos(lat0)*np.cos(lat)*np.sin(dlon/2.0)**2
 return 6371008.8*2*np.arctan2(np.sqrt(a),np.sqrt(np.maximum(0.0,1.0-a)))
def seq_range(arr,q,r):return int(np.count_nonzero(_np_distances(arr,q)<=r))
def seq_knn(arr,q,k):
 d=_np_distances(arr,q);kk=min(k,len(d));np.partition(d,kk-1)[:kk];return kk

def postgres_results(points,qs,n,dsn):
 try:import psycopg2
 except Exception as exc:return [{'dataset_size':n,'technique':'postgres_gist','query':'availability','parameter':'-','supported':False,'notes':f'psycopg2 no disponible: {exc}'}]
 name='bd2_spatial_'+uuid.uuid4().hex[:10];rows=[]
 try:
  conn=psycopg2.connect(dsn);conn.autocommit=True;cur=conn.cursor();cur.execute('CREATE EXTENSION IF NOT EXISTS postgis');cur.execute(f'CREATE TABLE {name}(id integer primary key, geom geometry(Point,4326))')
  start=time.perf_counter();cur.executemany(f'INSERT INTO {name}(id,geom) VALUES (%s,ST_SetSRID(ST_MakePoint(%s,%s),4326))',[(i,lon,lat) for i,(lat,lon) in enumerate(points)]);cur.execute(f'CREATE INDEX {name}_gist ON {name} USING GIST(geom)');build=(time.perf_counter()-start)*1000
  cur.execute(f"SELECT pg_total_relation_size('{name}'), pg_relation_size('{name}_gist')");table_size,index_size=cur.fetchone()
  for radius in RADII:
   ts=[];items=0
   for lat,lon in qs:
    t=time.perf_counter();cur.execute(f'SELECT count(*) FROM {name} WHERE ST_DWithin(geom::geography,ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,%s)',(lon,lat,radius));items+=cur.fetchone()[0];ts.append((time.perf_counter()-t)*1000)
   rows.append({'dataset_size':n,'technique':'postgres_gist','query':'range','parameter':f'{radius//1000} km','supported':True,'build_ms':build,'avg_query_ms':avg_ms(ts),'queries':len(qs),'result_items':items,'size_bytes':index_size,'table_size_bytes':table_size})
  for k in KS:
   ts=[];items=0
   for lat,lon in qs:
    t=time.perf_counter();cur.execute(f'SELECT id FROM {name} ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s,%s),4326) LIMIT %s',(lon,lat,k));items+=len(cur.fetchall());ts.append((time.perf_counter()-t)*1000)
   rows.append({'dataset_size':n,'technique':'postgres_gist','query':'knn','parameter':f'k={k}','supported':True,'build_ms':build,'avg_query_ms':avg_ms(ts),'queries':len(qs),'result_items':items,'size_bytes':index_size,'table_size_bytes':table_size})
  cur.execute(f'DROP TABLE {name}');cur.close();conn.close()
 except Exception as exc:
  rows=[{'dataset_size':n,'technique':'postgres_gist','query':'availability','parameter':'-','supported':False,'notes':str(exc)}]
 return rows

def run(sizes=(1000,10000,100000),query_count=100,seed=42,pg_dsn=''):
 out=[]
 for n in sizes:
  pts=generate(n,seed);arr=np.asarray(pts,dtype=np.float64);qs=queries(query_count,seed+n);seq_size=int(arr.nbytes)
  # Sequential build is zero: the dataset itself is the baseline structure.
  for radius in RADII:
   ts=[];items=0
   for q in qs:t=time.perf_counter();items+=seq_range(arr,q,radius);ts.append((time.perf_counter()-t)*1000)
   out.append({'dataset_size':n,'technique':'sequential','query':'range','parameter':f'{radius//1000} km','supported':True,'build_ms':0.0,'avg_query_ms':avg_ms(ts),'queries':query_count,'result_items':items,'size_bytes':seq_size})
  for k in KS:
   ts=[];items=0
   for q in qs:t=time.perf_counter();items+=seq_knn(arr,q,k);ts.append((time.perf_counter()-t)*1000)
   out.append({'dataset_size':n,'technique':'sequential','query':'knn','parameter':f'k={k}','supported':True,'build_ms':0.0,'avg_query_ms':avg_ms(ts),'queries':query_count,'result_items':items,'size_bytes':seq_size})
  idx=SpatialIndex('lat','lon',max_entries=16,metric='haversine');t=time.perf_counter();idx.bulk_load([({'lat':lat,'lon':lon},i) for i,(lat,lon) in enumerate(pts)]);build=(time.perf_counter()-t)*1000;assert idx.validate();isize=deep_size(idx)
  for radius in RADII:
   ts=[];items=0
   for q in qs:t=time.perf_counter();items+=len(idx.range_search(q,radius,metric='haversine'));ts.append((time.perf_counter()-t)*1000)
   out.append({'dataset_size':n,'technique':'rtree','query':'range','parameter':f'{radius//1000} km','supported':True,'build_ms':build,'avg_query_ms':avg_ms(ts),'queries':query_count,'result_items':items,'size_bytes':isize})
  for k in KS:
   ts=[];items=0
   for q in qs:t=time.perf_counter();items+=len(idx.knn(q,k,metric='haversine'));ts.append((time.perf_counter()-t)*1000)
   out.append({'dataset_size':n,'technique':'rtree','query':'knn','parameter':f'k={k}','supported':True,'build_ms':build,'avg_query_ms':avg_ms(ts),'queries':query_count,'result_items':items,'size_bytes':isize})
  if pg_dsn:out.extend(postgres_results(pts,qs,n,pg_dsn))
  else:out.append({'dataset_size':n,'technique':'postgres_gist','query':'availability','parameter':'-','supported':False,'notes':'Ejecuta con --pg-dsn para medir PostgreSQL/PostGIS GiST en este host.'})
 return out

def main():
 p=argparse.ArgumentParser();p.add_argument('--sizes',nargs='+',type=int,default=[1000,10000,100000]);p.add_argument('--queries',type=int,default=100);p.add_argument('--pg-dsn',default=os.environ.get('BD2_PG_DSN',''));p.add_argument('--output-dir',default='benchmark_results');a=p.parse_args();rows=run(a.sizes,a.queries,pg_dsn=a.pg_dsn);out=Path(a.output_dir);write_rows(rows,out/'spatial_benchmark.csv',out/'spatial_benchmark.json',{'sizes':a.sizes,'queries':a.queries,'radii_m':RADII,'k_values':KS,'postgres_enabled':bool(a.pg_dsn)});[print(r) for r in rows]
if __name__=='__main__':main()
