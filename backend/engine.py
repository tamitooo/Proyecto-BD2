from __future__ import annotations
import json,os,threading,time
from pathlib import Path
from typing import Any,Dict,Optional
from indexes.clustered_bplus import ClusteredBPlusIndex
from indexes.unclustered_bplus import UnclusteredBPlusIndex
from indexes.extendible_hash import ExtendibleHash
from query.catalog import Catalog
from query.csv_loader import import_csv
from query.query_executor import QueryExecutor
from query.query_result import QueryResult
from query import table_manager
from spatial.geo import METRIC_UNITS
from storage.heap_file import HeapFile
from storage.sequential_file import SequentialFile
from storage.record import Schema

USERS_SCHEMA=Schema([("id","INT"),("name","VARCHAR(32)"),("age","INT"),("dept","VARCHAR(16)")],"id")
EMPLOYEES_SCHEMA=Schema([("id","INT"),("name","VARCHAR(32)"),("dept","VARCHAR(16)"),("salary","FLOAT")],"id")
DEPARTMENTS_SCHEMA=Schema([("id","INT"),("name","VARCHAR(48)"),("city","VARCHAR(24)")],"id")
SEED=[("users","INSERT INTO users VALUES (1,'Ana Torres',20,'CS')"),("users","INSERT INTO users VALUES (2,'Luis Paredes',23,'EE')"),("users","INSERT INTO users VALUES (3,'Mia Rojas',19,'CS')"),("users","INSERT INTO users VALUES (4,'Karla Ruiz',25,'EE')"),("employees","INSERT INTO employees VALUES (10,'Ana Torres','CS',3200.0)"),("employees","INSERT INTO employees VALUES (11,'Luis Paredes','EE',4800.0)"),("employees","INSERT INTO employees VALUES (12,'Mia Rojas','CS',5100.0)"),("employees","INSERT INTO employees VALUES (13,'Karla Ruiz','EE',3900.0)"),("departments","INSERT INTO departments VALUES (1,'Ciencias de la Computacion','Lima')"),("departments","INSERT INTO departments VALUES (2,'Ingenieria Electronica','Arequipa')")]

