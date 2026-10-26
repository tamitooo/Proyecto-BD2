"""Benchmark requerido: Heap File vs Archivo Secuencial Paginado.

Para cada N mide una inserción representativa sobre una tabla ya poblada, una
búsqueda por PK, espacio en disco y el costo explícito de reorganización del
archivo secuencial. La construcción base se hace con ``replace_all`` para que
el experimento llegue a N=100 000 sin confundir tiempo de setup con la métrica
de inserción individual que pide el enunciado.
"""
from __future__ import annotations
import argparse, os, random, statistics, tempfile, time
from pathlib import Path
from benchmarks.common import write_rows
from storage.heap_file import HeapFile
from storage.record import Schema
from storage.sequential_file import SequentialFile

SCHEMA=Schema([('id','INT'),('value','INT'),('name','VARCHAR(24)')],'id')


def records(n):return [{'id':i,'value':i%997,'name':f'r{i}'} for i in range(n)]
def avg_us(samples):return statistics.fmean(samples)/1000 if samples else None

def timed_ns(fn,repeats=1):
    xs=[];last=None
    for _ in range(repeats):
        t=time.perf_counter_ns();last=fn();xs.append(time.perf_counter_ns()-t)
    return xs,last

def run(sizes=(1000,10000,100000),search_queries=100,insert_queries=25,seed=42):
    rng=random.Random(seed);out=[]
    with tempfile.TemporaryDirectory(prefix='bd2-storage-bench-') as td:
      for n in sizes:
        base=records(n)
        # HEAP setup (layout físico paginado real)
        hp=HeapFile(os.path.join(td,f'h{n}.dat'),SCHEMA); hp.replace_all(base)
        keys=[rng.randrange(n) for _ in range(min(search_queries,n))]
        search=[]
        for key in keys:
            t=time.perf_counter_ns();found=next((r for _,r in hp.scan() if r['id']==key),None);search.append(time.perf_counter_ns()-t);assert found and found['id']==key
        # representative inserts: use IDs beyond N and preserve file state
        ins=[]
        for j in range(insert_queries):
            row={'id':n+1_000+j,'value':j,'name':f'new{j}'};t=time.perf_counter_ns();hp.insert(row);ins.append(time.perf_counter_ns()-t)
        out += [
          {'dataset_size':n,'storage':'heap','metric':'insert','avg_us':avg_us(ins),'operations':len(ins),'size_bytes':hp.espacio_utilizado_bytes(),'supported':True},
          {'dataset_size':n,'storage':'heap','metric':'search_pk','avg_us':avg_us(search),'operations':len(search),'size_bytes':hp.espacio_utilizado_bytes(),'supported':True},
          {'dataset_size':n,'storage':'heap','metric':'disk_space','avg_us':0.0,'operations':0,'size_bytes':hp.espacio_utilizado_bytes(),'supported':True},
          {'dataset_size':n,'storage':'heap','metric':'reorganize','avg_us':None,'operations':0,'size_bytes':hp.espacio_utilizado_bytes(),'supported':False,'notes':'Heap reutiliza free-list; no requiere reorganización periódica.'},
        ]
        # SEQUENTIAL setup
        sp=SequentialFile(os.path.join(td,f's{n}'),SCHEMA);sp.replace_all(base)
        search=[]
        for key in keys:
            t=time.perf_counter_ns();rid,row=sp.search(key);search.append(time.perf_counter_ns()-t);assert rid and row['id']==key
        ins=[]
        for j in range(insert_queries):
            row={'id':n+2_000+j,'value':j,'name':f'new{j}'};t=time.perf_counter_ns();sp.insert(row);ins.append(time.perf_counter_ns()-t)
        out += [
          {'dataset_size':n,'storage':'sequential','metric':'insert','avg_us':avg_us(ins),'operations':len(ins),'size_bytes':sp.espacio_utilizado_bytes(),'supported':True},
          {'dataset_size':n,'storage':'sequential','metric':'search_pk','avg_us':avg_us(search),'operations':len(search),'size_bytes':sp.espacio_utilizado_bytes(),'supported':True},
          {'dataset_size':n,'storage':'sequential','metric':'disk_space','avg_us':0.0,'operations':0,'size_bytes':sp.espacio_utilizado_bytes(),'supported':True},
        ]
        # Reorganization benchmark: preload main, append an unsorted overflow in
        # one batch, then time exactly the merge/sort/compaction operation.
        rp=SequentialFile(os.path.join(td,f'r{n}'),SCHEMA);rp.replace_all(base)
        overflow=max(1,int(n*0.31))
        with open(rp.aux_path,'ab') as f:
            for j in range(overflow):
                row={'id':n+overflow-j,'value':j,'name':f'o{j}'}
                f.write(SCHEMA.pack(row,flag=SCHEMA.FLAG_USED))
        t=time.perf_counter_ns();rp.reorganizar();reorg=time.perf_counter_ns()-t
        main_ids=[r['id'] for flag,r in rp._leer_todos(rp.main_path) if flag==SCHEMA.FLAG_USED]
        assert main_ids==sorted(main_ids) and os.path.getsize(rp.aux_path)==0
        out.append({'dataset_size':n,'storage':'sequential','metric':'reorganize','avg_us':reorg/1000,'operations':1,'size_bytes':rp.espacio_utilizado_bytes(),'supported':True,'notes':f'merge main + overflow ({overflow} filas) y compactación'})
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('--sizes',nargs='+',type=int,default=[1000,10000,100000]);p.add_argument('--search-queries',type=int,default=100);p.add_argument('--insert-queries',type=int,default=25);p.add_argument('--output-dir',default='benchmark_results');a=p.parse_args()
    rows=run(a.sizes,a.search_queries,a.insert_queries);out=Path(a.output_dir);write_rows(rows,out/'storage_benchmark.csv',out/'storage_benchmark.json',{'sizes':a.sizes,'search_queries':a.search_queries,'insert_queries':a.insert_queries})
    for r in rows:print(r)
if __name__=='__main__':main()
