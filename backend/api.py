from __future__ import annotations
from typing import List,Optional
from fastapi import FastAPI,File,Form,HTTPException,UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,Field
from backend.engine import DemoEngine

app=FastAPI(title="Minigestor de Base de Datos Multimodal",version="2.0")
app.add_middleware(CORSMiddleware,allow_origins=["http://localhost:5173","http://127.0.0.1:5173"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
engine=DemoEngine()

class QueryBody(BaseModel): sql:str
class ColumnBody(BaseModel): name:str;type:str
class CreateTableBody(BaseModel): name:str;storage_kind:str="heap";primary_key:str;columns:List[ColumnBody]
class SpatialBody(BaseModel):
    table:str;kind:str="range";lat:float=-12.0464;lon:float=-77.0428;radius_m:float=Field(5000,ge=0);k:int=Field(10,ge=1);metric:str="haversine";polygon:Optional[List[List[float]]]=None

@app.get("/api/health")
def health():return {"status":"ok","tables":engine.catalog.table_names()}
@app.get("/api/tables")
def tables():return engine.tables()
@app.get("/api/catalog")
def catalog():return {"tables":engine.tables()}
@app.get("/api/tables/{name}")
def table(name:str):
    try:return engine.table_info(name)
    except Exception as e:raise HTTPException(404,str(e))
@app.post("/api/tables")
def create_table(body:CreateTableBody):
    try:return {"table":engine.create_table(name=body.name,columns=[c.model_dump() for c in body.columns],primary_key=body.primary_key,storage_kind=body.storage_kind)}
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/tables/import")
async def import_new(file:UploadFile=File(...),name:str=Form(...),primary_key:str=Form(...),storage_kind:str=Form("heap"),delimiter:str=Form(",")):
    try:return engine.import_csv_as_table(name=name,filename=file.filename,content=await file.read(),primary_key=primary_key,storage_kind=storage_kind,delimiter=delimiter)
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/tables/{name}/import")
async def import_existing(name:str,file:UploadFile=File(...),delimiter:str=Form(","),has_header:bool=Form(True)):
    try:return engine.import_csv(name,await file.read(),delimiter=delimiter,has_header=has_header).to_dict()
    except Exception as e:raise HTTPException(400,str(e))
@app.post("/api/query")
def query(body:QueryBody):return engine.run(body.sql).to_dict()
@app.get("/api/spatial/points/{name}")
def spatial_points(name:str):
    try:return engine.spatial_points(name)
    except Exception as e:raise HTTPException(404,str(e))
@app.post("/api/spatial/query")
def spatial_query(body:SpatialBody):
    try:
        polygon=[(float(x[0]),float(x[1])) for x in body.polygon] if body.polygon else None
        return engine.spatial_query(table=body.table,kind=body.kind,lat=body.lat,lon=body.lon,radius_m=body.radius_m,k=body.k,metric=body.metric,polygon=polygon)
    except Exception as e:raise HTTPException(400,str(e))

if __name__=="__main__":
    import uvicorn;uvicorn.run("backend.api:app",host="127.0.0.1",port=8000,reload=True)
