from __future__ import annotations
import itertools,re,time
from dataclasses import dataclass,field,replace
from typing import Any,Dict,Iterable,List,Optional,Sequence,Tuple
from indexes.clustered_bplus import ClusteredBPlusIndex
from operators.external_sort import ExternalSort
from operators.external_hashing import ExternalHashing
from query.catalog import Catalog,CatalogError,TableMetadata
from query.query_planner import EQUALITY_OPERATORS,OrderBy,Predicate,QueryPlanner,DistanceExpression
from query.query_result import QueryResult
from query.spatial_queries import SpatialExecutor,SpatialQueryError,find_distance_predicate,find_polygon_predicate,find_spatial_order_by,spatial_kind
from query.sql_parser import *
from spatial.geo import euclidean,haversine
from transactions.lock_manager import LockManager

class QueryExecutionError(Exception):pass
@dataclass
class TransactionState:
    id:str;active:bool=True;statements:int=0;snapshots:Dict[str,Dict[str,Any]]=field(default_factory=dict);created_tables:List[str]=field(default_factory=list);locked_tables:List[str]=field(default_factory=list)

_AGG=re.compile(r"^\s*(COUNT|SUM|AVG|MIN|MAX)\s*\(\s*(\*|[A-Za-z_][A-Za-z0-9_]*)\s*\)(?:\s+AS\s+([A-Za-z_][A-Za-z0-9_]*))?\s*$",re.I)

