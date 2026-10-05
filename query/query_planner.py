from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple, Union

EQUALITY_OPERATORS={"=","=="}; RANGE_OPERATORS={"<","<=",">",">=","between"}; SUPPORTED_PREDICATE_OPERATORS=EQUALITY_OPERATORS|RANGE_OPERATORS|{"!=","<>"}

@dataclass(frozen=True)
class DistanceExpression:
    column:str; point:Tuple[float,float]; metric:str="haversine"
    @property
    def lat(self): return self.point[0]
    @property
    def lon(self): return self.point[1]
@dataclass(frozen=True)
class Predicate:
    column:str; operator:str; value:Any; distance:Optional[DistanceExpression]=None
    @property
    def is_spatial(self): return self.distance is not None
    def normalized_operator(self): return self.operator.strip().lower()
@dataclass(frozen=True)
class PolygonPredicate:
    column:str; ring:Tuple[Tuple[float,float],...]
    @property
    def is_spatial(self): return True
    @property
    def operator(self): return "dentro_de"
    @property
    def value(self): return self.ring
    @property
    def distance(self): return None
@dataclass(frozen=True)
class OrderBy:
    column:str; descending:bool=False; distance:Optional[DistanceExpression]=None
    @property
    def is_spatial(self): return self.distance is not None
@dataclass(frozen=True)
class JoinSpec:
    table:str; left_column:str; right_column:str; join_type:str="inner"; operator:str="="
@dataclass(frozen=True)
class QuerySpec:
    table:str; predicates:Tuple[Predicate,...]=(); order_by:Tuple[OrderBy,...]=(); group_by:Tuple[str,...]=(); joins:Tuple[JoinSpec,...]=(); or_groups:Tuple[Tuple[Predicate,...],...]=()
    @property
    def has_disjunction(self): return bool(self.or_groups)
@dataclass(frozen=True)
class IndexMetadata:
    name:str; table:str; column:str; kind:str; unique:bool=False
    def __post_init__(self):
        if self.kind not in {"hash","bplus_clustered","bplus_unclustered","rtree"}: raise ValueError(f"unsupported index kind: {self.kind}")
@dataclass
class PlanStep:
    operator:str; table:Optional[str]=None; index:Optional[str]=None; reason:str=""; details:Dict[str,Any]=field(default_factory=dict)
    def to_dict(self): return {"operator":self.operator,"table":self.table,"index":self.index,"reason":self.reason,"details":dict(self.details)}
@dataclass
class QueryPlan:
    table:str; steps:List[PlanStep]; access_path:str; used_indexes:List[str]=field(default_factory=list); planner_type:str="rule_based"
    def to_dict(self): return {"table":self.table,"planner_type":self.planner_type,"access_path":self.access_path,"used_indexes":list(self.used_indexes),"steps":[s.to_dict() for s in self.steps]}
    def explain(self):
        lines=[f"Planner: {self.planner_type}",f"Table: {self.table}",f"Access path: {self.access_path}"]
        for i,s in enumerate(self.steps,1):
            line=f"{i}. {s.operator}"+(f" [{s.table}]" if s.table else "")+(f" using {s.index}" if s.index else "")+(f" - {s.reason}" if s.reason else "")
            lines.append(line)
        return "\n".join(lines)
@dataclass(frozen=True)
class _AccessCandidate:
    index:IndexMetadata; predicate:Optional[Predicate]; score:int; operator:str; preserves_order:bool; reason:str; extra_predicates:Tuple[Predicate,...]=(); from_disjunction:bool=False

def replace_candidate(c,**kw):
    return _AccessCandidate(kw.get("index",c.index),kw.get("predicate",c.predicate),kw.get("score",c.score),kw.get("operator",c.operator),kw.get("preserves_order",c.preserves_order),kw.get("reason",c.reason),kw.get("extra_predicates",c.extra_predicates),kw.get("from_disjunction",c.from_disjunction))

