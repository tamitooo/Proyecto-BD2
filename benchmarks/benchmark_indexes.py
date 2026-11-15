"""Comparación B+ clustered, B+ unclustered y Hash Extendible."""
from __future__ import annotations
import argparse, random, statistics, time
from pathlib import Path
from benchmarks.common import deep_size,write_rows
from indexes.clustered_bplus import ClusteredBPlusIndex
from indexes.unclustered_bplus import UnclusteredBPlusIndex
from indexes.extendible_hash import ExtendibleHash


def ns(fn):t=time.perf_counter_ns();x=fn();return time.perf_counter_ns()-t,x
def mean_us(xs):return statistics.fmean(xs)/1000 if xs else None

def linear_scan_baseline(recs,queries,rng):
 """Línea base sin índice: cada búsqueda recorre todos los registros."""
 n=len(recs);exact=[];hits=0;ranges=[];items=0;width=max(2,n//300)
 for _ in range(queries):
  k=rng.randrange(max(1,n//3));dt,v=ns(lambda k=k:[r for r in recs if r['value']==k]);exact.append(dt);hits+=len(v)
 for _ in range(queries):
  lo=rng.randrange(max(1,n//3));dt,v=ns(lambda lo=lo:[r for r in recs if lo<=r['value']<=lo+width]);ranges.append(dt);items+=len(v)
 base={'dataset_size':n,'index_type':'linear_scan','build_ms':0.0,'size_bytes':0,'supported':True}
 return [base|{'metric':'exact_lookup','avg_us':mean_us(exact),'operations':queries,'result_items':hits},
         base|{'metric':'range_search','avg_us':mean_us(ranges),'operations':queries,'result_items':items}]

def run(sizes=(1000,10000,100000),queries=100,mutations=50,seed=42):
 rng=random.Random(seed);out=[]
 for n in sizes:
  recs=[{'id':i,'value':i//3} for i in range(n)]
  out+=linear_scan_baseline(recs,queries,random.Random(seed))
  specs=[
   ('bplus_clustered',lambda:ClusteredBPlusIndex('value',order=32)),
   ('bplus_unclustered',lambda:UnclusteredBPlusIndex('value',order=32)),
   ('extendible_hash',lambda:ExtendibleHash(bucket_capacity=64,hash_func=lambda x:x)),
  ]
  for name,factory in specs:
   idx=factory();start=time.perf_counter_ns()
   for rid,row in enumerate(recs):
    if name=='extendible_hash':idx.insert(row['value'],rid)
    else:idx.insert(row,rid)
   build=(time.perf_counter_ns()-start)/1e6
   if hasattr(idx,'validate'):assert idx.validate()
   memory=deep_size(idx)
   exact=[];hits=0
   for _ in range(queries):
    k=rng.randrange(max(1,n//3));dt,v=ns(lambda k=k:idx.search(k));exact.append(dt);hits+=len(v)
   out.append({'dataset_size':n,'index_type':name,'metric':'build','build_ms':build,'avg_us':build*1000/n,'operations':n,'result_items':n,'size_bytes':memory,'supported':True})
   out.append({'dataset_size':n,'index_type':name,'metric':'exact_lookup','build_ms':build,'avg_us':mean_us(exact),'operations':queries,'result_items':hits,'size_bytes':memory,'supported':True})
   if name!='extendible_hash':
    ranges=[];items=0
    width=max(2,n//300)
    for _ in range(queries):
      low=rng.randrange(max(1,n//3));high=low+width;dt,v=ns(lambda lo=low,hi=high:idx.range_search(lo,hi));ranges.append(dt);items+=len(v)
    ordered_ns,v=ns(lambda:idx.scan())
    out.append({'dataset_size':n,'index_type':name,'metric':'range_search','build_ms':build,'avg_us':mean_us(ranges),'operations':queries,'result_items':items,'size_bytes':memory,'supported':True})
    out.append({'dataset_size':n,'index_type':name,'metric':'ordered_scan','build_ms':build,'avg_us':ordered_ns/1000,'operations':1,'result_items':len(v),'size_bytes':memory,'supported':True})
   else:
    out.append({'dataset_size':n,'index_type':name,'metric':'range_search','build_ms':build,'avg_us':None,'operations':0,'result_items':None,'size_bytes':memory,'supported':False,'notes':'Hash no preserva orden ni soporta rango.'})
    out.append({'dataset_size':n,'index_type':name,'metric':'ordered_scan','build_ms':build,'avg_us':None,'operations':0,'result_items':None,'size_bytes':memory,'supported':False,'notes':'Hash no preserva orden.'})
   muts=[]
   for j in range(mutations):
      row={'id':n+j,'value':n+j};t=time.perf_counter_ns()
      if name=='extendible_hash':idx.insert(row['value'],n+j)
      else:idx.insert(row,n+j)
      muts.append(time.perf_counter_ns()-t)
   out.append({'dataset_size':n,'index_type':name,'metric':'insert_mutation','build_ms':build,'avg_us':mean_us(muts),'operations':mutations,'result_items':mutations,'size_bytes':deep_size(idx),'supported':True})
 return out

def main():
 p=argparse.ArgumentParser();p.add_argument('--sizes',nargs='+',type=int,default=[1000,10000,100000]);p.add_argument('--queries',type=int,default=100);p.add_argument('--mutations',type=int,default=50);p.add_argument('--output-dir',default='benchmarks/results');a=p.parse_args();rows=run(a.sizes,a.queries,a.mutations);out=Path(a.output_dir);write_rows(rows,out/'index_benchmark.csv',out/'index_benchmark.json',{'sizes':a.sizes,'queries':a.queries,'mutations':a.mutations});[print(r) for r in rows]
if __name__=='__main__':main()
