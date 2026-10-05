from __future__ import annotations
import os
from dataclasses import dataclass,field
from pathlib import Path
from typing import Any,Callable,Dict,List,Optional,Sequence,Tuple
from indexes.clustered_bplus import ClusteredBPlusIndex
from indexes.unclustered_bplus import UnclusteredBPlusIndex
from indexes.extendible_hash import ExtendibleHash
from query.query_planner import IndexMetadata
from spatial.index import SpatialIndex
from storage.heap_file import HeapFile
from storage.sequential_file import SequentialFile
from storage.record import Schema

class CatalogError(Exception):pass
@dataclass
class RegisteredIndex: metadata:IndexMetadata; implementation:Any
@dataclass
class TableMetadata:
    name:str; schema:Any; storage:Any; storage_kind:str; indexes:Dict[str,RegisteredIndex]=field(default_factory=dict)
    def read_rid(self,rid): return self.storage.read(rid) if self.storage_kind=="heap" else self.storage.read_rid(rid)

class Catalog:
    _SUFFIX={"hash":"hash","bplus_clustered":"bpc","bplus_unclustered":"bpu","rtree":"rtree"}
    def __init__(self,data_dir=None,on_change:Optional[Callable]=None,*,rtree_max_entries=16):
        self._tables={};self.data_dir=Path(data_dir) if data_dir is not None else None;self.on_change=on_change;self.rtree_max_entries=rtree_max_entries
    @staticmethod
    def _norm(x):
        if not isinstance(x,str) or not x.strip():raise CatalogError("identifier must be a non-empty string")
        return x.strip().lower()
    def register_table(self,name,storage,*,schema=None,storage_kind=None,replace=False):
        n=self._norm(name)
        if n in self._tables and not replace:raise CatalogError(f"table already registered: {name}")
        schema=schema or getattr(storage,"schema",None)
        kind=(storage_kind or ("heap" if isinstance(storage,HeapFile) else "sequential" if isinstance(storage,SequentialFile) else "")).lower()
        if not schema or kind not in {"heap","sequential"}:raise CatalogError("invalid table storage/schema")
        t=TableMetadata(n,schema,storage,kind);self._tables[n]=t;return t
    def create_table(self,name,columns,primary_key=None,*,storage_kind="heap",if_not_exists=False,data_dir=None,primary_key_index=True):
        n=self._norm(name)
        if n in self._tables:
            if if_not_exists:return self._tables[n]
            raise CatalogError(f"la tabla ya existe: {name}")
        if not columns:raise CatalogError("CREATE TABLE requiere columnas")
        kind=(storage_kind or "heap").lower(); directory=Path(data_dir) if data_dir is not None else self.data_dir
        if directory is None:raise CatalogError("el catálogo no tiene data_dir")
        directory.mkdir(parents=True,exist_ok=True); schema=Schema(list(columns),primary_key or columns[0][0])
        storage=HeapFile(str(directory/f"{n}.dat"),schema) if kind=="heap" else SequentialFile(str(directory/n),schema)
        t=self.register_table(n,storage,schema=schema,storage_kind=kind)
        if primary_key_index:
            self.register_index(name=f"idx_{n}_{schema.primary_key}_hash",table=n,column=schema.primary_key,kind="hash",implementation=ExtendibleHash(bucket_capacity=4,unique=True),unique=True,rebuild=False)
        self._notify();return t
    def drop_table(self,name,*,if_exists=False,delete_files=True):
        n=self._norm(name);t=self._tables.get(n)
        if not t:
            if if_exists:return False
            raise CatalogError(f"unknown table: {name}")
        paths=[t.storage.path,t.storage.path+".free"] if t.storage_kind=="heap" else [t.storage.main_path,t.storage.aux_path]
        del self._tables[n]
        if delete_files:
            for p in paths:
                try:os.remove(p)
                except OSError:pass
        self._notify();return True
    def get_table(self,name):
        try:return self._tables[self._norm(name)]
        except KeyError as e:raise CatalogError(f"unknown table: {name}") from e
    def has_table(self,name):
        try:return self._norm(name) in self._tables
        except CatalogError:return False
    def table_names(self):return sorted(self._tables)
    def index_names(self,table):return sorted(self.get_table(table).indexes)
    def find_indexes_on_column(self,table,column):return sorted(n for n,r in self.get_table(table).indexes.items() if r.metadata.column==column)
    def clustered_index(self,table):
        t=self.get_table(table)
        return next((r for r in t.indexes.values() if r.metadata.kind=="bplus_clustered"),None)
    def create_index(self,table,column,*,kind="bplus_unclustered",unique=False,name=None,if_not_exists=False,lon_column=None):
        t=self.get_table(table);kind=(kind or "").lower();col=self._norm(column)
        if kind not in self._SUFFIX:raise CatalogError(f"técnica de índice no soportada: '{kind}'")
        if col not in t.schema.col_names():raise CatalogError(f"la columna '{column}' no existe en la tabla '{t.name}'")
        idx=self._norm(name) if name else f"idx_{t.name}_{col}_{self._SUFFIX[kind]}"
        if idx in t.indexes:
            if if_not_exists:return t.indexes[idx]
            raise CatalogError(f"el índice '{idx}' ya existe")
        if unique and kind!="hash":raise CatalogError("UNIQUE se soporta con Hash Extendible en este minigestor")
        if kind=="bplus_clustered":
            if self.clustered_index(t.name):raise CatalogError("solo puede existir un índice B+ agrupado por tabla")
            if t.storage_kind!="heap":raise CatalogError("BPLUS_CLUSTERED requiere Heap File en este minigestor; el Archivo Secuencial ya mantiene su propio orden físico por la PK")
            # Orden físico ANTES de capturar los RID del índice.
            self._cluster_heap(t,col)
            impl=ClusteredBPlusIndex(col,order=4,unique=unique)
        elif kind=="bplus_unclustered": impl=UnclusteredBPlusIndex(col,order=4,unique=unique)
        elif kind=="hash": impl=ExtendibleHash(bucket_capacity=4,unique=unique)
        else:
            if not lon_column:raise CatalogError("RTREE necesita (lat, lon)")
            lon=self._norm(lon_column)
            if lon not in t.schema.col_names() or lon==col:raise CatalogError("columna de longitud inválida")
            impl=SpatialIndex(col,lon,max_entries=self.rtree_max_entries)
        reg=self.register_index(name=idx,table=t.name,column=col,kind=kind,implementation=impl,unique=unique,rebuild=False)
        # clustering changed every RID: rebuild every index in a single pass.
        if kind=="bplus_clustered": self.rebuild_indexes(t.name)
        else:self.rebuild_index(t.name,idx)
        self._notify();return reg
    def drop_index(self,name,*,table=None,if_exists=False):
        key=self._norm(name); candidates=[]
        if table is not None:
            t=self.get_table(table);candidates=[t]
        else:candidates=[t for t in self._tables.values() if key in t.indexes]
        if not candidates:
            if if_exists:return False
            raise CatalogError(f"no existe el índice '{name}'")
        t=candidates[0]
        if key not in t.indexes:
            if if_exists:return False
            raise CatalogError(f"no existe el índice '{name}'")
        r=t.indexes[key]
        if r.metadata.column==t.schema.primary_key and r.metadata.kind=="hash" and r.metadata.unique:
            raise CatalogError(f"no se puede eliminar '{key}': garantiza la PRIMARY KEY")
        del t.indexes[key];self._notify();return True
    def register_index(self,*,name,table,column,kind,implementation,unique=None,rebuild=False):
        t=self.get_table(table);idx=self._norm(name);kind=kind.lower()
        if idx in t.indexes:raise CatalogError(f"index already registered: {idx}")
        if column not in t.schema.col_names():raise CatalogError(f"unknown indexed column '{column}'")
        if kind=="bplus_clustered" and any(r.metadata.kind=="bplus_clustered" for r in t.indexes.values()):raise CatalogError("solo puede existir un índice B+ agrupado por tabla")
        meta=IndexMetadata(idx,t.name,column,kind,bool(getattr(implementation,"unique",False) if unique is None else unique));reg=RegisteredIndex(meta,implementation);t.indexes[idx]=reg
        if rebuild:self.rebuild_index(t.name,idx)
        return reg
    def get_index(self,table,name):
        t=self.get_table(table)
        try:return t.indexes[self._norm(name)]
        except KeyError as e:raise CatalogError(f"unknown index '{name}' for table '{table}'") from e
    def _cluster_heap(self,t,column):
        if t.storage_kind!="heap":raise CatalogError("clustering físico solo se admite sobre Heap File")
        rows=[row for _,row in t.storage.scan()];rows.sort(key=lambda r:(r[column] is None,r[column]));t.storage.replace_all(rows)
    def recluster_table(self,table):
        t=self.get_table(table);c=self.clustered_index(t.name)
        if not c:return False
        self._cluster_heap(t,c.metadata.column);self.rebuild_indexes(t.name);return True
    def rebuild_index(self,table,index_name):
        t=self.get_table(table);reg=self.get_index(table,index_name);m=reg.metadata;old=reg.implementation
        if m.kind=="bplus_clustered": new=ClusteredBPlusIndex(m.column,order=getattr(old,"order",4),unique=m.unique)
        elif m.kind=="bplus_unclustered":new=UnclusteredBPlusIndex(m.column,order=getattr(old,"order",4),unique=m.unique)
        elif m.kind=="hash":new=ExtendibleHash(bucket_capacity=getattr(old,"bucket_capacity",4),unique=m.unique,hash_func=getattr(old,"hash_func",None),max_depth=getattr(old,"max_depth",64))
        elif m.kind=="rtree":new=SpatialIndex(old.lat_column,old.lon_column,max_entries=getattr(old,"max_entries",self.rtree_max_entries),metric=getattr(old,"metric","haversine"))
        else:raise CatalogError(f"unsupported index kind: {m.kind}")
        if m.kind=="rtree":new.bulk_load((row,rid) for rid,row in t.storage.scan())
        else:
            for rid,row in t.storage.scan():
                if m.kind in {"bplus_clustered","bplus_unclustered"}:new.insert(row,rid)
                elif m.kind=="hash":new.insert(row[m.column],rid)
        reg.implementation=new;return reg
    def rebuild_indexes(self,table):
        for name in list(self.get_table(table).indexes):self.rebuild_index(table,name)
    def planner_indexes(self):return [r.metadata for t in self._tables.values() for r in t.indexes.values()]
    def planner_storage(self):return {t.name:t.storage_kind for t in self._tables.values()}
    def spatial_index_for(self,table,column=None):
        t=self.get_table(table);col=(column or "").lower()
        spatial=[r for r in t.indexes.values() if r.metadata.kind=="rtree"]
        # ``ubicacion``/``location`` es el alias lógico del par (lat, lon),
        # tal como lo expresa el enunciado del proyecto. Si hay un solo R-Tree
        # en la tabla, el alias resuelve de forma inequívoca ese índice.
        if col in {"ubicacion","location","geom","geometry"} and len(spatial)==1:
            return spatial[0]
        for r in spatial:
            if not col or col in {r.implementation.lat_column.lower(),r.implementation.lon_column.lower(),r.metadata.column.lower()}:return r
        return None
    def describe_tables(self):
        out=[]
        for t in self._tables.values():
            idx=[]
            for r in t.indexes.values():
                d={"name":r.metadata.name,"column":r.metadata.column,"kind":r.metadata.kind,"unique":r.metadata.unique}
                if r.metadata.kind=="rtree":d.update({"lon_column":r.implementation.lon_column,"metric":r.implementation.metric,"max_entries":r.implementation.max_entries})
                idx.append(d)
            out.append({"name":t.name,"columns":[tuple(c) for c in t.schema.to_dict()["columnas"]],"primary_key":t.schema.primary_key,"storage_kind":t.storage_kind,"indexes":idx})
        return out
    def restore_table(self,definition,*,data_dir=None):
        directory=Path(data_dir) if data_dir is not None else self.data_dir;name=self._norm(definition["name"]);schema=Schema([tuple(c) for c in definition["columns"]],definition["primary_key"]);kind=definition.get("storage_kind","heap")
        storage=HeapFile(str(directory/f"{name}.dat"),schema) if kind=="heap" else SequentialFile(str(directory/name),schema);t=self.register_table(name,storage,schema=schema,storage_kind=kind)
        for d in definition.get("indexes",[]):
            k=d["kind"]
            if k=="rtree":impl=SpatialIndex(d["column"],d.get("lon_column") or self._guess_lon(t,d["column"]),max_entries=int(d.get("max_entries",self.rtree_max_entries)),metric=d.get("metric","haversine"))
            elif k=="bplus_clustered":impl=ClusteredBPlusIndex(d["column"],order=4,unique=bool(d.get("unique")))
            elif k=="bplus_unclustered":impl=UnclusteredBPlusIndex(d["column"],order=4,unique=bool(d.get("unique")))
            elif k=="hash":impl=ExtendibleHash(bucket_capacity=4,unique=bool(d.get("unique")))
            else:continue
            self.register_index(name=d["name"],table=name,column=d["column"],kind=k,implementation=impl,unique=bool(d.get("unique")),rebuild=True)
        return t
    @staticmethod
    def _guess_lon(t,lat):
        names=t.schema.col_names(); low={x.lower():x for x in names}
        for c in ("lon","lng","longitud","longitude","x"):
            if c in low:return low[c]
        raise CatalogError(f"no se puede restaurar RTREE: falta lon_column para {lat}")
    def _notify(self):
        if self.on_change:self.on_change()
