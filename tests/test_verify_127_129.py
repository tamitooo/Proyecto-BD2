import importlib.util
from pathlib import Path
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0,str(ROOT))
from tools.finish_127_129 import build_complementary_purchases,build_stores_stock,_save_csv,PRODUCT_FIELDS
from tools.verify_127_129 import offline


def test_offline_acceptance_no_false_real_claim(tmp_path):
    images=tmp_path/'imagenes';images.mkdir()
    rows=[]
    for i in range(1,11):
        cat='laptops' if i<=5 else 'mochilas'
        filename=f'x{i}.png';Image.new('RGB',(64,64),'white').save(images/filename)
        rows.append({'id':i,'nombre':f'item{i}','categoria':cat,'precio':50,'descripcion':'long description','imagen':filename})
    _save_csv(tmp_path/'productos.csv',PRODUCT_FIELDS,[[r[k] for k in PRODUCT_FIELDS] for r in rows])
    build_complementary_purchases(rows,tmp_path/'compras.csv')
    build_stores_stock(rows,tmp_path)
    sample=offline(tmp_path,require_real=False)
    assert sample['plausible_fraction']==1
    assert sample['all_products_stocked']
    import pytest
    with pytest.raises(ValueError,match='2,000-5,000 real products'):
        offline(tmp_path,require_real=True)
