"""Build a real-image Amazon catalog and plausible *synthetic* co-purchase baskets.

Offline sample: python -m tools.finish_127_129 --source sample --count 30 --output data/issue127129_sample
Real: python -m tools.finish_127_129 --source amazon-hf --count 2000 --output data/issue127129_amazon
Optional: --skip-vectors (CSV + genuine images, but NOT ready for IVF import).

Do not commit dataset or images. Product metadata comes from a public dataset;
synthetic buyers, purchases, stores and stock are demonstration fixtures.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
import os
import random
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps

ROOT=Path(__file__).resolve().parents[1]
SOURCE_ID='EmbeddingStudio/amazon-products-with-images'
PRODUCT_FIELDS=('id','nombre','categoria','precio','descripcion','imagen')
STOCK_FIELDS=('id','tienda_id','producto_id','cantidad')
PURCHASE_FIELDS=('id','usuario_id','producto_id','fecha','cantidad')
STORE_FIELDS=('id','nombre','lat','lon','distrito')
PAIRS=(('laptops','mochilas'),('celulares','audifonos'),('zapatillas','relojes'),
       ('electronics','accessories'),('electronics','office'),('toys','games'),
       ('toys','baby'),('books','office'),('home','kitchen'),('home','tools'),
       ('sports','outdoors'),('fashion','shoes'),('beauty','health'),
       ('pet','home'),('video_games','electronics'))
LIMA=[('Miraflores',-12.1211,-77.0297),('San Isidro',-12.0975,-77.0365),
      ('Surco',-12.1460,-76.9920),('La Molina',-12.0790,-76.9420),
      ('Los Olivos',-11.992,-77.07),('Lince',-12.0845,-77.031),
      ('Pueblo Libre',-12.0776,-77.0648),('Barranco',-12.1462,-77.0208),
      ('Cercado',-12.0464,-77.0428),('San Miguel',-12.0756,-77.0928)]


def _save_csv(path, fields, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f,lineterminator='\n');writer.writerow(fields);writer.writerows(rows)


def _category(title, category):
    txt=(str(category)+' '+str(title)).lower()
    rules=[('laptops',r'\blaptop|notebook computer|chromebook|macbook'),
       ('mochilas',r'backpack|rucksack|laptop bag|school bag|bookbag'),
       ('celulares',r'cell phones|smartphone|mobile phone|iphone|samsung galaxy'),
       ('audifonos',r'headphone|earphone|earbuds|headset|airpods'),
       ('zapatillas',r'\bsneaker|running shoe|athletic shoe'),
       ('relojes',r'\bwatch|smartwatch|wristwatch'),
       ('accessories',r'computer accessories|phone case|chargers|charger|keyboard|mouse|memory card|usb cable|adapter|hdmi'),
       ('electronics',r'electronics|computer|television|camera|audio|video|\bprinter'),
       ('books',r'\bbooks|book |literature|textbook'),
       ('office',r'office products|stationery|notebook|pens|school supplies'),
       ('kitchen',r'kitchen|cookware|utensils|blender|coffee maker'),
       ('home',r'home & kitchen|furniture|home decor|bedding|lighting'),
       ('tools',r'tools|home improvement|hardware'),
       ('sports',r'sports & outdoors|fitness|exercise|bicycle'),
       ('outdoors',r'camping|hiking|outdoor recreation|garden'),
       ('video_games',r'video games|playstation|xbox|nintendo|gaming'),
       ('games',r'board games|puzzles|game & accessories|card games'),
       ('baby',r'baby products|baby & toddler|baby gear'),
       ('toys',r'toys & games|dolls|stuffed animals|action figures'),
       ('pet',r'pet supplies|dog supplies|cat supplies'),
       ('beauty',r'beauty|cosmetics|makeup|skin care'),
       ('health',r'health & household|personal care|wellness'),
       ('shoes',r'shoes|boots|footwear'),
       ('fashion',r'clothing|apparel|fashion|shirts|dresses')]
    for k,regexp in rules:
        if re.search(regexp,txt):return k
    root=str(category).split('|',1)[0].strip().lower()
    return {'toys & games':'toys','home & kitchen':'home', 'sports & outdoors':'sports',
            'video games':'video_games','office products':'office','baby products':'baby'}.get(root,'other')


def _short(value,limit):
    v=re.sub(r'\s+',' ',str(value or '')).strip()
    while len(v.encode('utf-8'))>limit: v=v[:-1]
    return v


def _price(value):
    found=re.search(r'(\d[\d,]*\.?\d*)',str(value or ''))
    if not found:return None
    try:
        n=float(found.group(1).replace(',',''))
        return round(n,2) if math.isfinite(n) and n>0 else None
    except ValueError:return None


def _image_bytes(source):
    if isinstance(source,Image.Image):return source
    if isinstance(source,dict):
        if source.get('bytes'):return Image.open(io.BytesIO(source['bytes']))
        if source.get('path') and Path(source['path']).is_file():return Image.open(source['path'])
    return None


def _normalize_image(image:Image.Image,path:Path):
    # Genuine image content: white padding only, never generated product drawings.
    image=ImageOps.exif_transpose(image)
    image=ImageOps.contain(image.convert('RGB'),(160,160))
    out=Image.new('RGB',(160,160),'white')
    out.paste(image,((160-image.width)//2,(160-image.height)//2))
    out.save(path,format='PNG',optimize=True)


def amazon_stream():
    try:from datasets import load_dataset
    except ImportError as e:
        raise RuntimeError('Install datasets: python -m pip install "datasets>=3,<6"') from e
    return iter(load_dataset(SOURCE_ID,split='train',streaming=True))


def make_catalog(stream:Iterable[dict],destination:Path,needed:int=2000,max_scanned:int=24000,require_descriptors:bool=False):
    """Resumable write, never invent missing images or product descriptions."""
    images=destination/'imagenes';images.mkdir(parents=True,exist_ok=True)
    product_csv=destination/'productos.csv';mapping_csv=destination/'source_mapping.csv'
    rows=[];mappings=[];seen=set();group_counts=Counter();scanned=0
    # Resume from the existing metadata; a fresh catalog starts from row one.
    if product_csv.exists():
        with product_csv.open(encoding='utf-8',newline='') as f:rows=list(csv.DictReader(f))
        if mapping_csv.exists():
            with mapping_csv.open(encoding='utf-8',newline='') as f:mappings=list(csv.DictReader(f))
        if len(mappings)!=len(rows):raise RuntimeError('partial provenance: use a new output path')
        for p,m in zip(rows,mappings):
            if not (images/p['imagen']).is_file():raise RuntimeError('missing previously saved image: '+p['imagen'])
            seen.add(m['source_key']);group_counts[p['categoria']]+=1
    for source in stream:
        if len(rows)>=needed or scanned>=max_scanned:break
        scanned+=1
        title=_short(source.get('Product Name'),112)
        desc=_short(source.get('Description') or source.get('Product Specification'),780)
        price=_price(source.get('Selling Price'))
        cat=_category(title,source.get('Category',''))
        image=_image_bytes(source.get('Raw Image'))
        source_key=str(source.get('Image') or hashlib.sha256((title+desc).encode()).hexdigest())
        allowed={g for pair in PAIRS for g in pair}
        if not title or len(title)<3 or not desc or not price or image is None or cat not in allowed:continue
        if source_key in seen or group_counts[cat]>=max(150,int(needed*0.28)):continue
        pid=len(rows)+1;filename=f'amazon_{pid:06d}.png'
        try:
            _normalize_image(image,images/filename)
            if require_descriptors:
                from vector.extract_features import ExtractFeatures
                if ExtractFeatures.local_descriptors(images/filename,kind='image').shape[0] < 2:
                    (images/filename).unlink(missing_ok=True)
                    continue
        except (OSError,ValueError):
            (images/filename).unlink(missing_ok=True)
            continue
        if image is not None and hasattr(image,'close'):
            try:image.close()
            except:pass
        rows.append({'id':pid,'nombre':title,'categoria':cat,'precio':price,'descripcion':desc,'imagen':filename})
        mappings.append({'id':pid,'source_key':source_key,'original_category':str(source.get('Category','')),
                         'source_dataset':SOURCE_ID,'image_sha256':hashlib.sha256((images/filename).read_bytes()).hexdigest()})
        seen.add(source_key);group_counts[cat]+=1
        if len(rows)%100==0:
            _save_csv(product_csv,PRODUCT_FIELDS,[[r[f] for f in PRODUCT_FIELDS] for r in rows]);
            _save_csv(mapping_csv,('id','source_key','original_category','source_dataset','image_sha256'),
                      [[m[f] for f in ('id','source_key','original_category','source_dataset','image_sha256')] for m in mappings]);
            print(f'Real product images: {len(rows)}/{needed}; inspected {scanned}',flush=True)
    _save_csv(product_csv,PRODUCT_FIELDS,[[r[f] for f in PRODUCT_FIELDS] for r in rows])
    _save_csv(mapping_csv,('id','source_key','original_category','source_dataset','image_sha256'),
              [[m[f] for f in ('id','source_key','original_category','source_dataset','image_sha256')] for m in mappings])
    if len(rows)<needed:raise RuntimeError(f'Only {len(rows)} real products with valid images; requires {needed}. Rerun (resumable) or increase scan limit')
    return rows,dict(group_counts)


def read_catalog(path):
    with path.open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))


def _pairs(groups:dict):
    valid=[]
    for a,b in PAIRS:
        if a in groups and b in groups and a!=b:valid.append((a,b))
    return valid


def build_complementary_purchases(products:list[dict],out:Path,seed=2026,baskets_per_product=3):
    """Every product X is placed in baskets with a real complementary category.
    Repeat anchor products across independent users; never invent behavioral ground truth.
    """
    rnd=random.Random(seed);groups=defaultdict(list)
    for p in products:groups[p['categoria']].append(int(p['id']))
    links=_pairs(groups)
    if not links:raise ValueError('No compatible shopping categories found; cannot invent complementary purchases')
    neighbor=defaultdict(list)
    for a,b in links:
        neighbor[a].append(b);neighbor[b].append(a)
    eligible=[p for p in products if p['categoria'] in neighbor]
    # When the source has categories with no complementary partner available,
    # pair two distinct items of the same category (e.g. a matching toy set).
    # Never match across entirely unrelated categories as a silent fallback.
    fallback_categories=[]
    for cat,ids in groups.items():
        if cat not in neighbor and len(ids)>1:
            neighbor[cat]=[cat];fallback_categories.append(cat)
    eligible=[p for p in products if p['categoria'] in neighbor]
    if len(eligible)<len(products):
        raise ValueError(f'Only {len(eligible)} of {len(products)} products have a plausible purchase complement')
    rows=[];counts=Counter();start=date(2026,8,1)
    for p in eligible:
        cat=p['categoria'];pid=int(p['id']);targets=neighbor[cat]
        for repeat in range(baskets_per_product):
            other_cat=targets[(repeat+pid)%len(targets)]
            pool=[x for x in groups[other_cat] if x!=pid]
            if not pool:continue
            # A popular subset is shared by many independent users, producing measurable co-purchase support.
            hub=pool[:min(18,len(pool))]
            # Repeat a stable complement for the same anchor across buyers.
            # Otherwise user-held-out co-purchase learns no usable relation.
            slot=int.from_bytes(hashlib.sha256(f'{pid}:{other_cat}'.encode()).digest()[:4],'big')%len(hub)
            other=hub[(slot+(repeat//3))%len(hub)]
            user=1+len(rows)//2
            day=(start+timedelta(days=(user*7+repeat)%90)).isoformat()
            for item in (pid,other):
                rows.append([len(rows)+1,user,item,day,rnd.randint(1,2)])
            counts[f'{cat}->{other_cat}']+=1
    _save_csv(out,PURCHASE_FIELDS,rows)
    return {'purchases':len(rows),'users':len(rows)//2,'baskets':len(rows)//2,
            'affinity_edges':dict(counts),'same_category_fallbacks':fallback_categories,
            'paired_products':len(eligible),
            'coverage_fraction':round(len(eligible)/len(products),4)}


def build_stores_stock(products:list[dict],output:Path,seed=2026):
    r=random.Random(seed);stores=[];stock=[]
    for i in range(30):
        area,lat,lon=LIMA[i%len(LIMA)];stores.append([i+1,f'Tienda Demo {i+1:02d}',round(lat+r.uniform(-.002,.002),6),round(lon+r.uniform(-.002,.002),6),area])
    for item in products:
        pid=int(item['id'])
        for store in r.sample(range(1,31),r.randint(2,4)):
            stock.append([len(stock)+1,store,pid,r.randint(1,40)])
    _save_csv(output/'tiendas.csv',STORE_FIELDS,stores)
    _save_csv(output/'stock.csv',STOCK_FIELDS,stock)
    return {'stores':len(stores),'stock':len(stock)}


def build_vectors(products:list[dict],output:Path,*,words:int=24,sample:int=180):
    """REAL SIFT -> BoVW/TF-IDF embeddings; no placeholder vectors."""
    from vector.bow import train_model,model_path
    from vector.extract_features import ExtractFeatures
    from vector.sift import sift_backend
    raw=[];valid=[]
    for i,p in enumerate(products):
        descriptors=ExtractFeatures.local_descriptors(output/'imagenes'/p['imagen'],kind='image')
        raw.append(descriptors)
        if descriptors.shape[0]>=2:valid.append(descriptors)
        if (i+1)%250==0:print(f'SIFT analyzed {i+1}/{len(products)}',flush=True)
    if len(valid)<20:raise RuntimeError('Not enough SIFT-compatible images')
    # Train on representative source categories, not just the first Amazon rows.
    training_by_category=defaultdict(list)
    for p,descriptors in zip(products,raw):
        if descriptors.shape[0]>=2:training_by_category[p['categoria']].append(descriptors)
    training=[];keys=sorted(training_by_category)
    while len(training)<sample and any(training_by_category.values()):
        for key in keys:
            if training_by_category[key] and len(training)<sample:
                training.append(training_by_category[key].pop(0))
    model=train_model('image',training,words,seed=2026,descriptor_backend=sift_backend(),max_iter=18,max_descriptors=8000)
    (output/'modelo').mkdir(exist_ok=True)
    model.save(model_path(output/'modelo','image'))
    indexed=[]
    for p,local in zip(products,raw):
        if local.shape[0]<2:
            # If the original is almost featureless, the model needs a nonzero vector.
            # Fail explicitly rather than write invented nearest-neighbor vectors.
            raise RuntimeError(f'Missing SIFT descriptors for real image {p["imagen"]}; replace this source image')
        vector=model.encode(local)
        if not any(float(x)>0 for x in vector):
            raise RuntimeError(f'Empty BoVW features for image {p["imagen"]}')
        indexed.append([p[k] for k in PRODUCT_FIELDS]+[json.dumps([round(float(v),6) for v in vector])])
    _save_csv(output/'productos_indexados.csv',(*PRODUCT_FIELDS,'embedding'),indexed)
    return {'features':'SIFT-BoVW-TFIDF','vocabulary_words':model.n_words,'indexed_products':len(indexed)}


def verify(output:Path,expected=0):
    products=read_catalog(output/'productos.csv');pids={int(p['id']) for p in products}
    if expected and len(pids)!=expected:raise ValueError('product count does not match target')
    if len(products)!=len(pids):raise ValueError('duplicate product IDs')
    for p in products:
        file=output/'imagenes'/p['imagen']
        with Image.open(file) as x:x.verify()
    def rd(p):
        with (output/p).open(encoding='utf8',newline='') as f:return list(csv.DictReader(f))
    purchases=rd('compras.csv');stock=rd('stock.csv');stores=rd('tiendas.csv')
    if not purchases or not stock or len(stores)!=30:raise ValueError('incomplete generated tables')
    if set(int(s['producto_id']) for s in stock)!=pids:raise ValueError('some products have no stock')
    seen=set();good=0
    for b in purchases:
        pid=int(b['producto_id']); key=(b['usuario_id'],b['fecha']);
        if pid not in pids or int(b['cantidad'])<1:raise ValueError('bad foreign key/quantity in purchases')
        if (key,pid) in seen:raise ValueError('duplicate user/date/product')
        seen.add((key,pid));good+=1
    if not (output/'productos_indexados.csv').is_file():indexed=0
    else:indexed=len(rd('productos_indexados.csv'))
    return {'products':len(products),'images':len(products),'purchases':good,'stock':len(stock),
            'stores':len(stores),'indexed':indexed,'all_products_stocked':True}


def main(argv=None):
    pa=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    pa.add_argument('--source',choices=['amazon-hf','sample'],default='amazon-hf')
    pa.add_argument('--count',type=int,default=2000)
    pa.add_argument('--output',type=Path,default=ROOT/'data'/'issue127129_amazon')
    pa.add_argument('--skip-vectors',action='store_true',help='Skip SIFT model/IVF-compatible CSV; not ready for seed_part5_fast')
    pa.add_argument('--scan-limit',type=int,default=24000)
    args=pa.parse_args(argv)
    if args.source=='amazon-hf' and not 2000<=args.count<=5000:
        pa.error('issue #127 requires 2000-5000 real products')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    try:
        if args.source=='sample':
            origin=ROOT/'examples'/'tienda';products=read_catalog(origin/'productos.csv')
            (output/'imagenes').mkdir(exist_ok=True)
            for p in products:shutil.copyfile(origin/'imagenes'/p['imagen'],output/'imagenes'/p['imagen'])
            shutil.copyfile(origin/'productos.csv',output/'productos.csv')
            src={'source':'examples/tienda (illustrative sample; NOT issue #127)','genuine_products':False}
        else:
            products,category_counts=make_catalog(amazon_stream(),output,args.count,args.scan_limit,require_descriptors=not args.skip_vectors)
            src={'source':SOURCE_ID,'genuine_products':True,'category_counts':category_counts,
                 'source_license_claim':'Apache-2.0 dataset card; product image rights not independently verified',
                 'redistribution':'Do not upload image assets to a public Git repo'}
        if not (output/'compras.csv').is_file():source=build_complementary_purchases(products,output/'compras.csv')
        else:source={'note':'existing purchases preserved'}
        if not (output/'stock.csv').is_file():inventory=build_stores_stock(products,output)
        else:inventory={'note':'existing stores and stock preserved'}
        if not args.skip_vectors and not (output/'productos_indexados.csv').is_file():vectors=build_vectors(products,output)
        else:vectors={'note':'vectors skipped or already present'}
        # Required by the team's existing seed_part5_fast / generate_part5_data.verify contract.
        def _count_rows(name):
            with (output/name).open(encoding='utf-8',newline='') as f:
                return sum(1 for _ in csv.DictReader(f))
        manifest={'source':str(output/'productos.csv'),'synthetic_stores':True,
                  'synthetic_purchases':True,'seed':2026,'products':len(products),
                  'stores':_count_rows('tiendas.csv'),'stock':_count_rows('stock.csv'),
                  'purchases':_count_rows('compras.csv'),'schema':'tools.seed_part5_fast compatible',
                  'assets_copied':True,'precomputed_embeddings':(output/'productos_indexados.csv').is_file(),
                  'visual_model':(output/'modelo'/'bow_image.npz').is_file()}
        (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        checked=verify(output,len(products))
        from tools.generate_part5_data import verify as verify_team_format
        verify_team_format(output,image_dir=output/'imagenes')
        report={**src,**source,**inventory,**vectors,**checked,'seed':2026,
                'warning':'Purchases and store locations are synthetic; products/images are from the cited source'}
        (output/'issue127129_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        print(json.dumps(report,ensure_ascii=False,indent=2))
    except Exception as exc:
        print('SETUP FAILED:',str(exc),file=sys.stderr)
        raise

if __name__=='__main__':main()
