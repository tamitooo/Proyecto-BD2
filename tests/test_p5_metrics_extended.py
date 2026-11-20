from pathlib import Path
import csv, json
import pytest
from benchmarks.p5_precision_por_fuente import extra_metrics, candidate_weights, evaluate


def test_precision_ceiling_random_and_perfect_ranking():
    m=extra_metrics([2],frozenset({2}),30,10)
    assert m['precision_at_k']==pytest.approx(.1)
    assert m['max_precision_at_k']==pytest.approx(.1)
    assert m['recall_at_k']==1.0 and m['hit_rate_at_k']==1.0
    assert m['ndcg_at_k']==1.0 and m['mrr_at_k']==1.0
    assert m['random_precision_at_k']==pytest.approx(1/29)
    assert m['p_at_3']==pytest.approx(1/3)


def test_nonhit_and_multiple_relevants():
    m=extra_metrics([3,4,5,2],frozenset({1,2}),12,10)
    assert m['max_precision_at_k']==.2
    assert m['precision_at_k']==.1
    assert m['hit_rate_at_k']==1.0
    assert m['mrr_at_k']==.25
    assert m['ndcg_at_k']<1
    assert m['p_at_3']==0


def test_duplicate_recommendations_rejected():
    with pytest.raises(ValueError,match='duplicate'):
        extra_metrics([2,2],frozenset({2}),30)


def test_non_leaky_nested_choice_on_small_fixture(tmp_path):
    pro=tmp_path/'productos.csv';buy=tmp_path/'compras.csv';out=tmp_path/'result'
    with pro.open('w',encoding='utf8',newline='') as f:
        w=csv.writer(f);w.writerow(['id','nombre','categoria','precio','descripcion','imagen'])
        w.writerows([[i,f'item {i}', 'a' if i%2 else 'b', 10+i, f'item {i} description', f'{i}.png'] for i in range(1,13)])
    with buy.open('w',encoding='utf8',newline='') as f:
        w=csv.writer(f);w.writerow(['id','usuario_id','producto_id','fecha','cantidad'])
        for u in range(1,11):
            for offset,pid in enumerate([u%6+1,(u%6+1)%6+1],1):
                w.writerow([u*2+offset,u,pid,'2026-11-01',1])
    r=evaluate(pro,buy,out,folds=5,limit=None,render_chart=False)
    assert r['nested_cv_weights'] is True
    assert r['results'][-1]['source']=='fusion_validada'
    assert 0<=r['max_precision_at_k']<=1
    assert len(r['folds'])==5 and all('inner_cv_precision' in f for f in r['folds'])
    assert 'p_at_3' in r['results'][0] and 'ndcg_at_k' in r['results'][0]
    report=(out/'p5_precision_para_informe.md').read_text(encoding='utf8')
    assert 'Máximo' in report and 'Validación' in report
    assert len(list(csv.DictReader((out/'p5_precision_casos.csv').open())))==r['evaluated_cases']*len(r['results'])
