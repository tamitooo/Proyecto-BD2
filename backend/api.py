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