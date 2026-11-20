"""Offline and optional live DB acceptance checks for issues #127 and #129."""
from __future__ import annotations
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from tools.finish_127_129 import verify,read_catalog,PAIRS


def offline(dataset:Path,require_real=True):
    d=Path(dataset)
    report=verify(d)
    if require_real and not 2000 <= report['products'] <= 5000:
        raise ValueError('issue #127 needs 2,000-5,000 real products')
    products={int(r['id']):r for r in read_catalog(d/'productos.csv')}
    pairs=defaultdict(set)
    for a,b in PAIRS:
        pairs[a].add(b);pairs[b].add(a)
    baskets=defaultdict(set)
    for r in read_catalog(d/'compras.csv'):
        baskets[(r['usuario_id'],r['fecha'])].add(int(r['producto_id']))
    eligible=0;plausible=0
    for productids in baskets.values():
        if len(productids)<2:continue
        eligible+=1
        cats={products[p]['categoria'] for p in productids}
        # Same category fallback is disclosed, and complements are explicit.
        if len(cats)==1 or any(b in pairs.get(a,set()) for a in cats for b in cats if a!=b):
            plausible+=1
    report.update({'baskets':len(baskets),'multi_product_baskets':eligible,
                   'plausible_baskets':plausible,'plausible_fraction':round(plausible/max(1,eligible),4)})
    if plausible!=eligible:raise ValueError('unexplained category pair in purchase baskets')
    if require_real:
        if not (d/'source_mapping.csv').is_file():raise ValueError('no Amazon provenance')
        if not (d/'modelo'/'bow_image.npz').is_file() or report['indexed']!=report['products']:
            raise ValueError('missing real-image BoVW/TF-IDF vectors')
    return report


def online(dataset:Path,api_url='http://127.0.0.1:8017',queries=12):
    from tools.seed_tienda import Api
    api=Api(api_url)
    table={r['name']:r for r in api.get('/api/tables')}
    expected=offline(dataset)
    for name,count in [('productos',expected['products']),('compras',expected['purchases']),('stock',expected['stock']),('tiendas',30)]:
        if name not in table or int(table[name]['row_count'])!=count:
            raise ValueError(f'Live table {name} rows differ from dataset')
    index={t['name']:{i['name']:i['kind'].lower() for i in t['indexes']} for t in table.values()}
    if index['productos'].get('idx_productos_embedding')!='ivf':raise ValueError('missing IVF product image index')
    if index['tiendas'].get('idx_tiendas_ubicacion')!='rtree':raise ValueError('missing RTree store index')
    p=read_catalog(dataset/'productos.csv');by_id={int(r['id']):r for r in p}
    take=[p[(i*(len(p)-1))//(queries-1)] for i in range(queries)] if queries>1 else p[:1]
    links=defaultdict(set)
    for a,b in PAIRS:links[a].add(b);links[b].add(a)
    examples=[]
    for product in take:
        pid=int(product['id']);category=product['categoria']
        response=api.get(f'/api/recommend/copurchase/{pid}?k=10')
        rec=response.get('recomendaciones',[])
        candidates=[(r,by_id.get(int(r['producto_id']))) for r in rec]
        appropriate=[(r,y) for r,y in candidates if y and (y['categoria'] in links.get(category,set()) or y['categoria']==category)]
        if not appropriate:raise ValueError(f'No meaningful co-purchase for product {pid} ({category})')
        r,y=appropriate[0]
        examples.append({'producto_id':pid,'producto':product['nombre'],'categoria':category,
                         'recomendado_id':int(r['producto_id']),'recomendado':y['nombre'],
                         'categoria_recomendada':y['categoria'],'score':float(r['score'])})
    report={**expected,'live_import_passed':True,'ivf':True,'rtree':True,
            'live_copurchase_checks':len(examples),'successful_copurchase_checks':len(examples),
            'examples':examples}
    out=dataset/'issue127129_online_report.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    with (dataset/'issue129_copurchase_examples.csv').open('w',encoding='utf8',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=list(examples[0]));wr.writeheader();wr.writerows(examples)
    return report


def main():
    p=argparse.ArgumentParser();p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--api',help='If set, verify live API with 12 co-purchase examples')
    p.add_argument('--demo',action='store_true',help='Allow 30-product sample, not acceptance for #127')
    a=p.parse_args()
    report=online(a.dataset,a.api) if a.api else offline(a.dataset,require_real=not a.demo)
    print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
