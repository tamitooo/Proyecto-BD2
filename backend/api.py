"""API REST que expone el motor SQL al frontend React.

Ejecutar desde la raíz del repositorio:
    python -m uvicorn backend.api:app --reload --port 8000

Documentación interactiva:
    http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.engine import TableManagementError, engine
from query.catalog import CatalogError


MAX_CSV_BYTES = 20 * 1024 * 1024


app = FastAPI(
    title="BD2 Engine API",
    version="1.1.0",
    description=(
        "Puente entre el motor de base de datos (Python) y la interfaz "
        "(React), incluyendo creación de tablas e importación CSV."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    sql: str = Field(
        ...,
        min_length=1,
        description="SELECT, INSERT o DELETE",
    )


class ColumnRequest(BaseModel):
    name: str = Field(..., min_length=1)
    type: str = Field(..., min_length=1)


class CreateTableRequest(BaseModel):
    name: str = Field(..., min_length=1)
    storage_kind: Literal["heap", "sequential"] = "heap"
    primary_key: str = Field(..., min_length=1)
    columns: list[ColumnRequest] = Field(..., min_length=1)


def _raise_table_http_error(exc: Exception) -> None:
    message = str(exc)

    if "already exists" in message or "already registered" in message:
        raise HTTPException(
            status_code=409,
            detail=message,
        ) from exc

    raise HTTPException(
        status_code=400,
        detail=message,
    ) from exc


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "tables": engine.catalog.table_names(),
    }


@app.get("/api/tables")
def list_tables() -> dict:
    return {"tables": engine.tables()}


@app.post("/api/tables", status_code=201)
def create_table(request: CreateTableRequest) -> dict:
    try:
        table = engine.create_table(
            name=request.name,
            columns=[
                {
                    "name": column.name,
                    "type": column.type,
                }
                for column in request.columns
            ],
            primary_key=request.primary_key,
            storage_kind=request.storage_kind,
        )
        return {"table": table}
    except (TableManagementError, CatalogError, ValueError) as exc:
        _raise_table_http_error(exc)


@app.post("/api/tables/import-csv", status_code=201)
async def import_csv_table(
    name: str = Form(...),
    primary_key: str = Form(...),
    storage_kind: Literal["heap", "sequential"] = Form("heap"),
    file: UploadFile = File(...),
) -> dict:
    filename = file.filename or "upload.csv"

    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="only .csv files are supported",
        )

    content = await file.read()

    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(
            status_code=413,
            detail="CSV exceeds the 20 MB upload limit",
        )

    try:
        return engine.import_csv(
            name=name,
            filename=filename,
            content=content,
            primary_key=primary_key,
            storage_kind=storage_kind,
        )
    except (TableManagementError, CatalogError, ValueError) as exc:
        _raise_table_http_error(exc)


@app.get("/api/tables/{name}")
def get_table(name: str) -> dict:
    try:
        return engine.table_info(name)
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc


@app.post("/api/query")
def run_query(request: QueryRequest) -> dict:
    """El motor devuelve success=false + error legible para errores SQL."""
    return engine.run(request.sql).to_dict()
