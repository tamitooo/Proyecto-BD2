import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple, Union

from query.query_planner import JoinSpec, OrderBy, Predicate, QuerySpec


@dataclass(frozen=True)
class InsertStatement:
    table: str
    values: Tuple[Any, ...]


@dataclass(frozen=True)
class DeleteStatement:
    table: str
    predicates: Tuple[Predicate, ...]


@dataclass(frozen=True)
class SelectStatement:
    columns: Tuple[str, ...]
    query_spec: QuerySpec


class SQLParseError(Exception):
    pass


class SQLParser:
    """
    Parser SQL ligero para:
      - SELECT [cols] FROM table [JOIN ...] [WHERE ...] [GROUP BY ...] [ORDER BY ...]
      - INSERT INTO table VALUES (...)
      - DELETE FROM table WHERE ...
    """

    def parse(self, sql: str) -> Union[SelectStatement, InsertStatement, DeleteStatement]:
        clean_sql = sql.strip().rstrip(";")
        if not clean_sql:
            raise SQLParseError("Empty SQL statement")

        first_word = clean_sql.split(None, 1)[0].upper()

        if first_word == "SELECT":
            return self._parse_select(clean_sql)
        elif first_word == "INSERT":
            return self._parse_insert(clean_sql)
        elif first_word == "DELETE":
            return self._parse_delete(clean_sql)
        else:
            raise SQLParseError(f"Unsupported SQL command: {first_word}")

    def _parse_select(self, sql: str) -> SelectStatement:
        # Extraer cláusulas principales usando expresiones regulares insensibles a mayúsculas
        pattern = re.compile(
            r"SELECT\s+(?P<select>.+?)\s+FROM\s+(?P<from>[a-zA-Z0-9_]+)"
            r"(?:\s+JOIN\s+(?P<join>.+?)\s+ON\s+(?P<on>.+?))?"
            r"(?:\s+WHERE\s+(?P<where>.+?))?"
            r"(?:\s+GROUP\s+BY\s+(?P<group_by>.+?))?"
            r"(?:\s+ORDER\s+BY\s+(?P<order_by>.+?))?$",
            re.IGNORECASE,
        )

        match = pattern.match(sql)
        if not match:
            raise SQLParseError(f"Syntax error in SELECT statement: {sql}")

        parts = match.groupdict()

        # 1. Columnas seleccionadas
        cols_raw = parts["select"].strip()
        columns = tuple(c.strip() for c in cols_raw.split(","))

        # 2. Tabla base
        table = parts["from"].strip()

        # 3. JOIN (opcional)
        joins = []
        if parts.get("join") and parts.get("on"):
            join_table = parts["join"].strip()
            on_clause = parts["on"].strip()
            # Asume formato: left_table.col = right_table.col o col1 = col2
            on_match = re.match(r"([a-zA-Z0-9_.]+)\s*(=)\s*([a-zA-Z0-9_.]+)", on_clause)
            if not on_match:
                raise SQLParseError(f"Unsupported ON condition in JOIN: {on_clause}")
            left_col, op, right_col = on_match.groups()
            left_col = left_col.split(".")[-1]
            right_col = right_col.split(".")[-1]
            joins.append(JoinSpec(table=join_table, left_column=left_col, right_column=right_col, operator=op))

        # 4. WHERE 
        predicates = []
        if parts.get("where"):
            predicates = self._parse_where(parts["where"].strip())

        # 5. GROUP BY 
        group_by = ()
        if parts.get("group_by"):
            group_by = tuple(g.strip() for g in parts["group_by"].split(","))

        # 6. ORDER BY 
        order_by = []
        if parts.get("order_by"):
            order_items = parts["order_by"].split(",")
            for item in order_items:
                tokens = item.strip().split()
                col = tokens[0]
                descending = len(tokens) > 1 and tokens[1].upper() == "DESC"
                order_by.append(OrderBy(column=col, descending=descending))

        query_spec = QuerySpec(
            table=table,
            predicates=tuple(predicates),
            order_by=tuple(order_by),
            group_by=group_by,
            joins=tuple(joins),
        )

        return SelectStatement(columns=columns, query_spec=query_spec)

    def _parse_insert(self, sql: str) -> InsertStatement:
        match = re.match(
            r"INSERT\s+INTO\s+([a-zA-Z0-9_]+)\s+VALUES\s*\((.+?)\)",
            sql,
            re.IGNORECASE,
        )
        if not match:
            raise SQLParseError(f"Syntax error in INSERT statement: {sql}")

        table = match.group(1).strip()
        raw_vals = match.group(2).split(",")
        values = tuple(self._coerce_literal(v.strip()) for v in raw_vals)

        return InsertStatement(table=table, values=values)

    def _parse_delete(self, sql: str) -> DeleteStatement:
        match = re.match(
            r"DELETE\s+FROM\s+([a-zA-Z0-9_]+)(?:\s+WHERE\s+(.+))?",
            sql,
            re.IGNORECASE,
        )
        if not match:
            raise SQLParseError(f"Syntax error in DELETE statement: {sql}")

        table = match.group(1).strip()
        raw_where = match.group(2)
        predicates = self._parse_where(raw_where.strip()) if raw_where else ()

        return DeleteStatement(table=table, predicates=tuple(predicates))
    
    def _parse_where(self, where_clause: str) -> List[Predicate]:
        predicates = []
        clause = where_clause.strip()

        # 1. Extraer primero todas las condiciones BETWEEN ... AND ...
        between_pattern = re.compile(
            r"([a-zA-Z0-9_]+)\s+BETWEEN\s+('[^']*'|\"[^\"]*\"|\S+)\s+AND\s+('[^']*'|\"[^\"]*\"|\S+)",
            re.IGNORECASE,
        )

        for match in between_pattern.finditer(clause):
            col, low, high = match.groups()
            val = (self._coerce_literal(low.strip()), self._coerce_literal(high.strip()))
            predicates.append(Predicate(column=col, operator="between", value=val))

        # Remover los BETWEEN ya procesados de la cadena
        clause_without_between = between_pattern.sub("", clause).strip()

        # 2. Procesar las demás condiciones separadas por AND
        if clause_without_between:
            raw_conditions = re.split(r"\s+AND\s+", clause_without_between, flags=re.IGNORECASE)
            for cond in raw_conditions:
                cond = cond.strip()
                if not cond:
                    continue

                op_match = re.match(r"([a-zA-Z0-9_]+)\s*(<=|>=|!=|<>|<|>|=)\s*(.+)", cond)
                if not op_match:
                    raise SQLParseError(f"Unsupported condition in WHERE: {cond}")

                col, op, raw_val = op_match.groups()
                val = self._coerce_literal(raw_val.strip())
                predicates.append(Predicate(column=col, operator=op, value=val))

        return predicates

    @staticmethod
    def _coerce_literal(literal: str) -> Any:
        # String con comillas
        if (literal.startswith("'") and literal.endswith("'")) or (
            literal.startswith('"') and literal.endswith('"')
        ):
            return literal[1:-1]

        # Entero
        if re.match(r"^-?\d+$", literal):
            return int(literal)

        # Flotante
        try:
            return float(literal)
        except ValueError:
            pass

        # Booleano
        if literal.upper() == "TRUE":
            return True
        elif literal.upper() == "FALSE":
            return False

        return literal