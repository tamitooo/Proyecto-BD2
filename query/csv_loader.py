"""Importación de archivos CSV hacia tablas del motor.

Un minigestor necesita poder trabajar con datos externos (el caso típico del
curso: un CSV de prueba del profesor). Este módulo implementa esa utilidad
reutilizando el **mismo camino de escritura** que ``INSERT``: cada fila se
inserta a través del ``QueryExecutor``, de modo que se respetan la clave
primaria, los índices y la reorganización del Archivo Secuencial.

El CSV se interpreta con la librería estándar ``csv`` (soporta campos entre
comillas con comas y comillas escapadas: ``"Pérez, Juan"``).
"""

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from query.sql_parser import InsertStatement


@dataclass
class CsvImportReport:
    """Resultado de una importación, serializable para el API REST."""

    table: str
    columns: List[str] = field(default_factory=list)
    rows_read: int = 0
    inserted: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.failed == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table": self.table,
            "columns": list(self.columns),
            "rows_read": self.rows_read,
            "inserted": self.inserted,
            "failed": self.failed,
            "errors": list(self.errors),
            "success": self.success,
        }


class CsvImportError(Exception):
    """Error de importación que debe verse como fallo, no como 0 filas."""


def _read_source(
    source: Union[str, Path, io.IOBase],
    encoding: str,
    *,
    allow_path: bool = True,
) -> str:
    """Acepta una ruta, el contenido CSV o un archivo ya abierto.

    Un texto que "parece una ruta" (una sola línea, sin comas) pero no existe
    es un error explícito: antes se interpretaba como contenido CSV y la
    importación terminaba con 0 filas y ``success = True``, que es peor que
    fallar porque oculta el problema.
    """
    if hasattr(source, "read"):
        data = source.read()
        return data.decode(encoding) if isinstance(data, bytes) else data

    text = str(source)
    candidate = Path(text)
    try:
        if candidate.is_file():
            return candidate.read_text(encoding=encoding)
    except OSError as exc:
        raise CsvImportError(
            f"no se pudo leer el archivo '{candidate}': {exc}"
        ) from exc

    if allow_path and "\n" not in text and "\r" not in text and "," not in text:
        raise CsvImportError(
            f"no existe el archivo CSV '{text}'. Si querías pegar el contenido "
            "del CSV, usa --stdin o adjúntalo como archivo"
        )

    return text


def _coerce(value: str, kind: str) -> Any:
    text = value.strip()
    if kind == "INT":
        return int(float(text)) if text else 0
    if kind == "FLOAT":
        return float(text) if text else 0.0
    return text


def _kind_of(schema, column: str) -> str:
    for field_definition in schema.fields:
        if field_definition.name == column:
            return field_definition.kind
    raise KeyError(column)


def import_csv(
    executor,
    table_name: str,
    source: Union[str, Path, io.IOBase],
    *,
    has_header: bool = True,
    delimiter: str = ",",
    encoding: str = "utf-8",
    max_errors: int = 10,
    allow_path: bool = True,
    strict_header: bool = True,
) -> CsvImportReport:
    """Carga un CSV en ``table_name`` y devuelve el reporte de la importación.

    ``strict_header`` evita la corrupción silenciosa: si el encabezado no
    coincide con las columnas de la tabla, se falla con un mensaje que lista las
    columnas esperadas en lugar de importar por posición.
    """
    table = executor.catalog.get_table(table_name)
    schema = table.schema
    columns = schema.col_names()

    text = _read_source(source, encoding, allow_path=allow_path)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows: List[List[str]] = [
        row for row in reader
        if row and any(cell.strip() for cell in row)
    ]

    report = CsvImportReport(table=table.name, columns=list(columns))
    if not rows:
        raise CsvImportError(
            f"el CSV no tiene filas de datos para la tabla '{table.name}'"
        )

    # Un origen de una sola línea sin comas es un nombre de archivo, no un CSV:
    # falla como archivo inexistente en lugar de confundirse con un encabezado.
    if not hasattr(source, "read") and "\n" not in text and "\r" not in text and "," not in text:
        raise CsvImportError(
            f"'{text.strip()}' no parece un CSV: es una sola línea sin "
            "separadores. Si es una ruta, revisa que el archivo exista"
        )

    if has_header:
        header = [cell.strip().lower() for cell in rows[0]]
        if all(column.lower() in header for column in columns):
            positions = [header.index(column.lower()) for column in columns]
        elif strict_header:
            raise CsvImportError(
                "el encabezado del CSV ("
                + ", ".join(rows[0])
                + ") no incluye todas las columnas de la tabla '"
                + table.name
                + "' ("
                + ", ".join(columns)
                + "). Renombra las columnas del CSV o usa "
                "has_header=False para importar por posición"
            )
        else:
            # Encabezado con otros nombres: se importa por posición.
            positions = list(range(len(columns)))
        data_rows = rows[1:]
    else:
        positions = list(range(len(columns)))
        data_rows = rows

    report.rows_read = len(data_rows)

    for index, raw in enumerate(data_rows, start=1):
        try:
            values = []
            for position, column in zip(positions, columns):
                cell = raw[position] if position < len(raw) else ""
                values.append(_coerce(cell, _kind_of(schema, column)))

            result = executor.execute(
                InsertStatement(table=table.name, values=tuple(values))
            )
            if result.success:
                report.inserted += 1
            else:
                report.failed += 1
                if len(report.errors) < max_errors:
                    report.errors.append(f"fila {index}: {result.error}")
        except Exception as exc:  # fila mal formada, tipo inválido, etc.
            report.failed += 1
            if len(report.errors) < max_errors:
                report.errors.append(f"fila {index}: {exc}")

    return report