class QueryExecutor:
    def __init__(self,catalog:Catalog,*,parser=None,external_sort=None,external_hashing=None,lock_manager=None):
        self.catalog=catalog;self.parser=parser or SQLParser();self.external_sort=external_sort or ExternalSort();self.external_hashing=external_hashing or ExternalHashing();self.lock_manager=lock_manager or LockManager();self._txn=None;self._txcounter=itertools.count(1);self._seq_reorgs={};self.named_points={}
    @property
    def transaction(self):return self._txn
    def execute(self,sql_or_statement,*,raise_on_error=False):
        start=time.perf_counter(); name="UNKNOWN"
        try:
            s=self.parser.parse(sql_or_statement) if isinstance(sql_or_statement,str) else sql_or_statement;name=self._name(s)
            if isinstance(s,TransactionStatement):r=self._transaction(s)
            elif isinstance(s,SetPointStatement):r=self._set_point(s)
            elif isinstance(s,SelectStatement):r=self._select(s)
            elif isinstance(s,InsertStatement):r=self._insert(s)
            elif isinstance(s,DeleteStatement):r=self._delete(s)
            elif isinstance(s,UpdateStatement):r=self._update(s)
            elif isinstance(s,CreateTableStatement):r=self._create_table(s)
            elif isinstance(s,DropTableStatement):r=self._drop_table(s)
            elif isinstance(s,CreateIndexStatement):r=self._create_index(s)
            elif isinstance(s,DropIndexStatement):r=self._drop_index(s)
            elif isinstance(s,ExplainStatement):r=self._explain(s)
            else:raise QueryExecutionError(f"unsupported {type(s).__name__}")
            r.execution_time_ms=self._ms(start)
            if r.execution_plan is not None:r.execution_plan["total_execution_time_ms"]=r.execution_time_ms
            return r
        except Exception as e:
            if raise_on_error:raise
            return QueryResult.fail(name,e,execution_time_ms=self._ms(start))
    # ---------- SELECT ----------
    def _select(self,s):
        q=s.query_spec;self._resolve_named_points(q);t=self.catalog.get_table(q.table);self._validate_select(s,t)
        kind=spatial_kind(q)
        if kind:
            r=self._spatial(s,t,kind)
            if r is not None:return r
        plan=self._planner().plan(q);runtime=[];st=time.perf_counter();rows=self._access(t,plan);self._runtime(runtime,plan.steps[0].operator,st,rows_out=len(rows),table=t.name,index=plan.steps[0].index)
        if q.or_groups:rows=[x for x in rows if self.matches_query(x,q)]
        elif q.predicates:
            spatial=[p for p in q.predicates if getattr(p,"distance",None)]
            normal=[p for p in q.predicates if not getattr(p,"is_spatial",False)]
            if spatial:rows=self._filter_spatial_linear(rows,spatial)
            if normal:rows=[x for x in rows if self.matches_all(x,normal)]
        if q.joins:rows=self._joins(rows,q.joins,runtime)
        aggs=self._aggregates(s.columns)
        if q.group_by:
            key=q.group_by[0] if len(q.group_by)==1 else tuple(q.group_by);st=time.perf_counter();before=len(rows);rows=self.external_hashing.group_by(rows,key=key,aggregates=aggs or None);self._runtime(runtime,"EXTERNAL_HASH_GROUP_BY",st,rows_in=before,rows_out=len(rows))
        elif aggs:
            rows=[self._aggregate_all(rows,aggs)]
        if q.order_by and any(x.operator=="EXTERNAL_SORT" for x in plan.steps):rows=self._sort(rows,q.order_by,runtime)
        projected,cols=self._project(rows,s.columns)
        if s.limit is not None:projected=projected[:s.limit]
        p=plan.to_dict();p["runtime_steps"]=runtime
        return QueryResult.ok("SELECT",columns=cols,rows=projected,affected_rows=len(projected),execution_plan=p)
    def _spatial(self,s,t,kind):
        ex=SpatialExecutor(self.catalog);q=s.query_spec
        try:
            if kind=="range":
                p=find_distance_predicate(q);rows,plan=ex.execute_range(t,p,limit=s.limit)
                normals=[x for x in q.predicates if not getattr(x,"is_spatial",False)]
                if normals:rows=[r for r in rows if self.matches_all(r,normals)]
            elif kind=="knn":
                o=find_spatial_order_by(q)
                if s.limit is None:raise SpatialQueryError("k-NN necesita LIMIT")
                rows,plan=ex.execute_knn(t,o,s.limit)
            else:
                p=find_polygon_predicate(q)
                if not p:return None
                rows,plan=ex.execute_polygon(t,DistanceExpression(p.column,p.ring[0]),p.ring)
        except SpatialQueryError as e:
            if "no tiene índice" in str(e):return None
            raise
        projected,cols=self._project(rows,s.columns)
        return QueryResult.ok("SELECT",columns=cols,rows=projected,affected_rows=len(projected),execution_plan={**plan,"spatial":True,"kind":kind})
    def _filter_spatial_linear(self,rows,preds):
        out=list(rows)
        for p in preds:
            e=p.distance; kept=[]
            for row in out:
                latc=e.column if e.column in row else next((c for c in row if c.lower() in {"lat","latitud","latitude"}),None);lonc=next((c for c in row if c.lower() in {"lon","lng","longitud","longitude"}),None)
                if not latc or not lonc:continue
                pt=(float(row[latc]),float(row[lonc]));d=euclidean(e.point,pt) if e.metric=="euclidean" else haversine(e.point,pt)
                if (p.operator=="<" and d<float(p.value)) or (p.operator=="<=" and d<=float(p.value)):
                    x=dict(row);x.update({"_distance":d,"_lat":pt[0],"_lon":pt[1]});kept.append(x)
            out=kept
        return out
    # ---------- DML ----------
    def _insert(self,s):
        t=self.catalog.get_table(s.table);cols=t.schema.col_names()
        if len(s.values)!=len(cols):raise QueryExecutionError(f"INSERT expected {len(cols)} values")
        self._snapshot(t);row=dict(zip(cols,s.values));st=time.perf_counter();rid=t.storage.insert(row)
        try:
            if t.storage_kind=="sequential":
                n=t.storage.n_reorganizaciones
                if n!=self._seq_reorgs.get(t.name):self._seq_reorgs[t.name]=n;self.catalog.rebuild_indexes(t.name)
                else:self._index_insert(t,row,rid)
            elif self.catalog.clustered_index(t.name): self.catalog.recluster_table(t.name)
            else:self._index_insert(t,row,rid)
        except Exception:
            if t.storage_kind=="heap":t.storage.delete(rid)
            else:t.storage.delete(row[t.schema.primary_key])
            self.catalog.rebuild_indexes(t.name);raise
        self._touch();return QueryResult.ok("INSERT",affected_rows=1,execution_plan=self._direct_plan(t,"INSERT",list(t.indexes),st))
    def _delete(self,s):
        t=self.catalog.get_table(s.table);self._snapshot(t);cand=list(t.storage.scan());match=[(rid,row) for rid,row in cand if self.matches_query(row,s)];st=time.perf_counter();n=0
        if t.storage_kind=="sequential":
            for _,row in match:n+=bool(t.storage.delete(row[t.schema.primary_key]))
            if n:self.catalog.rebuild_indexes(t.name)
        else:
            for rid,row in match:
                if t.storage.delete(rid):n+=1;self._index_delete(t,row,rid)
        self._touch();return QueryResult.ok("DELETE",affected_rows=n,execution_plan=self._direct_plan(t,"DELETE",[],st))
    def _update(self,s):
        t=self.catalog.get_table(s.table);self._snapshot(t);oldrows=[dict(r) for _,r in t.storage.scan()];match=[(rid,row) for rid,row in t.storage.scan() if self.matches_query(row,s)];assign=dict(s.assignments);st=time.perf_counter();n=0
        try:
            if t.storage_kind=="sequential":
                pk=t.schema.primary_key
                for _,row in match:
                    nr={**row,**assign};
                    if t.storage.delete(row[pk]):t.storage.insert(nr);n+=1
                if n:self.catalog.rebuild_indexes(t.name)
            else:
                for rid,row in match:
                    if t.storage.update(rid,{**row,**assign}):n+=1
                c=self.catalog.clustered_index(t.name)
                if n and c and c.metadata.column in assign:self.catalog.recluster_table(t.name)
                elif n and t.indexes:self.catalog.rebuild_indexes(t.name)
        except Exception:
            t.storage.replace_all(oldrows);self.catalog.rebuild_indexes(t.name);raise
        self._touch();return QueryResult.ok("UPDATE",affected_rows=n,execution_plan=self._direct_plan(t,"UPDATE",list(t.indexes),st))
    # ---------- DDL ----------
    def _create_table(self,s):
        t=self.catalog.create_table(s.table,s.columns,s.primary_key,storage_kind=s.storage_kind,if_not_exists=s.if_not_exists)
        if self._txn:self._txn.created_tables.append(t.name);self._touch()
        return QueryResult.ok("CREATE TABLE",columns=["table","storage","primary_key","indexes"],rows=[{"table":t.name,"storage":t.storage_kind,"primary_key":t.schema.primary_key,"indexes":", ".join(t.indexes)}],execution_plan={"table":t.name,"planner_type":"ddl","access_path":"CREATE_TABLE","used_indexes":list(t.indexes),"steps":[],"runtime_steps":[]})
    def _drop_table(self,s):
        if self.catalog.has_table(s.table):self._snapshot(self.catalog.get_table(s.table))
        ok=self.catalog.drop_table(s.table,if_exists=s.if_exists);self._touch();return QueryResult.ok("DROP TABLE",affected_rows=int(ok),rows=[{"table":s.table.lower(),"dropped":ok}])
    def _create_index(self,s):
        t=self.catalog.get_table(s.table);self._snapshot(t);st=time.perf_counter();r=self.catalog.create_index(s.table,s.column,kind=s.kind,unique=s.unique,name=s.name,if_not_exists=s.if_not_exists,lon_column=s.column2);self._touch();ms=self._ms(st)
        return QueryResult.ok("CREATE INDEX",columns=["indice","tabla","columna","tecnica","filas"],rows=[{"indice":r.metadata.name,"tabla":t.name,"columna":r.metadata.column,"tecnica":r.metadata.kind,"filas":sum(1 for _ in t.storage.scan())}],affected_rows=1,execution_plan={"table":t.name,"planner_type":"ddl","access_path":"CREATE_INDEX","used_indexes":[r.metadata.name],"index_build_time_ms":ms,"steps":[{"operator":"CREATE_INDEX","table":t.name,"index":r.metadata.name,"reason":"índice construido sobre datos existentes","details":{"kind":r.metadata.kind}}],"runtime_steps":[]})
    def _drop_index(self,s):
        table=s.table
        if table:self._snapshot(self.catalog.get_table(table))
        ok=self.catalog.drop_index(s.name,table=s.table,if_exists=s.if_exists);self._touch();return QueryResult.ok("DROP INDEX",affected_rows=int(ok),rows=[{"indice":s.name,"eliminado":ok}])
    # ---------- POINT VARIABLES ----------
    def _set_point(self,s):
        self.named_points[s.name.lower()]=tuple(s.point)
        return QueryResult.ok(
            "SET POINT",
            columns=["name","lat","lon"],
            rows=[{"name":s.name.lower(),"lat":s.point[0],"lon":s.point[1]}],
            affected_rows=1,
            execution_plan={"table":None,"planner_type":"session","access_path":"SET_POINT","used_indexes":[],"steps":[],"runtime_steps":[]},
        )
    def _resolve_named_points(self,q):
        exprs=[]
        for p in getattr(q,"predicates",()):
            if getattr(p,"distance",None) is not None:exprs.append(p.distance)
        for group in getattr(q,"or_groups",()):
            for p in group:
                if getattr(p,"distance",None) is not None:exprs.append(p.distance)
        for o in getattr(q,"order_by",()):
            if getattr(o,"distance",None) is not None:exprs.append(o.distance)
        for expr in exprs:
            name=getattr(expr,"point_name",None)
            if name:
                if name not in self.named_points:
                    raise QueryExecutionError(
                        f"punto nombrado '{name}' no definido; usa SET {name} = POINT(lat, lon)"
                    )
                object.__setattr__(expr,"point",tuple(self.named_points[name]))

    # ---------- TRANSACTION ----------
    def _transaction(self,s):
        if s.action=="begin":
            if self._txn:raise QueryExecutionError("ya hay una transacción activa")
            self._txn=TransactionState(f"T{next(self._txcounter)}");return QueryResult.ok("BEGIN TRANSACTION",rows=[{"transaction":self._txn.id,"estado":"activa"}],execution_plan={"table":None,"planner_type":"transaction","access_path":"BEGIN_TRANSACTION","used_indexes":[],"steps":[],"runtime_steps":[]})
        if not self._txn:raise QueryExecutionError("no hay una transacción activa")
        tx=self._txn
        if s.action=="commit":self.lock_manager.release_all(tx.id);self._txn=None;return QueryResult.ok("END TRANSACTION",rows=[{"transaction":tx.id,"estado":"confirmada (COMMIT)"}])
        # rollback: restore snapshots and delete tables created in txn
        for name in reversed(tx.created_tables):
            if self.catalog.has_table(name):self.catalog.drop_table(name)
        for name,snap in tx.snapshots.items():
            if self.catalog.has_table(name):
                t=self.catalog.get_table(name);t.storage.replace_all(snap["rows"]);self.catalog.rebuild_indexes(name)
        self.lock_manager.release_all(tx.id);self._txn=None;return QueryResult.ok("ROLLBACK",rows=[{"transaction":tx.id,"estado":"revertida (ROLLBACK)"}])
    def _snapshot(self,t):
        if not self._txn:return
        tx=self._txn
        if t.name not in tx.locked_tables:self.lock_manager.acquire_exclusive(tx.id,t.name);tx.locked_tables.append(t.name)
        if t.name not in tx.snapshots:tx.snapshots[t.name]={"rows":[dict(r) for _,r in t.storage.scan()]}
    def _touch(self):
        if self._txn:self._txn.statements+=1
    # ---------- EXPLAIN ----------
    def _explain(self,s):
        inner=s.statement
        if isinstance(inner,SelectStatement):
            q=inner.query_spec;self._resolve_named_points(q);t=self.catalog.get_table(q.table);kind=spatial_kind(q)
            if kind and self.catalog.spatial_index_for(t.name,(find_spatial_order_by(q).distance.column if kind=="knn" else (find_polygon_predicate(q).column if kind=="polygon" else find_distance_predicate(q).distance.column))):
                op={"range":"RTREE_RANGE_SCAN","knn":"RTREE_KNN","polygon":"RTREE_POLYGON"}[kind];reg=self.catalog.spatial_index_for(t.name,(find_spatial_order_by(q).distance.column if kind=="knn" else (find_polygon_predicate(q).column if kind=="polygon" else find_distance_predicate(q).distance.column)));payload={"table":t.name,"planner_type":"spatial_rtree","access_path":op,"used_indexes":[reg.metadata.name],"steps":[{"operator":op,"table":t.name,"index":reg.metadata.name,"reason":"consulta espacial con R-Tree","details":{}}],"runtime_steps":[]}
            else:payload=self._planner().plan(q).to_dict();payload["runtime_steps"]=[]
            if s.analyze:
                ex=self._select(inner);payload=ex.execution_plan or payload;payload["analyze"]={"rows":len(ex.rows),"execution_time_ms":ex.execution_time_ms}
        else:payload={"table":getattr(inner,"table",None),"planner_type":"direct_write","access_path":self._name(inner).replace(" ","_"),"used_indexes":[],"steps":[],"runtime_steps":[]}
        text=f"Tabla: {payload.get('table')}\nRuta de acceso: {payload.get('access_path')}\nÍndices: {', '.join(payload.get('used_indexes') or []) or '-'}"
        return QueryResult.ok("EXPLAIN",columns=["plan"],rows=[{"plan":text}],execution_plan=payload)
    # ---------- access/index ----------
    def _access(self,t,plan):
        step=plan.steps[0];op=step.operator
        if op in {"HEAP_SCAN","SEQUENTIAL_SCAN"}:return [dict(r) for _,r in t.storage.scan()]
        reg=self.catalog.get_index(t.name,step.index);idx=reg.implementation;raw=step.details.get("predicate");p=Predicate(raw["column"],raw["operator"],raw["value"]) if raw else None
        if op in {"HASH_INDEX_UNION","BPLUS_INDEX_UNION"}:
            preds=[p]+[Predicate(x["column"],x["operator"],x["value"]) for x in step.details.get("predicates_extra",[])];rids=[]
            for x in preds:rids.extend(idx.search(x.value))
            return self._materialize(t,self._unique(rids))
        if op=="HASH_INDEX_LOOKUP":return self._materialize(t,idx.search(p.value))
        if "LOOKUP" in op:return self._materialize(t,idx.search(p.value))
        if "RANGE_SCAN" in op:
            lo,hi,ilo,ihi=self._bounds(p);return self._materialize(t,idx.range_search(lo,hi,ilo,ihi))
        if "INDEX_SCAN" in op:return self._materialize(t,idx.scan())
        raise QueryExecutionError(f"unsupported access path {op}")
    @staticmethod
    def _unique(xs):
        seen=set();out=[]
        for x in xs:
            k=repr(x)
            if k not in seen:seen.add(k);out.append(x)
        return out
    def _materialize(self,t,rids):
        out=[]
        for rid in rids:
            r=t.read_rid(rid)
            if r is not None:out.append(dict(r))
        return out
    @staticmethod
    def _index_insert(t,row,rid):
        done=[]
        try:
            for r in t.indexes.values():
                k=r.metadata.kind;i=r.implementation
                if k in {"bplus_clustered","bplus_unclustered"}:i.insert(row,rid)
                elif k=="hash":i.insert(row[r.metadata.column],rid)
                elif k=="rtree":i.insert(row,rid)
                done.append(r)
        except Exception:
            for r in reversed(done):
                try:
                    if r.metadata.kind in {"bplus_clustered","bplus_unclustered"}:r.implementation.delete_record(row,rid)
                    elif r.metadata.kind=="hash":r.implementation.delete(row[r.metadata.column],rid)
                    elif r.metadata.kind=="rtree":r.implementation.delete(rid)
                except Exception:pass
            raise
    @staticmethod
    def _index_delete(t,row,rid):
        for r in t.indexes.values():
            if r.metadata.kind in {"bplus_clustered","bplus_unclustered"}:r.implementation.delete_record(row,rid)
            elif r.metadata.kind=="hash":r.implementation.delete(row[r.metadata.column],rid)
            elif r.metadata.kind=="rtree":r.implementation.delete(rid)
    # ---------- evaluators/operators ----------
    @classmethod
    def matches_all(cls,row,preds):return all(cls.evaluate_predicate(row,p) for p in preds)
    @classmethod
    def matches_query(cls,row,q):return any(cls.matches_all(row,g) for g in q.or_groups) if getattr(q,"or_groups",()) else cls.matches_all(row,getattr(q,"predicates",()))
    @staticmethod
    def evaluate_predicate(row,p):
        if getattr(p,"is_spatial",False):return True
        if p.column not in row:raise QueryExecutionError(f"unknown column {p.column}")
        a=row[p.column];b=p.value;op=p.normalized_operator()
        return {"=":lambda:a==b,"==":lambda:a==b,"!=":lambda:a!=b,"<>":lambda:a!=b,"<":lambda:a<b,"<=":lambda:a<=b,">":lambda:a>b,">=":lambda:a>=b,"between":lambda:b[0]<=a<=b[1]}[op]()
    def _sort(self,rows,order,runtime):
        current=list(rows);st=time.perf_counter()
        for o in reversed(order):current=self.external_sort.sort(current,key=lambda r,c=o.column:r[c],descending=o.descending)
        self._runtime(runtime,"EXTERNAL_SORT",st,rows_in=len(rows),rows_out=len(current));return current
    def _joins(self,rows,joins,runtime):
        cur=list(rows)
        for j in joins:
            rt=self.catalog.get_table(j.table);right=[dict(r) for _,r in rt.storage.scan()];st=time.perf_counter();cur=self.external_hashing.hash_join(cur,right,left_key=j.left_column,right_key=j.right_column,join_type=j.join_type,merge=lambda l,r:self._merge(l,r,rt.name));self._runtime(runtime,"EXTERNAL_HASH_JOIN",st,rows_out=len(cur),table=rt.name)
        return cur
    @staticmethod
    def _merge(l,r,name):
        d=dict(l or {})
        for k,v in (r or {}).items():d[k if k not in d else f"{name}.{k}"]=v
        return d
    def _aggregates(self,columns):
        out={}
        for x in columns:
            m=_AGG.match(x)
            if m:
                op,col,alias=m.groups();name=alias or f"{op.lower()}_{'all' if col=='*' else col}";out[name]="count" if op.upper()=="COUNT" and col=="*" else (op.lower(),col)
        return out
    @staticmethod
    def _aggregate_all(rows,aggs):
        rows=list(rows);out={}
        for name,spec in aggs.items():
            if spec=="count":out[name]=len(rows);continue
            op,col=spec;vals=[r[col] for r in rows if r.get(col) is not None]
            out[name]=len(vals) if op=="count" else sum(vals) if op=="sum" else (sum(vals)/len(vals) if vals else None) if op=="avg" else (min(vals) if vals else None) if op=="min" else (max(vals) if vals else None)
        return out
    def _project(self,rows,columns):
        if columns==("*",):return [dict(r) for r in rows],(list(rows[0].keys()) if rows else [])
        agg=self._aggregates(columns);names=[];out=[]
        for x in columns:
            m=_AGG.match(x);names.append((m.group(3) or f"{m.group(1).lower()}_{'all' if m.group(2)=='*' else m.group(2)}") if m else x.split('.')[-1])
        for r in rows:out.append({n:r.get(n) for n in names})
        return out,names
    # ---------- validation/helpers ----------
    def _validate_select(self,s,t):
        known=set(t.schema.col_names())|{"_distance","_lat","_lon"};q=s.query_spec
        for p in q.predicates:
            if p.column not in known and not getattr(p,"is_spatial",False):raise QueryExecutionError(f"unknown column '{p.column}'")
        for c in q.group_by:
            if c not in known:raise QueryExecutionError(f"unknown GROUP BY '{c}'")
    def _planner(self):return QueryPlanner(self.catalog.planner_indexes(),self.catalog.planner_storage())
    @staticmethod
    def _bounds(p):
        op=p.normalized_operator();v=p.value
        if op=="between":return v[0],v[1],True,True
        if op==">":return v,None,False,True
        if op==">=":return v,None,True,True
        if op=="<":return None,v,True,False
        if op=="<=":return None,v,True,True
        raise QueryExecutionError("not range")
    @staticmethod
    def _name(s):
        return {SelectStatement:"SELECT",InsertStatement:"INSERT",DeleteStatement:"DELETE",UpdateStatement:"UPDATE",CreateTableStatement:"CREATE TABLE",DropTableStatement:"DROP TABLE",CreateIndexStatement:"CREATE INDEX",DropIndexStatement:"DROP INDEX",ExplainStatement:"EXPLAIN",TransactionStatement:"TRANSACTION"}.get(type(s),type(s).__name__.upper())
    @staticmethod
    def _ms(st):return round((time.perf_counter()-st)*1000,6)
    @staticmethod
    def _runtime(a,op,st,**d):a.append({"operator":op,"elapsed_ms":QueryExecutor._ms(st),**d})
    def _direct_plan(self,t,op,indexes,st):return {"table":t.name,"planner_type":"direct_write","access_path":op,"used_indexes":indexes,"steps":[{"operator":op,"table":t.name,"index":None,"reason":"escritura directa","details":{}}],"runtime_steps":[{"operator":op,"elapsed_ms":self._ms(st)}]}
