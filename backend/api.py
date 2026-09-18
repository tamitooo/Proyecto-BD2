"""API REST que expone el motor SQL al frontend React.

Ejecutar desde la raíz del repositorio:
    python -m uvicorn backend.api:app --reload --port 8000
Documentación interactiva: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

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
    sql: str = Field(..., min_length=1, description="SELECT, INSERT o DELETE")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "tables": engine.catalog.table_names()}


@app.get("/api/tables")
def list_tables() -> dict:
    return {"tables": engine.tables()}


@app.get("/api/tables/{name}")
def get_table(name: str) -> dict:
    try:
        return engine.table_info(name)
    except Exception as exc:                       # CatalogError
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/query")
def run_query(request: QueryRequest) -> dict:
    """Nunca lanza: el motor devuelve success=false + error legible."""
    return engine.run(request.sql).to_dict()