from __future__ import annotations
from typing import List,Optional
from fastapi import FastAPI,File,Form,HTTPException,Query,UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from backend.engine import DemoEngine
from recommender import recommend_by_copurchase,recommend_by_metadata,stores_with_product

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
@app.post("/api/media/extract")
async def media_extract(file:UploadFile=File(...),kind:str=Form("")):
    try:return engine.extract_media(filename=file.filename or "archivo",content=await file.read(),kind=kind or None)
    except Exception as e:raise HTTPException(400,str(e))
@app.get("/api/media/{name}")
def media_file(name:str):
    try:path,media_type=engine.media_file(name)
    except FileNotFoundError as e:raise HTTPException(404,str(e))
    return FileResponse(path,media_type=media_type,headers={"X-Content-Type-Options":"nosniff"})
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
@app.get("/api/recommend/stores/{producto_id}")
def recommend_stores(producto_id:int,lat:float=-12.0464,lon:float=-77.0428,radius_m:float=15000.0,limit:int=10):
    """Tiendas dentro del radio que tienen stock del producto (issue #137)."""
    try:
        tiendas=stores_with_product(engine,producto_id,(lat,lon),radius_m=radius_m,limit=limit)
        return {"producto_id":producto_id,"centro":{"lat":lat,"lon":lon},"radio_m":radius_m,
                "tiendas":[tienda.as_dict() for tienda in tiendas]}
    except Exception as e:raise HTTPException(400,str(e))
def _recomendaciones(fuente,producto_id:int,k:int):
    try:return {"producto_id":producto_id,"recomendaciones":[r.as_dict() for r in fuente(engine,producto_id,k=k)]}
    except Exception as e:raise HTTPException(400,str(e))
@app.get("/api/recommend/copurchase/{producto_id}")
def recommend_copurchase(producto_id:int,k:int=Query(10,ge=1,le=100)):
    """Usuarios que compraron X también compraron Y (issue #135)."""
    return _recomendaciones(recommend_by_copurchase,producto_id,k)
@app.get("/api/recommend/metadata/{producto_id}")
def recommend_metadata(producto_id:int,k:int=Query(10,ge=1,le=100)):
    """Misma categoría y precio parecido (issue #136)."""
    return _recomendaciones(recommend_by_metadata,producto_id,k)

if __name__=="__main__":
    import uvicorn;uvicorn.run("backend.api:app",host="127.0.0.1",port=8000,reload=True)
