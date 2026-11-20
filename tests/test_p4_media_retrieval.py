import csv,json
import numpy as np
import pytest
from benchmarks.p4_media_retrieval import norm_rows, exact_topk, metric_row, load_image


def test_exact_cosine_and_self_exclusion():
    x=np.asarray([[1,0],[0.9,0.1],[0,1]],dtype=float)
    assert exact_topk([1,2,3],x,np.array([1.,0.]),2,exclude=1)==[2,3]
    assert exact_topk([1,2,3],x,np.array([1.,0.]),1)==[1]


def test_recall_vs_exact_and_label_precision_are_distinct():
    m=metric_row([2,3],[2,4],{3,5},2)
    assert m['retrieval_recall_at_k']==.5
    assert m['label_precision_at_k']==.5
    assert m['label_hit_rate_at_k']==1


def test_malformed_vectors_rejected():
    with pytest.raises(ValueError):norm_rows(np.array([[0.,0.]]))
    with pytest.raises(ValueError):norm_rows(np.array([[np.nan,1.]]))


def test_image_gallery_schema_and_query_label(tmp_path):
    ind=tmp_path/'productos_indexados.csv';labels=tmp_path/'etiquetas.csv'
    with ind.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['id','categoria','embedding'])
        w.writerows([[1,'circulo','[1,0]'],[2,'triangulo','[0,1]'],[3,'circulo','[0.9,0.1]']])
    with labels.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['id','figura','color'])
        w.writerows([[1,'circulo','rojo'],[2,'triangulo','azul'],[3,'circulo','rojo']])
    ids,mat,tags,qs,scope=load_image(ind,3,labels,None,None,None,2)
    assert ids==[1,2,3] and mat.shape==(3,2)
    assert tags[1]==('circulo','rojo')
    assert scope=='leave-one-out gallery'
    assert qs[0][2]==('circulo','rojo')
