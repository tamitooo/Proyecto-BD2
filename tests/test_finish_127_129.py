import importlib.util
from pathlib import Path
import csv
import pytest
from PIL import Image, ImageDraw

SPEC=importlib.util.spec_from_file_location('finish',Path(__file__).resolve().parents[1]/'tools'/'finish_127_129.py')
m=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(m)


def products(tmp_path):
    images=tmp_path/'imagenes';images.mkdir()
    rows=[]
    for i in range(1,13):
        cat=['laptops','mochilas','celulares','audifonos','toys','games'][((i-1)//2)]
        image=f'img_{i}.png'
        picture=Image.new('RGB',(160,160),'white');draw=ImageDraw.Draw(picture)
        for k in range(24):draw.line(((i*k+2)%150,0,(k*9+20)%150,150),fill=(20+i*10,20+k*8%255,150),width=2)
        picture.save(images/image)
        rows.append({'id':i,'nombre':f'{cat} item {i}','categoria':cat,'precio':20+i,'descripcion':f'original {cat} description','imagen':image})
    m._save_csv(tmp_path/'productos.csv',m.PRODUCT_FIELDS,[[p[x] for x in m.PRODUCT_FIELDS] for p in rows])
    return rows


def test_real_catalog_preserves_image_content_and_provenance(tmp_path):
    src=[]
    for i in range(15):
        image=Image.new('RGB',(60,30),color=(20*i%255,70,170))
        src.append({'Product Name':f'Gaming accessory {i} charger', 'Description':f'A useful charger number {i}',
           'Category':'Electronics | Accessories','Selling Price':f'$ {i+10}.99','Image':f'http://example.com/{i}.jpg',
           'Raw Image':image})
    products,groups=m.make_catalog(iter(src),tmp_path,needed=5)
    assert len(products)==5
    assert all((tmp_path/'imagenes'/p['imagen']).is_file() for p in products)
    assert len(m.read_catalog(tmp_path/'productos.csv'))==5
    assert len(m.read_catalog(tmp_path/'source_mapping.csv'))==5
    with Image.open(tmp_path/'imagenes'/products[0]['imagen']) as img:assert img.size==(160,160)


def test_purchases_are_complementary_repeatable_and_stock_all(tmp_path):
    p=products(tmp_path)
    a=m.build_complementary_purchases(p,tmp_path/'compras.csv')
    b=m.build_stores_stock(p,tmp_path)
    assert a['paired_products']==12
    assert a['coverage_fraction']==1.0
    assert a['purchases']>=72
    assert b['stores']==30
    check=m.verify(tmp_path,12)
    assert check['all_products_stocked']
    assert check['purchases']==a['purchases']
    rows=m.read_catalog(tmp_path/'compras.csv')
    grouped={}
    for x in rows:grouped.setdefault((x['usuario_id'],x['fecha']),set()).add(int(x['producto_id']))
    assert all(len(v)==2 for v in grouped.values())
    cats={int(x['id']):x['categoria'] for x in p}
    assert all(tuple(sorted(cats[i] for i in v)) in {tuple(sorted(pair)) for pair in m.PAIRS} for v in grouped.values())


def test_category_and_price_require_real_data(tmp_path):
    assert m._price('$1,299.90')==1299.90
    assert m._price('price not available') is None
    assert m._category('Earbud set','Electronics | Headphones')=='audifonos'
    assert m._category('Laptop sleeve backpack','Office Products')=='laptops' or m._category('Laptop sleeve backpack','Office Products')=='mochilas'
    with pytest.raises(RuntimeError,match='Only 0 real products'):
        m.make_catalog([],tmp_path,needed=3)
