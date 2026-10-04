"""API REST que expone el motor SQL al frontend React.

Ejecutar desde la raíz del repositorio:
    python -m uvicorn backend.api:app --reload --port 8000
Documentación interactiva: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.engine import engine

app = FastAPI(
    title="BD2 Engine API",
    version="1.0.0",
    description="Puente entre el motor de base de datos (Python) y la interfaz (React).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    sql: str = Field(
        ...,
        min_length=1,
        description=(
            "SELECT, INSERT, UPDATE, DELETE, CREATE TABLE, DROP TABLE, "
            "CREATE INDEX, DROP INDEX, BEGIN TRANSACTION / END TRANSACTION / "
            "COMMIT / ROLLBACK, EXPLAIN [ANALYZE]"
        ),
    )


class CsvImportRequest(BaseModel):
    csv_text: str = Field(..., min_length=1, description="Contenido del CSV")
    has_header: bool = Field(True, description="La primera fila es el encabezado")
    delimiter: str = Field(",", min_length=1, max_length=1)


# ----------------------------------------------------------------------
# Espacial (Parte 2)
# ----------------------------------------------------------------------

class SpatialQueryRequest(BaseModel):
    """Consulta espacial para el panel de mapa."""

    table: str = Field(..., min_length=1)
    kind: str = Field("range", description="range | knn | polygon")
    lat: float = Field(-12.0464, description="Latitud del punto de consulta")
    lon: float = Field(-77.0428, description="Longitud del punto de consulta")
    radius_m: float = Field(5000.0, ge=0, description="Radio en metros")
    k: int = Field(10, ge=1, le=10_000)
    metric: str = Field("haversine", description="euclidean | haversine")
    polygon: Optional[List[List[float]]] = Field(
        None, description="Vértices [[lat, lon], ...] para kind='polygon'"
    )


@app.get("/api/health")
def health() -> dict:
    transaccion = engine.transaction_state()
    return {
        "status": "ok",
        "tables": engine.catalog.table_names(),
        "transaction": transaccion,
    }


@app.get("/api/tables")
def list_tables() -> dict:
    return {"tables": engine.tables()}


@app.get("/api/catalog")
def catalog_manifest() -> dict:
    """Tablas creadas por el usuario (persistidas en catalog.json)."""
    return engine.catalog_manifest()


@app.get("/api/tables/{name}")
def get_table(name: str) -> dict:
    try:
        return engine.table_info(name)
    except Exception as exc:                       # CatalogError
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/tables/{name}/import")
def import_csv(name: str, request: CsvImportRequest) -> dict:
    """Carga un CSV en una tabla existente (mismo camino que INSERT)."""
    try:
        report = engine.import_csv(
            name,
            request.csv_text,
            has_header=request.has_header,
            delimiter=request.delimiter,
        )
    except Exception as exc:                       # CatalogError, etc.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return report.to_dict()


@app.post("/api/query")
def run_query(request: QueryRequest) -> dict:
    """Nunca lanza: el motor devuelve success=false + error legible."""
    return engine.run(request.sql).to_dict()

@app.get("/api/spatial/points/{name}")
def spatial_points(name: str, limit: int = 0) -> dict:
    """Puntos de una tabla espacial, para el panel de mapa (Parte 2)."""
    try:
        return engine.spatial_points(name, limit=limit or None)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/spatial/query")
def spatial_query(request: SpatialQueryRequest) -> dict:
    """Consulta espacial (rango, k-NN o poligono) resuelta con el R-Tree."""
    try:
        return engine.spatial_query(
            request.table,
            kind=request.kind,
            lat=request.lat,
            lon=request.lon,
            radius_m=request.radius_m,
            k=request.k,
            metric=request.metric,
            polygon=request.polygon,
        )
    except Exception as exc:
        # El frontend siempre lee el mismo contrato, con success=false.
        return {
            "success": False,
            "kind": request.kind,
            "metric": request.metric,
            "table": request.table,
            "points": [],
            "error": str(exc),
        }