class QueryPlanner:
    def __init__(self,indexes=None,storage_by_table=None): self.indexes=list(indexes or []); self.storage_by_table=dict(storage_by_table or {})
    def register_index(self,index): self.indexes.append(index)
    def register_storage(self,table,storage_kind): self.storage_by_table[table]=storage_kind.lower()
    def plan(self,query):
        query=self._coerce_query(query); self._validate_query(query); steps=[]; used=[]; c=self._choose_access_candidate(query)
        if c is None:
            access=self._fallback_scan(query.table); path=access.operator; preserves=False; consumed=(); from_or=False
        else:
            access=PlanStep(c.operator,query.table,c.index.name,c.reason,self._access_details(c)); path=c.operator; preserves=c.preserves_order; consumed=((c.predicate,) if c.predicate else ())+c.extra_predicates; from_or=c.from_disjunction; used=[c.index.name]
        steps.append(access)
        residual=self._residual_predicates(query.predicates,consumed)
        if query.or_groups and not from_or: residual=list(query.predicates)
        if residual:
            steps.append(PlanStep("FILTER",query.table,reason="unión de índices: el filtro confirma los grupos del OR" if from_or else "predicados no resueltos por el camino de acceso",details={"predicates":[self._predicate_to_dict(p) for p in residual]}))
        for j in query.joins:
            op="EXTERNAL_HASH_JOIN" if j.operator.strip().lower() in EQUALITY_OPERATORS else "NESTED_LOOP_JOIN"
            steps.append(PlanStep(op,j.table,reason="equi-join: Grace Hash Join" if op.startswith("EXTERNAL") else "hash join solo aplica a igualdad",details={"join_type":j.join_type.lower(),"left_column":j.left_column,"right_column":j.right_column,"operator":j.operator})); preserves=False
        if query.group_by:
            steps.append(PlanStep("EXTERNAL_HASH_GROUP_BY",query.table,reason="GROUP BY con particionado hash externo",details={"columns":list(query.group_by)})); preserves=False
        if query.order_by and not self._order_is_covered(query,c,preserves):
            steps.append(PlanStep("EXTERNAL_SORT",query.table,reason="el camino de acceso no garantiza el ORDER BY",details={"columns":[{"column":o.column,"direction":"DESC" if o.descending else "ASC"} for o in query.order_by]}))
        return QueryPlan(query.table,steps,path,used)
    def _choose_access_candidate(self,q):
        idx=[i for i in self.indexes if i.table==q.table]; cs=[]
        if not q.has_disjunction:
            for i in idx:
                c=self._candidate_for_index(q,i)
                if c: cs.append(c)
        else:
            c=self._candidate_for_disjunction(q,idx)
            if c: cs.append(c)
        if q.order_by and not q.predicates and not q.has_disjunction:
            first=q.order_by[0] if not q.order_by[0].descending else None
            for i in idx:
                if first is None or i.column!=first.column: continue
                if i.kind=="bplus_clustered": cs.append(_AccessCandidate(i,None,70,"BPLUS_CLUSTERED_INDEX_SCAN",True,"B+ clustered evita sort inicial"))
                elif i.kind=="bplus_unclustered": cs.append(_AccessCandidate(i,None,60,"BPLUS_UNCLUSTERED_INDEX_SCAN",True,"B+ unclustered entrega RIDs ordenados"))
        if not cs:return None
        pri={"hash":3,"bplus_clustered":2,"bplus_unclustered":1,"rtree":0}
        return max(cs,key=lambda c:(c.score,pri.get(c.index.kind,0)))
    def _candidate_for_index(self,q,i):
        match=[p for p in q.predicates if p.column==i.column and not getattr(p,"is_spatial",False)]
        eq=[p for p in match if p.normalized_operator() in EQUALITY_OPERATORS]
        if eq:return self._candidate_for_predicate(q,i,eq[0],eq[0].normalized_operator())
        ranges=[p for p in match if p.normalized_operator() in RANGE_OPERATORS]
        if not ranges:return None
        if len(ranges)==1:return self._candidate_for_predicate(q,i,ranges[0],ranges[0].normalized_operator())
        bounds=self._combined_range(ranges)
        if bounds is None:return self._candidate_for_predicate(q,i,ranges[0],ranges[0].normalized_operator())
        low,high,il,ih=bounds; anchor=next((p for p in ranges if (low is not None and self._is_lower_bound(p)) or (low is None and self._is_upper_bound(p))),ranges[0]); combined=Predicate(i.column,"between",(low,high)); c=self._candidate_for_predicate(q,i,combined,"between")
        if not c:return None
        return replace_candidate(c,predicate=anchor,extra_predicates=tuple(p for p in ranges if p is not anchor),reason=f"B+ {i.kind.split('_')[-1]} combina los dos extremos del rango")
    @staticmethod
    def _is_lower_bound(p): return p.normalized_operator() in {">",">=","between"}
    @staticmethod
    def _is_upper_bound(p): return p.normalized_operator() in {"<","<=","between"}
    @classmethod
    def _combined_range(cls,ps):
        low=high=None; il=ih=True
        for p in ps:
            op=p.normalized_operator(); v=p.value
            if op=="between":
                a,b=v
                if low is None or a>low:low,il=a,True
                if high is None or b<high:high,ih=b,True
            elif op in {">",">="}:
                if low is None or v>low:low,il=v,op==">="
                elif v==low and op==">":il=False
            elif op in {"<","<="}:
                if high is None or v<high:high,ih=v,op=="<="
                elif v==high and op=="<":ih=False
            else:return None
        return low,high,il,ih
    def _candidate_for_disjunction(self,q,indexes):
        groups=q.or_groups
        if not groups:return None
        for i in indexes:
            if not all(all(p.column==i.column and p.normalized_operator() in EQUALITY_OPERATORS for p in g) for g in groups):continue
            members=tuple(p for g in groups for p in g); op="HASH_INDEX_UNION" if i.kind=="hash" else "BPLUS_INDEX_UNION"
            if i.kind not in {"hash","bplus_clustered","bplus_unclustered"}:continue
            return _AccessCandidate(i,members[0],100,op,False,f"WHERE con OR: unión de {len(members)} búsquedas por '{i.column}'",members[1:],True)
        return None
    def _candidate_for_predicate(self,q,i,p,op):
        bonus=self._order_bonus(q,i)
        if op in EQUALITY_OPERATORS:
            if i.kind=="hash":return _AccessCandidate(i,p,110,"HASH_INDEX_LOOKUP",False,"Extendible Hashing es preferido para igualdad exacta")
            if i.kind=="bplus_clustered":return _AccessCandidate(i,p,90+bonus,"BPLUS_CLUSTERED_LOOKUP",True,"B+ clustered soporta lookup directo")
            if i.kind=="bplus_unclustered":return _AccessCandidate(i,p,80+bonus,"BPLUS_UNCLUSTERED_LOOKUP",True,"B+ unclustered soporta lookup mediante RIDs")
        if op in RANGE_OPERATORS:
            if i.kind=="bplus_clustered":return _AccessCandidate(i,p,95+bonus,"BPLUS_CLUSTERED_RANGE_SCAN",True,"B+ clustered soporta range scan ordenado")
            if i.kind=="bplus_unclustered":return _AccessCandidate(i,p,85+bonus,"BPLUS_UNCLUSTERED_RANGE_SCAN",True,"B+ unclustered soporta range scan")
        return None
    @staticmethod
    def _order_bonus(q,i): return 15 if q.order_by and not q.order_by[0].descending and q.order_by[0].column==i.column and i.kind.startswith("bplus") else 0
    @staticmethod
    def _order_is_covered(q,c,preserves):
        if not q.order_by:return True
        if c is None or len(q.order_by)!=1:return False
        o=q.order_by[0]
        if c.predicate and c.predicate.normalized_operator() in EQUALITY_OPERATORS and c.predicate.column==o.column:return True
        return preserves and not o.descending and c.index.kind.startswith("bplus") and c.index.column==o.column
    def _fallback_scan(self,t): return PlanStep("SEQUENTIAL_SCAN" if self.storage_by_table.get(t,"heap").lower()=="sequential" else "HEAP_SCAN",t,reason="no existe indice aplicable")
    @staticmethod
    def _residual_predicates(ps,consumed):
        rem=list(consumed or ()); out=[]
        for p in ps:
            for j,c in enumerate(rem):
                if p==c: rem.pop(j); break
            else: out.append(p)
        return out
    @staticmethod
    def _access_details(c):
        d={"index_kind":c.index.kind,"column":c.index.column,"unique":c.index.unique}
        if c.predicate:d["predicate"]=QueryPlanner._predicate_to_dict(c.predicate)
        if c.extra_predicates:d["predicates_extra"]=[QueryPlanner._predicate_to_dict(p) for p in c.extra_predicates]
        if c.from_disjunction:d.update({"disjunction":True,"searches":1+len(c.extra_predicates)})
        return d
    @staticmethod
    def _predicate_to_dict(p): return {"column":p.column,"operator":p.operator,"value":p.value}
    @staticmethod
    def _validate_query(q):
        if not q.table:raise ValueError("query.table is required")
        for p in q.predicates:
            if getattr(p,"is_spatial",False):continue
            op=p.normalized_operator()
            if op not in SUPPORTED_PREDICATE_OPERATORS:raise ValueError(f"unsupported predicate operator: {p.operator}")
    @classmethod
    def _coerce_query(cls,q):
        if isinstance(q,QuerySpec):return q
        if not isinstance(q,Mapping):raise TypeError("query must be QuerySpec or mapping")
        return QuerySpec(table=q.get("table",""),predicates=tuple(cls._coerce_predicate(x) for x in q.get("predicates",())),order_by=tuple(cls._coerce_order_by(x) for x in q.get("order_by",())),group_by=((q.get("group_by"),) if isinstance(q.get("group_by"),str) else tuple(q.get("group_by",()))),joins=tuple(cls._coerce_join(x) for x in q.get("joins",())))
    @staticmethod
    def _coerce_predicate(x):
        if isinstance(x,Predicate):return x
        if isinstance(x,Mapping):return Predicate(x["column"],x["operator"],x.get("value"))
        return Predicate(*x)
    @staticmethod
    def _coerce_order_by(x):
        if isinstance(x,OrderBy):return x
        if isinstance(x,str):return OrderBy(x)
        if isinstance(x,Mapping):return OrderBy(x["column"],bool(x.get("descending",False)))
        if len(x)==1:return OrderBy(x[0])
        return OrderBy(x[0],str(x[1]).lower()=="desc" if isinstance(x[1],str) else bool(x[1]))
    @staticmethod
    def _coerce_join(x):
        if isinstance(x,JoinSpec):return x
        return JoinSpec(x["table"],x["left_column"],x["right_column"],x.get("join_type","inner"),x.get("operator","="))
