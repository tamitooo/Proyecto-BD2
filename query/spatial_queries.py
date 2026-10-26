import time
from query.query_planner import DistanceExpression
from spatial.index import SpatialIndex
from spatial.geo import polygon_to_mbr

class SpatialQueryError(Exception): pass

def find_spatial_predicate(q):
    for p in q.predicates:
        if getattr(p,"is_spatial",False):return p
    for g in q.or_groups:
        for p in g:
            if getattr(p,"is_spatial",False):return p
    return None
def find_distance_predicate(q):return next((p for p in q.predicates if getattr(p,"distance",None) is not None),None)
def find_polygon_predicate(q):return next((p for p in q.predicates if p.__class__.__name__=="PolygonPredicate"),None)
def find_spatial_order_by(q):return next((x for x in q.order_by if getattr(x,"is_spatial",False)),None)
def spatial_kind(q):
    if find_spatial_order_by(q):return "knn"
    if find_polygon_predicate(q):return "polygon"
    if find_distance_predicate(q):return "range"
    return None

class SpatialExecutor:
    def __init__(self,catalog):self.catalog=catalog
    def _index_for(self,table,expr):
        r=self.catalog.spatial_index_for(table.name,expr.column)
        if not r:raise SpatialQueryError(f"la columna espacial '{expr.column}' de '{table.name}' no tiene índice R-Tree")
        return r
    @staticmethod
    def _row(table,rid):return table.storage.read(rid) if table.storage_kind=="heap" else table.storage.read_rid(rid)
    def _materialize(self,table,index,matches):
        out=[]
        for rid,d in matches:
            row=self._row(table,rid)
            if row is None:continue
            row=dict(row);lat,lon=index.coordinates(rid);row.update({"_lat":lat,"_lon":lon,"_distance":d});out.append(row)
        return out
    @staticmethod
    def _trace(op,table,name,ms,**details):
        return {"table":table.name,"planner_type":"spatial_rtree","access_path":op,"used_indexes":[name],"steps":[{"operator":op,"table":table.name,"index":name,"reason":"R-Tree: poda por MBR y verificación exacta","details":details}],"runtime_steps":[{"operator":op,"elapsed_ms":round(ms,6),"rows_out":details.get("rows_out"),"index":name}]}
    def execute_range(self,table,predicate,*,limit=None):
        expr=predicate.distance
        if not expr:raise SpatialQueryError("predicado no espacial")
        reg=self._index_for(table,expr);idx=reg.implementation;radius=float(predicate.value);t=time.perf_counter();matches=idx.range_search(expr.point,radius,metric=expr.metric);ms=(time.perf_counter()-t)*1000;rows=self._materialize(table,idx,matches);rows=rows[:limit] if limit is not None else rows
        return rows,self._trace("RTREE_RANGE_SCAN",table,reg.metadata.name,ms,rows_in=len(idx),rows_out=len(rows),radius=radius,metric=expr.metric,point=list(expr.point),candidates=len(matches))
    def execute_knn(self,table,order_by,k):
        expr=order_by.distance
        if not expr:raise SpatialQueryError("ORDER BY no espacial")
        if order_by.descending:raise SpatialQueryError("k-NN requiere ASC")
        reg=self._index_for(table,expr);idx=reg.implementation;t=time.perf_counter();matches=idx.knn(expr.point,k,metric=expr.metric);ms=(time.perf_counter()-t)*1000;rows=self._materialize(table,idx,matches)
        return rows,self._trace("RTREE_KNN",table,reg.metadata.name,ms,rows_in=len(idx),rows_out=len(rows),k=k,metric=expr.metric,point=list(expr.point),candidates=len(matches))
    def execute_polygon(self,table,expression,ring):
        reg=self._index_for(table,expression);idx=reg.implementation;t=time.perf_counter();matches=idx.polygon_search(ring);ms=(time.perf_counter()-t)*1000;rows=[]
        for rid,(lat,lon) in matches:
            row=self._row(table,rid)
            if row is not None:
                row=dict(row);row.update({"_lat":lat,"_lon":lon,"_distance":None});rows.append(row)
        return rows,self._trace("RTREE_POLYGON",table,reg.metadata.name,ms,rows_in=len(idx),rows_out=len(rows),vertices=len(ring),polygon_mbr=list(polygon_to_mbr(ring)))
