from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple
from query.query_planner import DistanceExpression, JoinSpec, OrderBy, PolygonPredicate, Predicate, QuerySpec

_ID=r"[A-Za-z_][A-Za-z0-9_]*"; _QID=rf"{_ID}(?:\.{_ID})?"
@dataclass(frozen=True)
class InsertStatement: table:str; values:Tuple[Any,...]
@dataclass(frozen=True)
class DeleteStatement: table:str; predicates:Tuple[Predicate,...]; or_groups:Tuple[Tuple[Predicate,...],...]=()
@dataclass(frozen=True)
class UpdateStatement: table:str; assignments:Tuple[Tuple[str,Any],...]; predicates:Tuple[Predicate,...]=(); or_groups:Tuple[Tuple[Predicate,...],...]=()
@dataclass(frozen=True)
class CreateTableStatement: table:str; columns:Tuple[Tuple[str,str],...]; primary_key:str; storage_kind:str="heap"; if_not_exists:bool=False
@dataclass(frozen=True)
class DropTableStatement: table:str; if_exists:bool=False
@dataclass(frozen=True)
class CreateIndexStatement: table:str; column:str; name:Optional[str]=None; unique:bool=False; kind:str="bplus_unclustered"; if_not_exists:bool=False; column2:Optional[str]=None
@dataclass(frozen=True)
class DropIndexStatement: name:str; table:Optional[str]=None; if_exists:bool=False
@dataclass(frozen=True)
class TransactionStatement: action:str
@dataclass(frozen=True)
class ExplainStatement: statement:Any; analyze:bool=False
@dataclass(frozen=True)
class SetPointStatement: name:str; point:Tuple[float,float]
@dataclass(frozen=True)
class SelectStatement: columns:Tuple[str,...]; query_spec:QuerySpec; limit:Optional[int]=None
class SQLParseError(Exception): pass

def strip_sql_comments(sql):
    out=[]; i=0; quote=None
    while i<len(sql):
        ch=sql[i]
        if quote:
            out.append(ch)
            if ch==quote:
                if i+1<len(sql) and sql[i+1]==quote: out.append(sql[i+1]); i+=2; continue
                quote=None
            i+=1; continue
        if ch in "'\"": quote=ch; out.append(ch); i+=1; continue
        if sql.startswith("--",i):
            j=sql.find("\n",i); 
            if j<0: break
            out.append("\n"); i=j+1; continue
        if sql.startswith("/*",i):
            j=sql.find("*/",i+2)
            if j<0: raise SQLParseError("comentario /* sin cerrar con */")
            out.append(" "); i=j+2; continue
        out.append(ch); i+=1
    return "".join(out)

def split_sql_statements(sql):
    sql=strip_sql_comments(sql); out=[]; start=0; depth=0; quote=None; i=0
    while i<len(sql):
        c=sql[i]
        if quote:
            if c==quote:
                if i+1<len(sql) and sql[i+1]==quote:i+=2;continue
                quote=None
        elif c in "'\"": quote=c
        elif c=="(":depth+=1
        elif c==")":depth-=1
        elif c==";" and depth==0:
            if sql[start:i].strip():out.append(sql[start:i].strip())
            start=i+1
        i+=1
    if sql[start:].strip():out.append(sql[start:].strip())
    return out