class DemoEngine:
    DEMO_TABLES={"users","employees","departments"}
    def __init__(self,data_dir=None,seed=True):
        self.data_dir=Path(data_dir or os.environ.get("BD2_DATA_DIR") or Path(__file__).resolve().parent/"data");self.data_dir.mkdir(parents=True,exist_ok=True);self.catalog_path=self.data_dir/"catalog.json";self._lock=threading.RLock();self._sources={}
        self.users=HeapFile(str(self.data_dir/"users.dat"),USERS_SCHEMA);self.employees=SequentialFile(str(self.data_dir/"employees"),EMPLOYEES_SCHEMA);self.departments=HeapFile(str(self.data_dir/"departments.dat"),DEPARTMENTS_SCHEMA)
        self.catalog=Catalog(self.data_dir,on_change=self._save_catalog)
        self.catalog.register_table("users",self.users);self.catalog.register_table("employees",self.employees);self.catalog.register_table("departments",self.departments)
        self.catalog.register_index(name="idx_users_id_hash",table="users",column="id",kind="hash",implementation=ExtendibleHash(bucket_capacity=4,unique=True),unique=True,rebuild=True)
        # Clustered real: users es Heap y se reorganiza físicamente por age.
        self.catalog.register_index(name="idx_users_age_bpc",table="users",column="age",kind="bplus_clustered",implementation=ClusteredBPlusIndex("age",order=4),rebuild=False)
        self.catalog.recluster_table("users")
        # employees demuestra Archivo Secuencial + B+ secundario (RID).
        self.catalog.register_index(name="idx_emp_salary_bplus",table="employees",column="salary",kind="bplus_unclustered",implementation=UnclusteredBPlusIndex("salary",order=4),rebuild=True)
        self.catalog.register_index(name="idx_emp_dept_bplus",table="employees",column="dept",kind="bplus_unclustered",implementation=UnclusteredBPlusIndex("dept",order=4),rebuild=True)
        self.executor=QueryExecutor(self.catalog);self._load_catalog()
        if seed:self._seed()
    def run(self,sql):
        with self._lock:
            result=self.executor.execute(sql);self._save_catalog();return result
    def _seed(self):
        # Cargar el dataset demo completo sólo cuando la tabla estaba vacía al
        # iniciar. No se reevalúa el conteo después de cada INSERT porque eso
        # dejaría únicamente la primera fila de cada tabla.
        empty = {
            name: sum(1 for _ in self.catalog.get_table(name).storage.scan()) == 0
            for name in self.DEMO_TABLES
        }
        for table, sql in SEED:
            if empty.get(table, False):
                result = self.executor.execute(sql)
                if not result.success:
                    raise RuntimeError(f"No se pudo sembrar {table}: {result.error}")
        self._save_catalog()
    def _save_catalog(self):
        try:
            dynamic=[d for d in self.catalog.describe_tables() if d["name"] not in self.DEMO_TABLES]
            self.catalog_path.write_text(json.dumps({"tables":dynamic,"sources":self._sources},ensure_ascii=False,indent=2),encoding="utf-8")
        except Exception:pass
    def _load_catalog(self):
        if not self.catalog_path.exists():return []
        try:data=json.loads(self.catalog_path.read_text(encoding="utf-8"))
        except Exception:return []
        self._sources=data.get("sources",{});rest=[]
        for d in data.get("tables",[]):
            if not self.catalog.has_table(d["name"]):
                try:self.catalog.restore_table(d,data_dir=self.data_dir);rest.append(d["name"])
                except Exception as e:print(f"[catalog] no se pudo restaurar {d.get('name')}: {e}")
        return rest
    def _remember_source(self,name,*,source,filename=None):self._sources[name.lower()]={"source":source,"original_filename":filename};self._save_catalog()
    def table_info(self,name):
        t=self.catalog.get_table(name);files=[]
        if t.storage_kind=="heap":paths=[("datos",t.storage.path),("free-list",t.storage.path+".free")]
        else:paths=[("main",t.storage.main_path),("aux",t.storage.aux_path)]
        for label,p in paths:files.append({"label":label,"path":str(p),"size_bytes":os.path.getsize(p) if os.path.exists(p) else 0})
        idx=[]
        for r in t.indexes.values():
            d={"name":r.metadata.name,"column":r.metadata.column,"kind":r.metadata.kind,"unique":r.metadata.unique}
            if r.metadata.kind=="rtree":d["lon_column"]=r.implementation.lon_column
            idx.append(d)
        src=self._sources.get(t.name,{"source":"demo" if t.name in self.DEMO_TABLES else "manual","original_filename":None})
        return {"name":t.name,"storage_kind":t.storage_kind,"schema":t.schema.to_dict(),"indexes":idx,"files":files,"row_count":sum(1 for _ in t.storage.scan()),"record_size":t.schema.record_size,**src}
    def tables(self):return [self.table_info(n) for n in self.catalog.table_names()]
    def create_table(self,**kw):return table_manager.create_table(self,**kw)
    def import_csv(self,table,content,**kw):
        rep=import_csv(self.executor,table,content,allow_path=False,**kw);self._save_catalog();return rep
    def import_csv_as_table(self,**kw):return table_manager.import_csv_as_table(self,**kw)
    def spatial_points(self,name):
        t=self.catalog.get_table(name);reg=self.catalog.spatial_index_for(name)
        if reg:
            idx=reg.implementation;latc,lonc=idx.lat_column,idx.lon_column
        else:
            names={c.lower():c for c in t.schema.col_names()};latc=next((names[x] for x in ("lat","latitud","latitude") if x in names),None);lonc=next((names[x] for x in ("lon","lng","longitud","longitude") if x in names),None)
            if not latc or not lonc:raise KeyError(f"'{name}' no tiene columnas espaciales reconocibles")
        pts=[]
        for rid,row in t.storage.scan():
            try:lat=float(row[latc]);lon=float(row[lonc])
            except Exception:continue
            label=next((str(row[c]) for c in ("name","nombre","label") if c in row),None);pts.append({"rid":repr(rid),"lat":lat,"lon":lon,"label":label,"distance_m":None,"row":row})
        if pts:
            b={"min_lat":min(p["lat"] for p in pts),"max_lat":max(p["lat"] for p in pts),"min_lon":min(p["lon"] for p in pts),"max_lon":max(p["lon"] for p in pts)}
        else:b=None
        return {"table":name,"lat_column":latc,"lon_column":lonc,"label_column":None,"count":len(pts),"bounds":b,"points":pts}
    def spatial_query(self,*,table,kind,lat,lon,radius_m=5000,k=10,metric="haversine",polygon=None):
        start=time.perf_counter();reg=self.catalog.spatial_index_for(table)
        if not reg:return {"success":False,"error":"La tabla no tiene índice R-Tree","table":table,"kind":kind,"metric":metric,"points":[]}
        idx=reg.implementation;t=self.catalog.get_table(table)
        if kind=="range":matches=idx.range_search((lat,lon),radius_m,metric=metric)
        elif kind=="knn":matches=idx.knn((lat,lon),k,metric=metric)
        elif kind=="polygon":
            pairs=idx.polygon_search(polygon or []);matches=[(rid,None) for rid,_ in pairs]
        else:raise ValueError("kind debe ser range, knn o polygon")
        pts=[]
        for rid,d in matches:
            row=t.read_rid(rid)
            if row is None:continue
            plat,plon=idx.coordinates(rid);pts.append({"rid":repr(rid),"lat":plat,"lon":plon,"label":str(row.get("name") or row.get("nombre") or "") or None,"distance_m":d,"row":row})
        return {"success":True,"kind":kind,"metric":metric,"table":table,"access_path":{"range":"RTREE_RANGE_SCAN","knn":"RTREE_KNN","polygon":"RTREE_POLYGON"}[kind],"used_indexes":[reg.metadata.name],"execution_time_ms":round((time.perf_counter()-start)*1000,6),"distance_unit":METRIC_UNITS.get(metric,"m"),"points":pts,"candidates_visited":len(pts),"error":None}
