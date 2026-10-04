import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from query.query_planner import JoinSpec, OrderBy, Predicate, QuerySpec


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_QUALIFIED_IDENTIFIER_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$"
)
_AGGREGATE_RE = re.compile(
    r"^(COUNT|SUM|AVG|MIN|MAX)\s*\(\s*(\*|[A-Za-z_][A-Za-z0-9_]*)\s*\)"
    r"(?:\s+AS\s+[A-Za-z_][A-Za-z0-9_]*)?$",
    re.IGNORECASE,
)
_JOIN_HEAD_RE = re.compile(
    r"^\s*(?:(INNER|LEFT|RIGHT|FULL)\s+)?JOIN\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s+ON\s+",
    re.IGNORECASE,
)
_JOIN_MARKER_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:(?:INNER|LEFT|RIGHT|FULL)\s+)?JOIN(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InsertStatement:
    table: str
    values: Tuple[Any, ...]


@dataclass(frozen=True)
class DeleteStatement:
    table: str
    predicates: Tuple[Predicate, ...]
    #: Cada grupo es un AND; la fila cumple si cumple CUALQUIER grupo (OR).
    or_groups: Tuple[Tuple[Predicate, ...], ...] = ()


@dataclass(frozen=True)
class UpdateStatement:
    table: str
    assignments: Tuple[Tuple[str, Any], ...]
    predicates: Tuple[Predicate, ...] = ()
    or_groups: Tuple[Tuple[Predicate, ...], ...] = ()


@dataclass(frozen=True)
class CreateTableStatement:
    table: str
    columns: Tuple[Tuple[str, str], ...]
    primary_key: str
    storage_kind: str = "heap"
    if_not_exists: bool = False


@dataclass(frozen=True)
class DropTableStatement:
    table: str
    if_exists: bool = False


@dataclass(frozen=True)
class CreateIndexStatement:
    """CREATE [UNIQUE] INDEX [nombre] ON tabla (columna) [USING tecnica]."""

    table: str
    column: str
    name: Optional[str] = None
    unique: bool = False
    kind: str = "bplus_unclustered"
    if_not_exists: bool = False


@dataclass(frozen=True)
class DropIndexStatement:
    """DROP INDEX nombre [ON tabla]."""

    name: str
    table: Optional[str] = None
    if_exists: bool = False


@dataclass(frozen=True)
class TransactionStatement:
    """BEGIN / END / COMMIT / ROLLBACK: control de transacciones del motor."""

    action: str  #: "begin" | "commit" | "rollback" | "status"


@dataclass(frozen=True)
class ExplainStatement:
    """EXPLAIN [ANALYZE] <sentencia>: plan lógico y, si ANALYZE, traza real."""

    statement: Any
    analyze: bool = False


@dataclass(frozen=True)
class SelectStatement:
    columns: Tuple[str, ...]
    query_spec: QuerySpec
    limit: Optional[int] = None


class SQLParseError(Exception):
    """Raised when a statement is outside the SQL subset supported by the project."""


def strip_sql_comments(sql: str) -> str:
    """Quita los comentarios ``--`` y ``/* */`` sin tocar los literales.

    Es necesario para poder pegar un script como el de la cátedra, que empieza
    con comentarios y separa las sentencias con ``;``. Los comentarios dentro de
    comillas simples o dobles se conservan como parte del texto.
    """
    output: List[str] = []
    index = 0
    length = len(sql)
    quote: Optional[str] = None

    while index < length:
        character = sql[index]

        if quote is not None:
            output.append(character)
            if character == quote:
                if index + 1 < length and sql[index + 1] == quote:
                    output.append(sql[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if character in {"'", '"'}:
            quote = character
            output.append(character)
            index += 1
            continue

        if character == "-" and sql.startswith("--", index):
            newline = sql.find("\n", index)
            if newline == -1:
                break
            output.append("\n")
            index = newline + 1
            continue

        if character == "/" and sql.startswith("/*", index):
            closing = sql.find("*/", index + 2)
            if closing == -1:
                raise SQLParseError("comentario /* sin cerrar con */")
            output.append(" ")
            index = closing + 2
            continue

        output.append(character)
        index += 1

    return "".join(output)


def split_sql_statements(sql: str) -> List[str]:
    """Divide un script en sentencias por los ``;`` de nivel superior."""
    statements: List[str] = []
    current: List[str] = []
    quote: Optional[str] = None
    depth = 0
    index = 0

    while index < len(sql):
        character = sql[index]

        if quote is not None:
            current.append(character)
            if character == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    current.append(sql[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if character in {"'", '"'}:
            quote = character
            current.append(character)
        elif character == "(":
            depth += 1
            current.append(character)
        elif character == ")":
            depth = max(0, depth - 1)
            current.append(character)
        elif character == ";" and depth == 0:
            statements.append("".join(current))
            current = []
        else:
            current.append(character)

        index += 1

    statements.append("".join(current))
    return [statement.strip() for statement in statements if statement.strip()]


class SQLParser:
    """Small, dependency-free parser for the SQL subset required by BD2.

    Supported statements:

    * SELECT columns FROM table [JOIN ... ON ...]
      [WHERE p1 AND p2 ...] [GROUP BY ...] [ORDER BY ...] [LIMIT n]
    * INSERT INTO table VALUES (...)
    * UPDATE table SET col = valor, ... [WHERE ...]
    * DELETE FROM table [WHERE ...]
    * CREATE TABLE nombre (col TIPO [PRIMARY KEY], ...) [USING HEAP|SEQUENTIAL]
    * CREATE [UNIQUE] INDEX [nombre] ON tabla (columna)
      [USING HASH|BPLUS_CLUSTERED|BPLUS_UNCLUSTERED]
    * DROP TABLE nombre
    * DROP INDEX nombre [ON tabla]
    * BEGIN TRANSACTION | END TRANSACTION | COMMIT | ROLLBACK
    * EXPLAIN [ANALYZE] <sentencia>

    En ``WHERE`` se admite ``AND`` y ``OR`` (sin paréntesis). El parser
    intencionalmente no implementa el estándar SQL completo: su trabajo es
    construir de forma fiable los objetos QuerySpec / AST del proyecto, siendo
    consciente de comillas, comas y paréntesis dentro de literales.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    KEYWORDS = {
        "SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "EXPLAIN",
        "FROM", "WHERE", "GROUP", "ORDER", "BY", "JOIN", "INNER", "LEFT",
        "RIGHT", "FULL", "ON", "LIMIT", "VALUES", "SET", "TABLE", "INTO",
        "AND", "OR", "BETWEEN", "AS", "USING", "HEAP", "SEQUENTIAL",
        "INDEX", "UNIQUE", "HASH", "BPLUS_CLUSTERED", "BPLUS_UNCLUSTERED",
        "BEGIN", "END", "TRANSACTION", "COMMIT", "ROLLBACK", "IF", "EXISTS",
        "NOT", "WORK",
    }

    def parse(self, sql: str) -> Union[
        SelectStatement,
        InsertStatement,
        DeleteStatement,
        UpdateStatement,
        CreateTableStatement,
        CreateIndexStatement,
        DropTableStatement,
        DropIndexStatement,
        TransactionStatement,
        ExplainStatement,
    ]:
        if not isinstance(sql, str):
            raise SQLParseError("SQL statement must be a string")

        # Un script pegado desde un archivo puede traer BOM, comentarios y
        # varias sentencias separadas por ';'. El motor ejecuta una sentencia
        # por llamada, así que se toma la primera y se ignoran comentarios.
        clean_sql = sql.lstrip("\ufeff").strip()
        clean_sql = strip_sql_comments(clean_sql).strip()
        while clean_sql.endswith(";"):
            clean_sql = clean_sql[:-1].rstrip()

        if ";" in clean_sql:
            sentencias = split_sql_statements(clean_sql)
            if not sentencias:
                raise SQLParseError("Empty SQL statement")
            clean_sql = sentencias[0]

        if not clean_sql:
            raise SQLParseError("Empty SQL statement")

        self._validate_balanced(clean_sql)
        first_word = clean_sql.split(None, 1)[0].upper()

        if first_word == "SELECT":
            return self._parse_select(clean_sql)
        if first_word == "INSERT":
            return self._parse_insert(clean_sql)
        if first_word == "UPDATE":
            return self._parse_update(clean_sql)
        if first_word == "DELETE":
            return self._parse_delete(clean_sql)
        if first_word == "CREATE":
            if re.match(r"CREATE\s+(UNIQUE\s+)?INDEX\b", clean_sql, re.IGNORECASE):
                return self._parse_create_index(clean_sql)
            return self._parse_create_table(clean_sql)
        if first_word == "DROP":
            if re.match(r"DROP\s+INDEX\b", clean_sql, re.IGNORECASE):
                return self._parse_drop_index(clean_sql)
            return self._parse_drop_table(clean_sql)
        if first_word == "EXPLAIN":
            return self._parse_explain(clean_sql)
        if first_word in {"BEGIN", "END", "COMMIT", "ROLLBACK", "START"}:
            return self._parse_transaction(clean_sql)

        raise SQLParseError(f"Unsupported SQL command: {first_word}")

    # ------------------------------------------------------------------
    # SELECT
    # ------------------------------------------------------------------

    def _parse_select(self, sql: str) -> SelectStatement:
        body = re.sub(r"^SELECT\b", "", sql, count=1, flags=re.IGNORECASE).lstrip()
        from_match = self._find_top_level_keyword(body, "FROM")
        if from_match is None:
            raise SQLParseError("SELECT requires a FROM clause")

        from_start, from_end = from_match
        select_raw = body[:from_start].strip()
        if not select_raw:
            raise SQLParseError("SELECT requires at least one selected column")

        columns = tuple(self._split_top_level(select_raw, ","))
        self._validate_select_columns(columns)

        from_tail = body[from_end:].lstrip()
        table_match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\b", from_tail)
        if not table_match:
            raise SQLParseError("FROM requires a valid table name")

        table = table_match.group(1)
        remainder = from_tail[table_match.end():]
        join_text, clauses = self._extract_select_clauses(remainder)

        joins = tuple(self._parse_joins(join_text))

        predicates: Tuple[Predicate, ...] = ()
        predicate_groups: Tuple[Tuple[Predicate, ...], ...] = ()
        if "WHERE" in clauses:
            predicate_groups = self._parse_where_groups(clauses["WHERE"])
            predicates = tuple(
                predicate
                for group in predicate_groups
                for predicate in group
            )

        group_by = self._parse_group_by(clauses.get("GROUP BY"))
        order_by = self._parse_order_by(clauses.get("ORDER BY"))
        limit = self._parse_limit(clauses.get("LIMIT"))

        return SelectStatement(
            columns=columns,
            limit=limit,
            query_spec=QuerySpec(
                table=table,
                predicates=predicates,
                order_by=order_by,
                group_by=group_by,
                joins=joins,
                or_groups=(
                    predicate_groups if len(predicate_groups) > 1 else ()
                ),
            ),
        )

    def _extract_select_clauses(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Split JOIN text from WHERE/GROUP BY/ORDER BY at top level.

        Clause keywords inside quoted strings or parenthesized expressions are
        deliberately ignored.
        """

        markers = []
        for name in ("WHERE", "GROUP BY", "ORDER BY", "LIMIT"):
            matches = self._find_all_top_level_keywords(text, name)
            if len(matches) > 1:
                raise SQLParseError(f"Duplicate {name} clause")
            if matches:
                start, end = matches[0]
                markers.append((start, end, name))

        markers.sort(key=lambda item: item[0])
        expected_order = {"WHERE": 0, "GROUP BY": 1, "ORDER BY": 2, "LIMIT": 3}
        order = [expected_order[name] for _, _, name in markers]
        if order != sorted(order):
            raise SQLParseError(
                "SELECT clauses must appear as WHERE, GROUP BY, ORDER BY, LIMIT"
            )

        if not markers:
            return text.strip(), {}

        join_text = text[: markers[0][0]].strip()
        clauses: Dict[str, str] = {}

        for index, (_, end, name) in enumerate(markers):
            next_start = markers[index + 1][0] if index + 1 < len(markers) else len(text)
            value = text[end:next_start].strip()
            if not value:
                raise SQLParseError(f"{name} clause cannot be empty")
            clauses[name] = value

        return join_text, clauses

    def _parse_joins(self, text: str) -> List[JoinSpec]:
        joins: List[JoinSpec] = []
        remaining = text.strip()

        while remaining:
            head = _JOIN_HEAD_RE.match(remaining)
            if not head:
                raise SQLParseError(f"Unsupported text after FROM clause: {remaining}")

            join_type = (head.group(1) or "inner").lower()
            join_table = head.group(2)
            condition_and_rest = remaining[head.end():]

            next_join = self._find_top_level_regex(condition_and_rest, _JOIN_MARKER_RE)
            if next_join is None:
                on_clause = condition_and_rest.strip()
                remaining = ""
            else:
                on_clause = condition_and_rest[: next_join[0]].strip()
                remaining = condition_and_rest[next_join[0]:].strip()

            on_match = re.fullmatch(
                r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)"
                r"\s*=\s*"
                r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)",
                on_clause,
                flags=re.IGNORECASE,
            )
            if not on_match:
                raise SQLParseError(
                    "JOIN ON currently supports only equality between columns: "
                    f"{on_clause}"
                )

            left_ref, right_ref = on_match.groups()
            left_table, left_col = self._split_column_ref(left_ref)
            right_table, right_col = self._split_column_ref(right_ref)

            # ExternalHashing expects the left key to belong to the rows
            # already produced and the right key to belong to the joined table.
            # If qualifiers make the reversed form explicit, normalize it.
            if left_table == join_table and right_table != join_table:
                left_col, right_col = right_col, left_col

            joins.append(
                JoinSpec(
                    table=join_table,
                    left_column=left_col,
                    right_column=right_col,
                    join_type=join_type,
                    operator="=",
                )
            )

        return joins

    def _parse_group_by(self, raw: str | None) -> Tuple[str, ...]:
        if raw is None:
            return ()

        columns = self._split_top_level(raw, ",")
        result = []
        for column in columns:
            if not _QUALIFIED_IDENTIFIER_RE.fullmatch(column):
                raise SQLParseError(f"Invalid GROUP BY column: {column}")
            result.append(column.split(".")[-1])
        return tuple(result)

    def _parse_order_by(self, raw: str | None) -> Tuple[OrderBy, ...]:
        if raw is None:
            return ()

        result = []
        for item in self._split_top_level(raw, ","):
            match = re.fullmatch(
                r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)"
                r"(?:\s+(ASC|DESC))?",
                item,
                flags=re.IGNORECASE,
            )
            if not match:
                raise SQLParseError(f"Invalid ORDER BY expression: {item}")

            column, direction = match.groups()
            result.append(
                OrderBy(
                    column=column.split(".")[-1],
                    descending=(direction or "ASC").upper() == "DESC",
                )
            )

        return tuple(result)

    # ------------------------------------------------------------------
    # INSERT / DELETE
    # ------------------------------------------------------------------

    def _parse_insert(self, sql: str) -> InsertStatement:
        match = re.fullmatch(
            r"INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)\s+VALUES\s*\((.*)\)\s*",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            raise SQLParseError(f"Syntax error in INSERT statement: {sql}")

        table = match.group(1)
        raw_values = match.group(2).strip()
        if not raw_values:
            raise SQLParseError("INSERT VALUES cannot be empty")

        values = tuple(
            self._coerce_literal(value)
            for value in self._split_top_level(raw_values, ",")
        )
        return InsertStatement(table=table, values=values)

    def _parse_delete(self, sql: str) -> DeleteStatement:
        match = re.fullmatch(
            r"DELETE\s+FROM\s+([A-Za-z_][A-Za-z0-9_]*)"
            r"(?:\s+WHERE\s+(.+))?\s*",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not match:
            raise SQLParseError(f"Syntax error in DELETE statement: {sql}")

        table = match.group(1)
        raw_where = match.group(2)
        groups = self._parse_where_groups(raw_where) if raw_where else ()
        predicates = tuple(p for group in groups for p in group)
        return DeleteStatement(
            table=table,
            predicates=predicates,
            or_groups=groups if len(groups) > 1 else (),
        )

    # ------------------------------------------------------------------
    # UPDATE
    # ------------------------------------------------------------------

    def _parse_update(self, sql: str) -> UpdateStatement:
        head = re.match(
            r"UPDATE\s+([A-Za-z_][A-Za-z0-9_]*)\s+SET\s+",
            sql,
            flags=re.IGNORECASE,
        )
        if not head:
            raise SQLParseError(f"Syntax error in UPDATE statement: {sql}")

        table = head.group(1)
        remainder = sql[head.end():]
        where_match = self._find_top_level_keyword(remainder, "WHERE")

        if where_match is None:
            assignments_text = remainder
            raw_where = None
        else:
            where_start, where_end = where_match
            assignments_text = remainder[:where_start]
            raw_where = remainder[where_end:]

        if not assignments_text.strip():
            raise SQLParseError("UPDATE requires at least one assignment")

        assignments = []
        for item in self._split_top_level(assignments_text, ","):
            match = re.fullmatch(
                r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)",
                item,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if not match:
                raise SQLParseError(f"Invalid assignment in UPDATE: {item}")
            assignments.append(
                (match.group(1), self._coerce_literal(match.group(2)))
            )

        groups = self._parse_where_groups(raw_where) if raw_where else ()
        predicates = tuple(p for group in groups for p in group)

        return UpdateStatement(
            table=table,
            assignments=tuple(assignments),
            predicates=predicates,
            or_groups=groups if len(groups) > 1 else (),
        )

    # ------------------------------------------------------------------
    # CREATE TABLE / DROP TABLE
    # ------------------------------------------------------------------

    _CREATE_HEAD_RE = re.compile(
        r"CREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?"
        r"([A-Za-z_][A-Za-z0-9_]*)\s*\(",
        re.IGNORECASE,
    )

    def _parse_create_table(self, sql: str) -> CreateTableStatement:
        head = self._CREATE_HEAD_RE.match(sql)
        if not head:
            raise SQLParseError(
                "Syntax error: se esperaba CREATE TABLE nombre (columna TIPO, ...)"
            )

        if_not_exists = bool(head.group(1))
        table = head.group(2)

        open_index = head.end() - 1
        close_index = self._find_matching_paren(sql, open_index)
        if close_index is None:
            raise SQLParseError("CREATE TABLE: falta el paréntesis de cierre")

        body = sql[open_index + 1:close_index]
        tail = sql[close_index + 1:].strip()

        storage_kind = "heap"
        if tail:
            using = re.fullmatch(
                r"USING\s+(HEAP|SEQUENTIAL)",
                tail,
                flags=re.IGNORECASE,
            )
            if not using:
                raise SQLParseError(
                    f"CREATE TABLE: sufijo no soportado '{tail}' "
                    "(usa USING HEAP o USING SEQUENTIAL)"
                )
            storage_kind = using.group(1).lower()

        items = self._split_top_level(body, ",") if body.strip() else []
        if not items:
            raise SQLParseError("CREATE TABLE requiere al menos una columna")

        columns: List[Tuple[str, str]] = []
        primary_key: Optional[str] = None

        for item in items:
            item = item.strip()

            if re.match(r"^PRIMARY\s+KEY\b", item, re.IGNORECASE):
                match = re.search(r"\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", item)
                if not match:
                    raise SQLParseError(
                        "PRIMARY KEY de tabla requiere PRIMARY KEY (columna)"
                    )
                primary_key = match.group(1)
                continue

            definition = re.fullmatch(
                r"([A-Za-z_][A-Za-z0-9_]*)\s+"
                r"([A-Za-z]+(?:\s*\(\s*\d+(?:\s*,\s*\d+)?\s*\))?)"
                r"(.*)",
                item,
                flags=re.DOTALL,
            )
            if not definition:
                raise SQLParseError(f"Definición de columna inválida: {item}")

            name = definition.group(1)
            tipo = self._normalize_type(definition.group(2))
            rest = definition.group(3)

            columns.append((name, tipo))

            if re.search(r"PRIMARY\s+KEY", rest, re.IGNORECASE):
                primary_key = name

        if not columns:
            raise SQLParseError("CREATE TABLE requiere al menos una columna")

        names = [name for name, _ in columns]
        if len(set(names)) != len(names):
            raise SQLParseError("CREATE TABLE: nombres de columna repetidos")

        if primary_key is None:
            # Sin PRIMARY KEY explícita se usa la primera columna (documentado).
            primary_key = names[0]
        elif primary_key not in names:
            raise SQLParseError(
                f"CREATE TABLE: la PRIMARY KEY '{primary_key}' no es una columna"
            )

        return CreateTableStatement(
            table=table,
            columns=tuple(columns),
            primary_key=primary_key,
            storage_kind=storage_kind,
            if_not_exists=if_not_exists,
        )

    def _parse_drop_table(self, sql: str) -> DropTableStatement:
        match = re.fullmatch(
            r"DROP\s+TABLE\s+(IF\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*",
            sql,
            flags=re.IGNORECASE,
        )
        if not match:
            raise SQLParseError("Syntax error: se esperaba DROP TABLE nombre")
        return DropTableStatement(
            table=match.group(2),
            if_exists=bool(match.group(1)),
        )

    # ------------------------------------------------------------------
    # CREATE INDEX / DROP INDEX
    # ------------------------------------------------------------------

    _INDEX_KINDS = {
        "HASH": "hash",
        "EXTENDIBLE_HASH": "hash",
        "HASH_INDEX": "hash",
        "BPLUS": "bplus_unclustered",
        "BPLUS_CLUSTERED": "bplus_clustered",
        "CLUSTERED": "bplus_clustered",
        "BPLUS_UNCLUSTERED": "bplus_unclustered",
        "UNCLUSTERED": "bplus_unclustered",
    }

    _CREATE_INDEX_HEAD_RE = re.compile(
        r"CREATE\s+(?:(UNIQUE)\s+)?INDEX\s+"
        r"(?:(IF\s+NOT\s+EXISTS)\s+)?"
        r"(?:([A-Za-z_][A-Za-z0-9_]*)\s+)?"
        r"ON\s+([A-Za-z_][A-Za-z0-9_]*)\s*",
        re.IGNORECASE,
    )

    def _parse_create_index(self, sql: str) -> CreateIndexStatement:
        head = self._CREATE_INDEX_HEAD_RE.match(sql)
        if not head:
            raise SQLParseError(
                "Syntax error: se esperaba "
                "CREATE [UNIQUE] INDEX [nombre] ON tabla (columna) "
                "[USING HASH|BPLUS_CLUSTERED|BPLUS_UNCLUSTERED]"
            )

        unique = bool(head.group(1))
        if_not_exists = bool(head.group(2))
        name = head.group(3)
        table = head.group(4)

        rest = sql[head.end():].strip()
        if not rest.startswith("("):
            raise SQLParseError(
                "CREATE INDEX requiere la columna entre paréntesis: (columna)"
            )

        close_index = rest.find(")")
        if close_index == -1:
            raise SQLParseError("CREATE INDEX: falta el paréntesis de cierre")

        column = rest[1:close_index].strip()
        if not _IDENTIFIER_RE.fullmatch(column):
            raise SQLParseError(
                f"CREATE INDEX: columna inválida '{column}' (una sola columna)"
            )

        tail = rest[close_index + 1:].strip()
        kind = "bplus_unclustered"
        if tail:
            using = re.fullmatch(
                r"USING\s+([A-Za-z_][A-Za-z0-9_]*)",
                tail,
                flags=re.IGNORECASE,
            )
            if not using:
                raise SQLParseError(
                    f"CREATE INDEX: sufijo no soportado '{tail}' "
                    "(usa USING HASH, USING BPLUS_CLUSTERED o "
                    "USING BPLUS_UNCLUSTERED)"
                )
            requested = using.group(1).upper()
            if requested not in self._INDEX_KINDS:
                raise SQLParseError(
                    f"CREATE INDEX: técnica desconocida '{requested}' "
                    "(usa HASH, BPLUS_CLUSTERED o BPLUS_UNCLUSTERED)"
                )
            kind = self._INDEX_KINDS[requested]

        return CreateIndexStatement(
            table=table,
            column=column,
            name=name,
            unique=unique,
            kind=kind,
            if_not_exists=if_not_exists,
        )

    def _parse_drop_index(self, sql: str) -> DropIndexStatement:
        match = re.fullmatch(
            r"DROP\s+INDEX\s+(IF\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*"
            r"(?:ON\s+([A-Za-z_][A-Za-z0-9_]*)\s*)?",
            sql,
            flags=re.IGNORECASE,
        )
        if not match:
            raise SQLParseError(
                "Syntax error: se esperaba DROP INDEX nombre [ON tabla]"
            )
        return DropIndexStatement(
            name=match.group(2),
            table=match.group(3),
            if_exists=bool(match.group(1)),
        )

    # ------------------------------------------------------------------
    # BEGIN / END TRANSACTION
    # ------------------------------------------------------------------

    def _parse_transaction(self, sql: str) -> TransactionStatement:
        text = re.sub(r"\s+", " ", sql.strip()).upper()
        text = re.sub(r"\s+(WORK|TRANSACTION)$", "", text)

        actions = {
            "BEGIN": "begin",
            "START": "begin",
            "START TRANSACTION": "begin",
            "END": "commit",
            "COMMIT": "commit",
            "ROLLBACK": "rollback",
        }

        if text not in actions:
            raise SQLParseError(
                f"Syntax error: sentencia de transacción no soportada '{sql}' "
                "(usa BEGIN TRANSACTION, END TRANSACTION, COMMIT o ROLLBACK)"
            )

        return TransactionStatement(action=actions[text])

    # ------------------------------------------------------------------
    # EXPLAIN
    # ------------------------------------------------------------------

    def _parse_explain(self, sql: str) -> ExplainStatement:
        head = re.match(r"EXPLAIN\s+(ANALYZE\s+)?", sql, flags=re.IGNORECASE)
        if not head:
            raise SQLParseError("Syntax error: se esperaba EXPLAIN [ANALYZE] ...")

        analyze = bool(head.group(1))
        inner = sql[head.end():].strip()
        if not inner:
            raise SQLParseError("EXPLAIN requiere una sentencia")

        if re.match(r"^EXPLAIN\b", inner, re.IGNORECASE):
            raise SQLParseError("EXPLAIN anidado no está soportado")

        return ExplainStatement(statement=self.parse(inner), analyze=analyze)

    @staticmethod
    def _normalize_type(raw: str) -> str:
        """Traduce el tipo declarado al subconjunto del motor (INT/FLOAT/VARCHAR)."""
        text = raw.strip().upper()
        compact = re.sub(r"\s+", "", text)

        match = re.fullmatch(r"(?:VARCHAR|CHAR|CHARACTER)\((\d+)\)", compact)
        if match:
            return f"VARCHAR({int(match.group(1))})"

        if re.fullmatch(r"(?:DECIMAL|NUMERIC)\(\d+(?:,\d+)?\)", compact):
            return "FLOAT"

        if compact in {"INT", "INTEGER", "SMALLINT", "BIGINT", "SERIAL"}:
            return "INT"

        if compact in {
            "FLOAT", "REAL", "DOUBLE", "DOUBLEPRECISION", "DECIMAL", "NUMERIC",
        }:
            return "FLOAT"

        if compact in {"TEXT", "STRING", "CLOB", "VARCHAR", "CHAR", "CHARACTER"}:
            return "VARCHAR(255)"

        raise SQLParseError(
            f"Tipo de columna no soportado: {raw} (usa INT, FLOAT o VARCHAR(n))"
        )

    @classmethod
    def _find_matching_paren(cls, text: str, open_index: int) -> Optional[int]:
        """Posición del ')' que cierra el '(' en `open_index`, ignorando literales."""
        depth = 0
        quote = None
        index = open_index

        while index < len(text):
            char = text[index]
            if quote is not None:
                if char == quote:
                    if index + 1 < len(text) and text[index + 1] == quote:
                        index += 2
                        continue
                    quote = None
                elif char == "\\" and index + 1 < len(text):
                    index += 2
                    continue
                index += 1
                continue

            if char in {"'", '"'}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return index
            index += 1

        return None

    # ------------------------------------------------------------------
    # WHERE
    # ------------------------------------------------------------------

    def _parse_limit(self, raw: Optional[str]) -> Optional[int]:
        if raw is None:
            return None

        text = raw.strip()
        if not re.fullmatch(r"\d+", text):
            raise SQLParseError(
                f"LIMIT solo admite un entero positivo (recibido: {text})"
            )
        return int(text)

    def _parse_where_groups(
        self,
        where_clause: str,
    ) -> Tuple[Tuple[Predicate, ...], ...]:
        """Divide el WHERE por ``OR`` de nivel superior; cada grupo es un AND."""
        clause = where_clause.strip()
        if not clause:
            raise SQLParseError("WHERE clause cannot be empty")

        boundaries = self._find_all_top_level_keywords(clause, "OR")
        parts: List[str] = []
        start = 0
        for or_start, or_end in boundaries:
            parts.append(clause[start:or_start])
            start = or_end
        parts.append(clause[start:])

        groups: List[Tuple[Predicate, ...]] = []
        for part in parts:
            part = part.strip()
            if not part:
                raise SQLParseError("WHERE contiene un OR sin condición")
            groups.append(tuple(self._parse_where(part)))

        return tuple(groups)

    def _parse_where(self, where_clause: str) -> List[Predicate]:
        clause = where_clause.strip()
        if not clause:
            raise SQLParseError("WHERE clause cannot be empty")

        if self._find_top_level_keyword(clause, "OR") is not None:
            raise SQLParseError(
                "OR anidado (por ejemplo dentro de paréntesis) no está soportado"
            )

        predicates: List[Predicate] = []
        position = 0

        while position < len(clause):
            position = self._skip_ws(clause, position)
            column_match = re.match(
                r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?",
                clause[position:],
            )
            if not column_match:
                raise SQLParseError(
                    f"Expected a column in WHERE near: {clause[position:]}"
                )

            column_ref = column_match.group(0)
            column = column_ref.split(".")[-1]
            position += column_match.end()
            position = self._skip_ws(clause, position)

            between = re.match(r"BETWEEN\b", clause[position:], re.IGNORECASE)
            if between:
                position += between.end()
                low_end = self._find_top_level_keyword(clause, "AND", position)
                if low_end is None:
                    raise SQLParseError("BETWEEN requires AND and an upper bound")

                and_start, and_end = low_end
                raw_low = clause[position:and_start].strip()
                if not raw_low:
                    raise SQLParseError("BETWEEN requires a lower bound")

                position = and_end
                next_and = self._find_top_level_keyword(clause, "AND", position)
                if next_and is None:
                    raw_high = clause[position:].strip()
                    position = len(clause)
                else:
                    next_start, next_end = next_and
                    raw_high = clause[position:next_start].strip()
                    position = next_end

                if not raw_high:
                    raise SQLParseError("BETWEEN requires an upper bound")

                predicates.append(
                    Predicate(
                        column=column,
                        operator="between",
                        value=(
                            self._coerce_literal(raw_low),
                            self._coerce_literal(raw_high),
                        ),
                    )
                )
                continue

            op_match = re.match(r"(<=|>=|!=|<>|=|<|>)", clause[position:])
            if not op_match:
                raise SQLParseError(
                    f"Expected a comparison operator after '{column_ref}'"
                )

            operator = op_match.group(1)
            position += op_match.end()
            next_and = self._find_top_level_keyword(clause, "AND", position)

            if next_and is None:
                raw_value = clause[position:].strip()
                position = len(clause)
            else:
                next_start, next_end = next_and
                raw_value = clause[position:next_start].strip()
                position = next_end

            if not raw_value:
                raise SQLParseError(
                    f"Predicate '{column_ref} {operator}' requires a value"
                )

            predicates.append(
                Predicate(
                    column=column,
                    operator=operator,
                    value=self._coerce_literal(raw_value),
                )
            )

        return predicates

    # ------------------------------------------------------------------
    # Validation / lexical helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_select_columns(columns: Tuple[str, ...]) -> None:
        if not columns or any(not column.strip() for column in columns):
            raise SQLParseError("SELECT contains an empty column expression")

        for expression in columns:
            expression = expression.strip()
            if expression == "*":
                continue
            if _QUALIFIED_IDENTIFIER_RE.fullmatch(expression):
                continue
            if _AGGREGATE_RE.fullmatch(expression):
                continue
            raise SQLParseError(f"Unsupported SELECT expression: {expression}")

    @staticmethod
    def _split_column_ref(ref: str) -> Tuple[str | None, str]:
        if "." not in ref:
            return None, ref
        table, column = ref.split(".", 1)
        return table, column

    @staticmethod
    def _skip_ws(text: str, position: int) -> int:
        while position < len(text) and text[position].isspace():
            position += 1
        return position

    @classmethod
    def _split_top_level(cls, text: str, separator: str) -> List[str]:
        """Split by a one-character separator outside quotes/parentheses."""
        if len(separator) != 1:
            raise ValueError("separator must be one character")

        cls._validate_balanced(text)
        parts: List[str] = []
        start = 0
        quote = None
        depth = 0
        index = 0

        while index < len(text):
            ch = text[index]
            if quote is not None:
                if ch == quote:
                    # SQL escaping: 'Badi''s row' / "a ""quoted"" value"
                    if index + 1 < len(text) and text[index + 1] == quote:
                        index += 2
                        continue
                    quote = None
                elif ch == "\\" and index + 1 < len(text):
                    # Also tolerate conventional backslash escaping.
                    index += 2
                    continue
                index += 1
                continue

            if ch in {"'", '"'}:
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == separator and depth == 0:
                part = text[start:index].strip()
                if not part:
                    raise SQLParseError("Empty item in comma-separated list")
                parts.append(part)
                start = index + 1
            index += 1

        final = text[start:].strip()
        if not final:
            raise SQLParseError("Empty item in comma-separated list")
        parts.append(final)
        return parts

    @classmethod
    def _find_top_level_keyword(
        cls,
        text: str,
        keyword: str,
        start: int = 0,
    ) -> Tuple[int, int] | None:
        matches = cls._find_all_top_level_keywords(text, keyword, start)
        return matches[0] if matches else None

    @classmethod
    def _find_all_top_level_keywords(
        cls,
        text: str,
        keyword: str,
        start: int = 0,
    ) -> List[Tuple[int, int]]:
        words = keyword.split()
        pattern = re.compile(
            r"(?<![A-Za-z0-9_])"
            + r"\s+".join(re.escape(word) for word in words)
            + r"(?![A-Za-z0-9_])",
            re.IGNORECASE,
        )
        return cls._find_all_top_level_regex(text, pattern, start)

    @classmethod
    def _find_top_level_regex(
        cls,
        text: str,
        pattern: re.Pattern,
        start: int = 0,
    ) -> Tuple[int, int] | None:
        matches = cls._find_all_top_level_regex(text, pattern, start)
        return matches[0] if matches else None

    @classmethod
    def _find_all_top_level_regex(
        cls,
        text: str,
        pattern: re.Pattern,
        start: int = 0,
    ) -> List[Tuple[int, int]]:
        results: List[Tuple[int, int]] = []
        quote = None
        depth = 0
        index = 0

        while index < len(text):
            ch = text[index]
            if quote is not None:
                if ch == quote:
                    if index + 1 < len(text) and text[index + 1] == quote:
                        index += 2
                        continue
                    quote = None
                elif ch == "\\" and index + 1 < len(text):
                    index += 2
                    continue
                index += 1
                continue

            if ch in {"'", '"'}:
                quote = ch
                index += 1
                continue
            if ch == "(":
                depth += 1
                index += 1
                continue
            if ch == ")":
                depth -= 1
                index += 1
                continue

            if depth == 0 and index >= start:
                match = pattern.match(text, index)
                if match:
                    results.append((match.start(), match.end()))
                    index = match.end()
                    continue

            index += 1

        return results

    @staticmethod
    def _validate_balanced(text: str) -> None:
        quote = None
        depth = 0
        index = 0

        while index < len(text):
            ch = text[index]
            if quote is not None:
                if ch == quote:
                    if index + 1 < len(text) and text[index + 1] == quote:
                        index += 2
                        continue
                    quote = None
                elif ch == "\\" and index + 1 < len(text):
                    index += 2
                    continue
                index += 1
                continue

            if ch in {"'", '"'}:
                quote = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    raise SQLParseError("Unbalanced parentheses")
            index += 1

        if quote is not None:
            raise SQLParseError("Unterminated quoted string")
        if depth != 0:
            raise SQLParseError("Unbalanced parentheses")

    @staticmethod
    def _coerce_literal(literal: str) -> Any:
        literal = literal.strip()
        if not literal:
            raise SQLParseError("Empty literal")

        # Quoted strings. SQL escapes a quote by doubling it.
        if (literal.startswith("'") and literal.endswith("'")) or (
            literal.startswith('"') and literal.endswith('"')
        ):
            quote = literal[0]
            inner = literal[1:-1]
            inner = inner.replace(quote + quote, quote)
            inner = inner.replace("\\" + quote, quote)
            return inner

        upper = literal.upper()
        if upper == "NULL":
            return None
        if upper == "TRUE":
            return True
        if upper == "FALSE":
            return False

        if re.fullmatch(r"[+-]?\d+", literal):
            return int(literal)

        if re.fullmatch(
            r"[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?",
            literal,
        ):
            return float(literal)

        # Keep bare words for backwards compatibility with the original
        # parser. Schema/executor validation remains responsible for deciding
        # whether a value is acceptable for a particular column.
        return literal
