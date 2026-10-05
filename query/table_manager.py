"""Gestión de tablas dinámicas desde el frontend (crear y cargar CSV).

Este módulo existe para que ``backend/engine.py`` no concentre la lógica de
gestión de tablas **y** siga siendo sólo el pegamento entre el motor y el API.

La pieza clave del diseño: **no hay una segunda ruta de creación de tablas**.
``create_table`` construye la sentencia ``CREATE TABLE`` y la ejecuta con el
mismo ``QueryExecutor`` que usa el panel de consultas, así que:

* el índice Hash único de la clave primaria se crea igual que por SQL;
* la tabla queda registrada en el catálogo (y por tanto persiste al reiniciar)
  con el mismo mecanismo que ``CREATE TABLE``;
* corregir el DDL en el parser corrige las dos puertas a la vez.

Es decir: dos puertas de entrada (el formulario del panel y el SQL), una sola
implementación por debajo.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from query.csv_loader import (
    CsvImportError,
    _coerce,
    _read_source,
    infer_schema_from_csv,
    parse_csv_rows,
)

#: Tipos que acepta el motor. ``VARCHAR`` sin longitud se completa con 32.
TIPOS_SIMPLES = {"INT", "FLOAT"}


class TableManagementError(Exception):
    """Error de gestión de tabla que el API debe devolver al usuario.

    Distingue el fallo de la petición (nombre inválido, tipo no soportado, tabla
    duplicada, clave primaria duplicada) del fallo interno del motor. El mensaje
    es legible y se usa tal cual en la respuesta HTTP.
    """


def _validate_identifier(value: str, kind: str) -> str:
    """Nombre de tabla/columna válido: letras, números y ``_``, sin empezar dígito."""
    texto = (value or "").strip()
    if not texto:
        raise TableManagementError(f"invalid {kind}: no puede estar vacío")

    if texto[0].isdigit():
        raise TableManagementError(
            f"invalid {kind} '{texto}': no puede empezar con un dígito"
        )

    if not all(char.isalnum() or char == "_" for char in texto):
        raise TableManagementError(
            f"invalid {kind} '{texto}': sólo se permiten letras, números y '_'"
        )

    return texto


def _normalize_type(value: str) -> str:
    """Normaliza y valida un tipo del enunciado (INT, FLOAT, VARCHAR(n))."""
    texto = (value or "").strip().upper().replace(" ", "")
    if not texto:
        raise TableManagementError("invalid column type: está vacío")

    if texto in TIPOS_SIMPLES:
        return texto

    if texto == "VARCHAR":
        return "VARCHAR(32)"

    if texto.startswith("VARCHAR(") and texto.endswith(")"):
        interior = texto[len("VARCHAR("):-1]
        if interior.isdigit() and int(interior) > 0:
            return f"VARCHAR({int(interior)})"
        raise TableManagementError(
            f"invalid column type '{value}': VARCHAR necesita una longitud "
            "positiva, por ejemplo VARCHAR(64)"
        )

    raise TableManagementError(
        f"invalid column type '{value}': el motor sólo soporta INT, FLOAT y "
        "VARCHAR(n)"
    )


def normalize_columns(
    columns: Union[Sequence[Mapping[str, str]], Sequence[str]],
) -> List[tuple]:
    """Acepta ``[{"name": "id", "type": "INT"}]`` o ``[("id", "INT")]``."""
    if not columns:
        raise TableManagementError("se necesita al menos una columna")

    normalizadas: List[tuple] = []
    vistas = set()

    for indice, columna in enumerate(columns, start=1):
        if isinstance(columna, Mapping):
            nombre = columna.get("name") or columna.get("nombre")
            tipo = columna.get("type") or columna.get("tipo")
        elif isinstance(columna, (list, tuple)) and len(columna) == 2:
            nombre, tipo = columna
        else:
            raise TableManagementError(
                f"columna {indice}: se espera {{'name': ..., 'type': ...}} o "
                "('nombre', 'TIPO')"
            )

        if nombre is None or tipo is None:
            raise TableManagementError(
                f"columna {indice}: faltan 'name' o 'type'"
            )

        limpio = _validate_identifier(str(nombre), "column").lower()
        if limpio in vistas:
            raise TableManagementError(f"columna duplicada: '{limpio}'")

        vistas.add(limpio)
        normalizadas.append((limpio, _normalize_type(str(tipo))))

    return normalizadas


def build_create_table_sql(
    name: str,
    columns: Sequence[tuple],
    primary_key: str,
    storage_kind: str = "heap",
) -> str:
    """Construye el ``CREATE TABLE`` que ejecuta el motor.

    Usa la sintaxis del parser del proyecto (``USING HEAP`` / ``USING
    SEQUENTIAL``), no una propia: así el SQL que genera el formulario es
    exactamente el que un usuario escribiría a mano.
    """
    definiciones = ", ".join(f"{columna} {tipo}" for columna, tipo in columns)
    return (
        f"CREATE TABLE {name} ({definiciones}, PRIMARY KEY ({primary_key})) "
        f"USING {storage_kind.upper()}"
    )


def validate_storage_kind(value: Optional[str]) -> str:
    texto = (value or "heap").strip().lower()
    if texto not in {"heap", "sequential"}:
        raise TableManagementError(
            f"invalid storage kind '{value}': usa 'heap' o 'sequential'"
        )
    return texto


def create_table(
    engine,
    *,
    name: str,
    columns: Union[Sequence[Mapping[str, str]], Sequence[str]],
    primary_key: str,
    storage_kind: str = "heap",
    source: str = "manual",
    original_filename: Optional[str] = None,
) -> Dict[str, Any]:
    """Crea la tabla por el camino del SQL y devuelve su información.

    Cualquier fallo del motor (nombre duplicado, tipo inválido, etc.) se traduce
    a :class:`TableManagementError` con un mensaje legible.
    """
    nombre = _validate_identifier(name, "table").lower()
    columnas = normalize_columns(columns)
    clave = _validate_identifier(primary_key, "primary key").lower()
    almacenamiento = validate_storage_kind(storage_kind)

    if not any(columna == clave for columna, _ in columnas):
        raise TableManagementError(
            f"primary key column '{clave}' is not present in the table "
            "(" + ", ".join(columna for columna, _ in columnas) + ")"
        )

    if engine.catalog.has_table(nombre):
        raise TableManagementError(f"la tabla '{nombre}' already exists")

    sql = build_create_table_sql(nombre, columnas, clave, almacenamiento)
    resultado = engine.run(sql)
    if not resultado.success:
        raise TableManagementError(
            resultado.error or f"no se pudo crear la tabla '{nombre}'"
        )

    engine._remember_source(nombre, source=source, filename=original_filename)
    return engine.table_info(nombre)


def import_csv_as_table(
    engine,
    *,
    name: str,
    filename: Optional[str],
    content: Union[str, bytes],
    primary_key: str,
    storage_kind: str = "heap",
    delimiter: str = ",",
    encoding: str = "utf-8",
) -> Dict[str, Any]:
    """Crea la tabla desde el CSV (deduciendo el esquema) y carga sus filas.

    Es **atómico**: si algo falla (esquema, fila de ancho incorrecto o clave
    primaria duplicada) la tabla se elimina y el motor queda como estaba. Sin
    eso, un CSV con un error a mitad dejaría una tabla a medio cargar.
    """
    nombre = _validate_identifier(name, "table").lower()
    clave = _validate_identifier(primary_key, "primary key").lower()
    almacenamiento = validate_storage_kind(storage_kind)

    if engine.catalog.has_table(nombre):
        raise TableManagementError(f"la tabla '{nombre}' already exists")

    try:
        # El API recibe los bytes del archivo subido: se decodifican aquí.
        origen = (
            content.decode(encoding) if isinstance(content, (bytes, bytearray))
            else content
        )
        texto = _read_source(origen, encoding, allow_path=False)
    except (CsvImportError, UnicodeDecodeError) as exc:
        raise TableManagementError(
            f"no se pudo leer el CSV con codificación {encoding}: {exc}"
        ) from exc

    # 1) Esquema deducido del propio CSV.
    try:
        columnas = infer_schema_from_csv(
            texto, primary_key=clave, delimiter=delimiter
        )
        filas = parse_csv_rows(
            texto,
            [columna for columna, _ in columnas],
            delimiter=delimiter,
        )
    except CsvImportError as exc:
        raise TableManagementError(str(exc)) from exc

    # 2) Crear la tabla (mismo camino que CREATE TABLE).
    create_table(
        engine,
        name=nombre,
        columns=columnas,
        primary_key=clave,
        storage_kind=almacenamiento,
        source="csv",
        original_filename=filename,
    )

    # 3) Cargar las filas. Ante el primer error se deshace todo.
    tipos = {columna: tipo for columna, tipo in columnas}
    cargadas = 0
    try:
        for numero, fila in enumerate(filas, start=2):  # 2 = primera fila de datos
            valores = []
            for (columna, _), celda in zip(columnas, fila):
                valores.append(_coerce(celda, tipos[columna]))

            sentencia = (
                f"INSERT INTO {nombre} VALUES ("
                + ", ".join(_literal(valor) for valor in valores)
                + ")"
            )
            resultado = engine.run(sentencia)
            if not resultado.success:
                error = resultado.error or "error desconocido"
                if "duplicate" in error.lower() or "duplicad" in error.lower():
                    raise TableManagementError(
                        f"duplicate primary key en la fila {numero}: {error}"
                    )
                raise TableManagementError(f"fila {numero}: {error}")
            cargadas += 1
    except TableManagementError:
        engine.run(f"DROP TABLE IF EXISTS {nombre}")
        engine._forget_source(nombre)
        raise

    engine._save_catalog()
    return {
        "imported_rows": cargadas,
        "table": engine.table_info(nombre),
        "inferred_schema": {
            "columnas": columnas,
            "primary_key": clave,
        },
        "original_filename": filename,
    }


def _literal(valor: Any) -> str:
    """Literal SQL para un valor ya convertido a su tipo."""
    if isinstance(valor, str):
        escapado = valor.replace("'", "''")
        return f"'{escapado}'"
    return repr(valor)
