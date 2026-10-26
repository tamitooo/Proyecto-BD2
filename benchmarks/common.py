from __future__ import annotations
import csv, json, sys
from dataclasses import asdict, is_dataclass
from pathlib import Path


def deep_size(obj):
    """Approximate deep size iteratively (safe for linked/cyclic trees)."""
    import types
    seen=set(); total=0; stack=[obj]
    atomic=(str,bytes,bytearray,int,float,bool,type(None),complex)
    while stack:
        current=stack.pop(); oid=id(current)
        if oid in seen: continue
        seen.add(oid)
        try: total += sys.getsizeof(current)
        except TypeError: pass
        if isinstance(current,atomic): continue
        if isinstance(current,(types.FunctionType,types.BuiltinFunctionType,types.MethodType,type,types.ModuleType)): continue
        if isinstance(current,dict):
            stack.extend(current.keys()); stack.extend(current.values()); continue
        if isinstance(current,(list,tuple,set,frozenset)):
            stack.extend(current); continue
        if hasattr(current,'__dict__'):
            stack.append(vars(current)); continue
        slots=getattr(type(current),'__slots__',())
        if isinstance(slots,str): slots=(slots,)
        for slot in slots:
            if hasattr(current,slot): stack.append(getattr(current,slot))
    return total


def write_rows(rows, csv_path, json_path, meta=None):
    csv_path=Path(csv_path);json_path=Path(json_path);csv_path.parent.mkdir(parents=True,exist_ok=True)
    normalized=[]
    for row in rows:
        if is_dataclass(row): row=asdict(row)
        normalized.append(dict(row))
    fields=[]
    for row in normalized:
        for k in row:
            if k not in fields:fields.append(k)
    with csv_path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(normalized)
    json_path.write_text(json.dumps({'meta':meta or {},'results':normalized},ensure_ascii=False,indent=2),encoding='utf-8')
