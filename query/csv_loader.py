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
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

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


def infer_schema_from_csv(
    text: str,
    *,
    primary_key: Optional[str] = None,
    delimiter: str = ",",
    has_header: bool = True,
) -> List[Tuple[str, str]]:
    """Deduce ``[(columna, tipo)]`` a partir del contenido de un CSV.

    Reglas (deterministas, pensadas para el caso del enunciado: INT, FLOAT y
    VARCHAR):

    * Todas las celdas de una columna enteras -> ``INT``;
    * todas numéricas (y alguna decimal) -> ``FLOAT``;
    * en cualquier otro caso -> ``VARCHAR(n)`` con ``n`` = **longitud máxima
      observada** en esa columna (mínimo 1).

    Las columnas vacías no cuentan para decidir el tipo, así que una columna con
    huecos sigue siendo INT o FLOAT. Los tipos nativos del proyecto son sólo INT,
    FLOAT y VARCHAR(n), así que la deducción se limita a esos tres.
    """
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if row and any(cell.strip() for cell in row)]
    if not rows:
        raise CsvImportError("el CSV está vacío: no se puede deducir el esquema")

    header = [cell.strip() for cell in rows[0]] if has_header else []
    data_rows = rows[1:] if has_header else rows
    if not data_rows:
        raise CsvImportError("el CSV no tiene filas de datos")

    width = len(header) if has_header else max(len(row) for row in data_rows)
    if width == 0:
        raise CsvImportError("el CSV no tiene columnas")

    if not has_header:
        header = [f"columna_{i + 1}" for i in range(width)]

    columns: List[Tuple[str, str]] = []
    for position in range(width):
        celdas = [
            row[position].strip()
            for row in data_rows
            if position < len(row) and row[position].strip()
        ]

        if not celdas:
            # Columna entera vacía: se asume texto de longitud 1.
            columns.append((header[position], "VARCHAR(1)"))
            continue

        todos_enteros = True
        todos_numericos = True
        for celda in celdas:
            try:
                float(celda)
            except ValueError:
                todos_numericos = False
                todos_enteros = False
                break
            if not _is_integer_literal(celda):
                todos_enteros = False

        if todos_enteros:
            tipo = "INT"
        elif todos_numericos:
            tipo = "FLOAT"
        else:
            # Longitud máxima **observada**: es lo que hace el motor de la
            # referencia y evita truncar datos reales.
            largo = max(len(celda) for celda in celdas)
            tipo = f"VARCHAR({max(1, largo)})"

        columns.append((header[position], tipo))

    if primary_key:
        buscada = primary_key.strip().lower()
        if not any(name.lower() == buscada for name, _ in columns):
            raise CsvImportError(
                f"primary key '{primary_key}' is not present in the CSV "
                "(" + ", ".join(name for name, _ in columns) + ")"
            )

    return columns


def _is_integer_literal(texto: str) -> bool:
    """¿El texto representa un entero (sin parte decimal)?"""
    limpio = texto.strip().lstrip("+-")
    return bool(limpio) and limpio.isdigit()


def parse_csv_rows(
    text: str,
    columns: Sequence[str],
    *,
    delimiter: str = ",",
    has_header: bool = True,
) -> List[List[str]]:
    """Filas de datos del CSV como listas de texto sin procesar.

    Valida que **todas** las filas tengan el ancho esperado: un CSV con una fila
    corta o larga es un error del archivo, no una fila a medias, así que falla
    con el número de fila en el mensaje.
    """
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if row and any(cell.strip() for cell in row)]
    if not rows:
        raise CsvImportError("el CSV está vacío")

    data_rows = rows[1:] if has_header else rows
    esperado = len(columns)

    for numero, row in enumerate(data_rows, start=1):
        if len(row) != esperado:
            raise CsvImportError(
                f"fila {numero}: se esperaban {esperado} columnas (expected "
                f"{esperado}) y el CSV trae {len(row)}"
            )

    return [list(row) for row in data_rows]


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