class SQLParser:
    _KINDS={"HASH":"hash","EXTENDIBLE_HASH":"hash","BPLUS":"bplus_unclustered","BPLUS_UNCLUSTERED":"bplus_unclustered","UNCLUSTERED":"bplus_unclustered","BPLUS_CLUSTERED":"bplus_clustered","CLUSTERED":"bplus_clustered","RTREE":"rtree","R_TREE":"rtree","GIST":"rtree"}
    def parse(self,sql):
        if not isinstance(sql,str):raise SQLParseError("SQL statement must be a string")
        parts=split_sql_statements(sql.lstrip("\ufeff"));
        if not parts:raise SQLParseError("Empty SQL statement")
        s=parts[0].rstrip(";").strip(); first=s.split(None,1)[0].upper()
        if first=="SELECT":return self._select(s)
        if first=="INSERT":return self._insert(s)
        if first=="DELETE":return self._delete(s)
        if first=="UPDATE":return self._update(s)
        if first=="CREATE": return self._create_index(s) if re.match(r"CREATE\s+(?:UNIQUE\s+)?INDEX\b",s,re.I) else self._create_table(s)
        if first=="DROP": return self._drop_index(s) if re.match(r"DROP\s+INDEX\b",s,re.I) else self._drop_table(s)
        if first=="EXPLAIN":return self._explain(s)
        if first=="SET":return self._set_point(s)
        if first in {"BEGIN","START","END","COMMIT","ROLLBACK"}:return self._transaction(s)
        raise SQLParseError(f"Unsupported SQL command: {first}")
    @staticmethod
    def _scan_top(text,keywords):
        found=[]; depth=0; quote=None; i=0
        kws=sorted(keywords,key=len,reverse=True)
        while i<len(text):
            c=text[i]
            if quote:
                if c==quote:
                    if i+1<len(text) and text[i+1]==quote:i+=2;continue
                    quote=None
                i+=1;continue
            if c in "'\"":quote=c;i+=1;continue
            if c=="(":depth+=1;i+=1;continue
            if c==")":depth-=1;i+=1;continue
            if depth==0:
                for kw in kws:
                    if text[i:i+len(kw)].upper()==kw and (i==0 or not(text[i-1].isalnum() or text[i-1]=='_')) and (i+len(kw)==len(text) or not(text[i+len(kw)].isalnum() or text[i+len(kw)]=='_')):
                        found.append((i,i+len(kw),kw)); i+=len(kw); break
                else:i+=1
            else:i+=1
        return found
    @staticmethod
    def _split(text,sep=','):
        out=[];start=0;depth=0;quote=None;i=0
        while i<len(text):
            c=text[i]
            if quote:
                if c==quote:
                    if i+1<len(text) and text[i+1]==quote:i+=2;continue
                    quote=None
            elif c in "'\"":quote=c
            elif c=='(':depth+=1
            elif c==')':depth-=1
            elif c==sep and depth==0:out.append(text[start:i].strip());start=i+1
            i+=1
        out.append(text[start:].strip()); return [x for x in out if x]
    def _select(self,s):
        body=re.sub(r"^SELECT\s+","",s,flags=re.I); marks=self._scan_top(body,["FROM"])
        if not marks:raise SQLParseError("SELECT requires FROM")
        fs,fe,_=marks[0]; columns=tuple(self._split(body[:fs])); tail=body[fe:].strip(); m=re.match(rf"({_ID})\b",tail)
        if not m:raise SQLParseError("FROM requires table")
        table=m.group(1); rest=tail[m.end():]
        marks=self._scan_top(rest,["WHERE","GROUP BY","ORDER BY","LIMIT"]); marks.sort()
        join_text=rest[:marks[0][0]].strip() if marks else rest.strip(); clauses={}
        for n,(a,b,k) in enumerate(marks):clauses[k]=rest[b:(marks[n+1][0] if n+1<len(marks) else len(rest))].strip()
        joins=self._joins(join_text); groups=self._where_groups(clauses["WHERE"]) if "WHERE" in clauses else (); preds=tuple(p for g in groups for p in g)
        group=tuple(x.split('.')[-1] for x in self._split(clauses.get("GROUP BY",""))) if clauses.get("GROUP BY") else ()
        order=self._order(clauses.get("ORDER BY")); limit=int(clauses["LIMIT"]) if clauses.get("LIMIT") else None
        return SelectStatement(columns,QuerySpec(table,preds,order,group,joins,groups if len(groups)>1 else ()),limit)
    def _joins(self,text):
        out=[]; rem=text.strip()
        while rem:
            h=re.match(rf"\s*(?:(INNER|LEFT|RIGHT|FULL)\s+)?JOIN\s+({_ID})\s+ON\s+",rem,re.I)
            if not h:raise SQLParseError(f"Unsupported text after FROM: {rem}")
            jt=(h.group(1) or "inner").lower(); t=h.group(2); after=rem[h.end():]; markers=self._scan_top(after,["JOIN","INNER JOIN","LEFT JOIN","RIGHT JOIN","FULL JOIN"])
            cond=after[:markers[0][0]].strip() if markers else after.strip(); rem=after[markers[0][0]:].strip() if markers else ""
            m=re.fullmatch(rf"({_QID})\s*=\s*({_QID})",cond,re.I)
            if not m:raise SQLParseError("JOIN ON only supports equality")
            l,r=m.groups(); lc=l.split('.')[-1]; rc=r.split('.')[-1]
            if l.split('.')[0]==t and '.' in l:lc,rc=rc,lc
            out.append(JoinSpec(t,lc,rc,jt,"="))
        return tuple(out)
    def _order(self,raw):
        if not raw:return ()
        out=[]
        for item in self._split(raw):
            d=self._distance_expr(item)
            if d:
                expr,end=d; suffix=item[end:].strip().upper(); out.append(OrderBy(expr.column,suffix=="DESC",expr)); continue
            m=re.fullmatch(rf"({_QID})(?:\s+(ASC|DESC))?",item,re.I)
            if not m:raise SQLParseError(f"Invalid ORDER BY: {item}")
            out.append(OrderBy(m.group(1).split('.')[-1],(m.group(2) or "ASC").upper()=="DESC"))
        return tuple(out)
    def _insert(self,s):
        m=re.fullmatch(rf"INSERT\s+INTO\s+({_ID})\s+VALUES\s*\((.*)\)\s*",s,re.I|re.S)
        if not m:raise SQLParseError("Syntax error in INSERT")
        return InsertStatement(m.group(1),tuple(self._literal(x) for x in self._split(m.group(2))))
    def _delete(self,s):
        m=re.fullmatch(rf"DELETE\s+FROM\s+({_ID})(?:\s+WHERE\s+(.+))?",s,re.I|re.S)
        if not m:raise SQLParseError("Syntax error in DELETE")
        g=self._where_groups(m.group(2)) if m.group(2) else (); return DeleteStatement(m.group(1),tuple(p for x in g for p in x),g if len(g)>1 else ())
    def _update(self,s):
        m=re.match(rf"UPDATE\s+({_ID})\s+SET\s+",s,re.I)
        if not m:raise SQLParseError("Syntax error in UPDATE")
        rest=s[m.end():]; marks=self._scan_top(rest,["WHERE"]); assigns=rest[:marks[0][0]] if marks else rest; where=rest[marks[0][1]:] if marks else None
        a=[]
        for item in self._split(assigns):
            mm=re.fullmatch(rf"({_ID})\s*=\s*(.+)",item,re.S)
            if not mm:raise SQLParseError(f"Invalid assignment: {item}")
            a.append((mm.group(1),self._literal(mm.group(2))))
        g=self._where_groups(where) if where else (); return UpdateStatement(m.group(1),tuple(a),tuple(p for x in g for p in x),g if len(g)>1 else ())
    def _create_table(self,s):
        m=re.match(rf"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?({_ID})\s*\(",s,re.I)
        if not m:raise SQLParseError("CREATE TABLE syntax")
        openi=m.end()-1; close=self._match_paren(s,openi); body=s[openi+1:close]; tail=s[close+1:].strip(); kind="heap"
        if tail:
            u=re.fullmatch(r"USING\s+(HEAP|SEQUENTIAL)",tail,re.I)
            if not u:raise SQLParseError("usa USING HEAP o USING SEQUENTIAL")
            kind=u.group(1).lower()
        cols=[]; pk=None
        for item in self._split(body):
            pkm=re.fullmatch(rf"PRIMARY\s+KEY\s*\(\s*({_ID})\s*\)",item,re.I)
            if pkm:pk=pkm.group(1);continue
            dm=re.fullmatch(rf"({_ID})\s+([A-Za-z]+(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?)(.*)",item,re.I|re.S)
            if not dm:raise SQLParseError(f"Definición inválida: {item}")
            name=dm.group(1);typ=self._type(dm.group(2));cols.append((name,typ));
            if re.search(r"PRIMARY\s+KEY",dm.group(3),re.I):pk=name
        if not cols:raise SQLParseError("CREATE TABLE sin columnas")
        pk=pk or cols[0][0]
        return CreateTableStatement(m.group(2),tuple(cols),pk,kind,bool(m.group(1)))
    def _drop_table(self,s):
        m=re.fullmatch(rf"DROP\s+TABLE\s+(IF\s+EXISTS\s+)?({_ID})",s,re.I)
        if not m:raise SQLParseError("DROP TABLE syntax")
        return DropTableStatement(m.group(2),bool(m.group(1)))
    def _create_index(self,s):
        m=re.match(rf"CREATE\s+(?:(UNIQUE)\s+)?INDEX\s+(?:(IF\s+NOT\s+EXISTS)\s+)?(?:({_ID})\s+)?ON\s+({_ID})\s*",s,re.I)
        if not m:raise SQLParseError("CREATE INDEX syntax")
        rest=s[m.end():].strip(); close=self._match_paren(rest,0) if rest.startswith('(') else None
        if close is None:raise SQLParseError("CREATE INDEX requiere (columna)")
        cols=self._split(rest[1:close]); tail=rest[close+1:].strip(); kind="bplus_unclustered"
        if tail:
            u=re.fullmatch(r"USING\s+([A-Za-z_][A-Za-z0-9_]*)",tail,re.I)
            if not u or u.group(1).upper() not in self._KINDS:raise SQLParseError("técnica de índice desconocida")
            kind=self._KINDS[u.group(1).upper()]
        if kind=="rtree" and len(cols)!=2:raise SQLParseError("RTREE necesita (lat, lon)")
        if kind!="rtree" and len(cols)!=1:raise SQLParseError("índice no espacial usa una columna")
        return CreateIndexStatement(m.group(4),cols[0],m.group(3),bool(m.group(1)),kind,bool(m.group(2)),cols[1] if len(cols)>1 else None)
    def _drop_index(self,s):
        m=re.fullmatch(rf"DROP\s+INDEX\s+(IF\s+EXISTS\s+)?({_ID})(?:\s+ON\s+({_ID}))?",s,re.I)
        if not m:raise SQLParseError("DROP INDEX syntax")
        return DropIndexStatement(m.group(2),m.group(3),bool(m.group(1)))
    def _transaction(self,s):
        t=re.sub(r"\s+"," ",s.strip()).upper(); t=t.replace(" WORK","")
        if t in {"BEGIN","BEGIN TRANSACTION","START","START TRANSACTION"}:return TransactionStatement("begin")
        if t in {"END","END TRANSACTION","COMMIT","COMMIT TRANSACTION"}:return TransactionStatement("commit")
        if t in {"ROLLBACK","ROLLBACK TRANSACTION"}:return TransactionStatement("rollback")
        raise SQLParseError("sentencia de transacción no soportada")
    def _set_point(self,s):
        m=re.fullmatch(rf"SET\s+({_ID})\s*=\s*POINT\s*\(\s*([^,]+),\s*([^\)]+)\s*\)",s,re.I)
        if not m:raise SQLParseError("SET de punto usa: SET nombre = POINT(lat, lon)")
        return SetPointStatement(m.group(1), (float(self._literal(m.group(2))), float(self._literal(m.group(3)))))
    def _explain(self,s):
        m=re.match(r"EXPLAIN\s+(ANALYZE\s+)?",s,re.I); inner=s[m.end():].strip()
        if not inner:raise SQLParseError("EXPLAIN requiere sentencia")
        return ExplainStatement(self.parse(inner),bool(m.group(1)))
    def _where_groups(self,raw):
        if not raw:return ()
        marks=self._scan_top(raw,["OR"]); parts=[];start=0
        for a,b,_ in marks:parts.append(raw[start:a].strip());start=b
        parts.append(raw[start:].strip()); return tuple(tuple(self._where(p)) for p in parts)
    def _where(self,text):
        # split AND, but protect BETWEEN's AND by scanning sequentially
        out=[]; pos=0
        while pos<len(text):
            pos=self._ws(text,pos)
            poly=self._polygon(text,pos)
            if poly: out.append(poly[0]); pos=poly[1]; pos=self._consume_and(text,pos); continue
            dist=self._distance_expr(text[pos:])
            if dist:
                expr,end=dist; pos+=end; pos=self._ws(text,pos); om=re.match(r"(<=|<)",text[pos:])
                if not om:raise SQLParseError("distancia admite < o <=")
                op=om.group(1);pos+=om.end(); endand=self._next_kw(text,"AND",pos); raw=text[pos:endand[0] if endand else len(text)].strip(); out.append(Predicate(expr.column,op,float(self._literal(raw)),expr));pos=endand[1] if endand else len(text);continue
            cm=re.match(_QID,text[pos:])
            if not cm:raise SQLParseError(f"WHERE inválido cerca de {text[pos:]}")
            col=cm.group(0).split('.')[-1];pos+=cm.end();pos=self._ws(text,pos)
            bm=re.match(r"BETWEEN\b",text[pos:],re.I)
            if bm:
                pos+=bm.end(); aand=self._next_kw(text,"AND",pos)
                if not aand:raise SQLParseError("BETWEEN requiere AND")
                low=self._literal(text[pos:aand[0]].strip());pos=aand[1]; nxt=self._next_kw(text,"AND",pos);high=self._literal(text[pos:nxt[0] if nxt else len(text)].strip());pos=nxt[1] if nxt else len(text);out.append(Predicate(col,"between",(low,high)));continue
            om=re.match(r"(<=|>=|!=|<>|=|<|>)",text[pos:])
            if not om:raise SQLParseError("operador WHERE esperado")
            op=om.group(1);pos+=om.end(); nxt=self._next_kw(text,"AND",pos);raw=text[pos:nxt[0] if nxt else len(text)].strip();out.append(Predicate(col,op,self._literal(raw)));pos=nxt[1] if nxt else len(text)
        return out
    def _distance_expr(self,text):
        m=re.match(r"(?:DISTANCIA|DISTANCE)\s*\(",text,re.I)
        if not m:return None
        oi=text.find('(',0);ci=self._match_paren(text,oi);parts=self._split(text[oi+1:ci]);
        if len(parts)<2:raise SQLParseError("distancia necesita columna, POINT")
        point_token=parts[1].strip()
        pm=re.fullmatch(r"POINT\s*\(\s*([^,]+),\s*([^\)]+)\s*\)",point_token,re.I)
        if pm:
            point=(float(self._literal(pm.group(1))),float(self._literal(pm.group(2))))
        elif re.fullmatch(_ID,point_token):
            # El ejecutor resuelve el punto nombrado (p.ej. mi_ubicacion).
            point=(float("nan"),float("nan"))
        else:raise SQLParseError("POINT inválido; usa POINT(lat, lon) o un punto nombrado")
        metric="haversine"
        if len(parts)>=3:
            mm=parts[2].strip(" '\"").lower(); metric="euclidean" if mm in {"euclidean","euclidiana"} else "haversine" if mm in {"haversine","geodesic","geodesica","geodésica"} else None
            if metric is None:raise SQLParseError("métrica desconocida")
        expr=DistanceExpression(parts[0].strip().split('.')[-1],point,metric)
        # Atributo dinámico inmutable no es posible en frozen dataclass; el nombre
        # se transporta en una marca privada usando object.__setattr__.
        if not pm: object.__setattr__(expr,"point_name",point_token.lower())
        return expr,ci+1
    def _polygon(self,text,pos):
        m=re.match(r"(?:DENTRO_DE|WITHIN|DENTRO)\s*\(",text[pos:],re.I)
        if not m:return None
        oi=pos+text[pos:].find('(');ci=self._match_paren(text,oi);body=text[oi+1:ci];parts=self._split(body)
        col=parts[0].strip().split('.')[-1]; raw=','.join(parts[1:]);pm=re.search(r"POLYGON\s*\(\s*\((.*?)\)\s*\)",raw,re.I|re.S)
        if not pm:raise SQLParseError("POLYGON inválido")
        ring=[]
        for pair in pm.group(1).split(','):
            xy=pair.split();
            if len(xy)!=2:raise SQLParseError("vértice inválido")
            ring.append((float(self._literal(xy[0])),float(self._literal(xy[1]))))
        if len(ring)<3:raise SQLParseError("polígono necesita 3 vértices")
        return PolygonPredicate(col,tuple(ring)),ci+1
    @staticmethod
    def _ws(t,p):
        while p<len(t) and t[p].isspace():p+=1
        return p
    def _next_kw(self,t,kw,p):
        arr=self._scan_top(t[p:],[kw]); return (p+arr[0][0],p+arr[0][1]) if arr else None
    def _consume_and(self,t,p):
        p=self._ws(t,p);m=re.match(r"AND\b",t[p:],re.I);return p+m.end() if m else p
    @staticmethod
    def _match_paren(t,oi):
        if oi is None or oi>=len(t) or t[oi]!='(':return None
        d=0;q=None;i=oi
        while i<len(t):
            c=t[i]
            if q:
                if c==q:
                    if i+1<len(t) and t[i+1]==q:i+=2;continue
                    q=None
            elif c in "'\"":q=c
            elif c=='(':d+=1
            elif c==')':
                d-=1
                if d==0:return i
            i+=1
        return None
    @staticmethod
    def _literal(x):
        x=x.strip()
        if len(x)>=2 and x[0]==x[-1] and x[0] in "'\"":return x[1:-1].replace(x[0]*2,x[0])
        u=x.upper()
        if u=="NULL":return None
        if u=="TRUE":return True
        if u=="FALSE":return False
        if re.fullmatch(r"[+-]?\d+",x):return int(x)
        if re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?",x):return float(x)
        return x
    @staticmethod
    def _type(raw):
        c=re.sub(r"\s+","",raw.upper())
        m=re.fullmatch(r"(?:VARCHAR|CHAR|CHARACTER)\((\d+)\)",c)
        if m:return f"VARCHAR({int(m.group(1))})"
        if c in {"INT","INTEGER","SMALLINT","BIGINT","SERIAL"}:return "INT"
        if c in {"FLOAT","REAL","DOUBLE","DOUBLEPRECISION","DECIMAL","NUMERIC"} or re.fullmatch(r"(?:DECIMAL|NUMERIC)\(\d+(?:,\d+)?\)",c):return "FLOAT"
        if c in {"TEXT","STRING","CLOB","VARCHAR","CHAR","CHARACTER"}:return "VARCHAR(255)"
        raise SQLParseError(f"Tipo no soportado: {raw}")
