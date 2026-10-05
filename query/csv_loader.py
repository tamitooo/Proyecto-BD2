from __future__ import annotations
import csv,io
from dataclasses import dataclass,field
@dataclass
class CsvImportReport:
    table:str;columns:list;rows_read:int=0;inserted:int=0;failed:int=0;errors:list=field(default_factory=list)
    @property
    def success(self):return self.failed==0
    def to_dict(self):return self.__dict__|{"success":self.success}
class CsvImportError(Exception):pass

def infer_schema_from_csv(text,*,primary_key=None,delimiter=",",has_header=True):
    rows=[r for r in csv.reader(io.StringIO(text),delimiter=delimiter) if r and any(x.strip() for x in r)]
    if len(rows)<2:raise CsvImportError("el CSV está vacío o no tiene datos")
    header=[x.strip().lower() for x in rows[0]] if has_header else [f"columna_{i+1}" for i in range(len(rows[0]))];data=rows[1:] if has_header else rows
    out=[]
    for i,name in enumerate(header):
        vals=[r[i].strip() for r in data if i<len(r) and r[i].strip()]
        try:
            for v in vals:int(v)
            typ="INT"
        except ValueError:
            try:
                for v in vals:float(v)
                typ="FLOAT"
            except ValueError:typ=f"VARCHAR({max([len(v) for v in vals] or [1])})"
        out.append((name,typ))
    if primary_key and primary_key.lower() not in [n for n,_ in out]:raise CsvImportError(f"primary key '{primary_key}' no está en CSV")
    return out

def _coerce(v,typ):
    v=v.strip()
    if typ=="INT":return int(float(v)) if v else 0
    if typ=="FLOAT":return float(v) if v else 0.0
    return v

def import_csv(executor,table_name,source,*,has_header=True,delimiter=",",encoding="utf-8",max_errors=10,**_):
    text=source.read() if hasattr(source,"read") else str(source);text=text.decode(encoding) if isinstance(text,bytes) else text
    t=executor.catalog.get_table(table_name);cols=t.schema.col_names();rows=[r for r in csv.reader(io.StringIO(text),delimiter=delimiter) if r and any(x.strip() for x in r)];rep=CsvImportReport(t.name,list(cols))
    if not rows:raise CsvImportError("CSV vacío")
    if has_header:
        h=[x.strip().lower() for x in rows[0]]
        if not all(c.lower() in h for c in cols):raise CsvImportError(f"encabezado debe incluir: {', '.join(cols)}")
        pos=[h.index(c.lower()) for c in cols];data=rows[1:]
    else:pos=list(range(len(cols)));data=rows
    types={f.name:f.kind if f.kind!="VARCHAR" else f.kind for f in t.schema.fields}
    rep.rows_read=len(data)
    for i,r in enumerate(data,2):
        try:
            vals=[]
            for p,c in zip(pos,cols):vals.append(_coerce(r[p],types[c]))
            q=executor.execute(__import__('query.sql_parser',fromlist=['InsertStatement']).InsertStatement(t.name,tuple(vals)))
            if not q.success:raise CsvImportError(q.error)
            rep.inserted+=1
        except Exception as e:
            rep.failed+=1
            if len(rep.errors)<max_errors:rep.errors.append(f"fila {i}: {e}")
    return rep
