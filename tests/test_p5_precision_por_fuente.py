"""Test the basket relevance and user-level hold-out for Issue #141."""
import csv
import json

from benchmarks.p5_precision_por_fuente import baskets_from_csv, cases_from_baskets, folds_by_user, evaluate


def dump_csv(path, headers, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w=csv.writer(f);w.writerow(headers);w.writerows(rows)


def test_basket_relevance_and_deduplication(tmp_path):
    p=tmp_path/'compras.csv'
    dump_csv(p, ['id','usuario_id','producto_id','fecha','cantidad'],[
      [1,10,1,'2026-11-01',1], [2,10,2,'2026-11-01',2],
      [3,10,2,'2026-11-01',1], [4,10,3,'2026-11-02',1],
      [5,11,5,'2026-11-01',1], [6,11,6,'2026-11-01',1]])
    baskets,total=baskets_from_csv(p,{1,2,3,5,6})
    assert total==6
    cases=cases_from_baskets(baskets)
    assert len(cases)==4
    assert next(c for c in cases if c['anchor']==1)['relevant']=={2}
    assert next(c for c in cases if c['anchor']==2)['relevant']=={1}
    assert all(c['anchor'] not in c['relevant'] for c in cases)


def test_disjoint_user_folds_are_repeatable():
    folds=folds_by_user(set(range(10)),5,2026)
    assert folds==folds_by_user(set(range(10)),5,2026)
    assert set().union(*folds)==set(range(10))
    assert all(not (f & g) for i,f in enumerate(folds) for g in folds[i+1:])


def test_full_report_and_no_heldout_user_leakage(tmp_path):
    products=tmp_path/'productos.csv';purchases=tmp_path/'compras.csv';out=tmp_path/'report'
    dump_csv(products, ['id','nombre','categoria','precio','descripcion','imagen'],
             [[i,f'item {i}','laptops' if i<5 else 'mochilas',100+i, f'product {i}',f'{i}.png'] for i in range(1,11)])
    # Each user has a unique partner for product 1; no other user's training
    # purchases should reveal that user's particular held-out partner.
    dump_csv(purchases,['id','usuario_id','producto_id','fecha','cantidad'],[
     [n*2-1,n,1,'2026-11-01',1] for n in range(1,6)] +
     [[n*2,n,n+1,'2026-11-01',1] for n in range(1,6)])
    report=evaluate(products,purchases,out,folds=5,limit=None,render_chart=False)
    assert report['products']==10 and report['purchases']==10
    assert report['eligible_cases']==10 and report['evaluated_cases']==10
    assert report['visual_included'] is False
    with (out/'p5_precision_casos.csv').open(encoding='utf-8') as f:
        rows=list(csv.DictReader(f))
    cases=[r for r in rows if r['fuente']=='co_compra' and r['producto_X']=='1']
    assert len(cases)==5
    for r in cases:
        # The unique evaluation user's partner is held out and never appears
        # in any other user's purchase data.
        assert str(int(r['usuario'])+1) not in r['recomendados'].split()
    assert (out/'p5_precision_por_fuente.csv').is_file()
    assert json.loads((out/'p5_precision_por_fuente.json').read_text())['evaluated_cases']==10


def test_invalid_purchases_are_rejected(tmp_path):
    import pytest
    p=tmp_path/'compras.csv'
    dump_csv(p,['id','usuario_id','producto_id','fecha','cantidad'],[[1,1,9,'2026-01-01',1]])
    with pytest.raises(ValueError,match='not in catalog'):
        baskets_from_csv(p,{1,2})
