import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Union

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


@dataclass(frozen=True)
class SelectStatement:
    columns: Tuple[str, ...]
    query_spec: QuerySpec


class SQLParseError(Exception):
    """Raised when a statement is outside the SQL subset supported by the project."""


class SQLParser:
    """Small, dependency-free parser for the SQL subset required by BD2.

    Supported statements:

    * SELECT columns FROM table [JOIN ... ON ...]
      [WHERE p1 AND p2 ...] [GROUP BY ...] [ORDER BY ...]
    * INSERT INTO table VALUES (...)
    * DELETE FROM table [WHERE ...]

    The parser intentionally does not try to implement the complete SQL
    standard.  Its job is to create the project's existing QuerySpec / AST
    objects reliably, while being quote-aware so commas and keywords inside
    string literals do not corrupt parsing.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, sql: str) -> Union[SelectStatement, InsertStatement, DeleteStatement]:
        if not isinstance(sql, str):
            raise SQLParseError("SQL statement must be a string")

        clean_sql = sql.strip()
        while clean_sql.endswith(";"):
            clean_sql = clean_sql[:-1].rstrip()

        if not clean_sql:
            raise SQLParseError("Empty SQL statement")

        self._validate_balanced(clean_sql)
        first_word = clean_sql.split(None, 1)[0].upper()

        if first_word == "SELECT":
            return self._parse_select(clean_sql)
        if first_word == "INSERT":
            return self._parse_insert(clean_sql)
        if first_word == "DELETE":
            return self._parse_delete(clean_sql)

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
        predicates = tuple(self._parse_where(clauses["WHERE"])) if "WHERE" in clauses else ()
        group_by = self._parse_group_by(clauses.get("GROUP BY"))
        order_by = self._parse_order_by(clauses.get("ORDER BY"))

        return SelectStatement(
            columns=columns,
            query_spec=QuerySpec(
                table=table,
                predicates=predicates,
                order_by=order_by,
                group_by=group_by,
                joins=joins,
            ),
        )

    def _extract_select_clauses(self, text: str) -> Tuple[str, Dict[str, str]]:
        """Split JOIN text from WHERE/GROUP BY/ORDER BY at top level.

        Clause keywords inside quoted strings or parenthesized expressions are
        deliberately ignored.
        """

        markers = []
        for name in ("WHERE", "GROUP BY", "ORDER BY"):
            matches = self._find_all_top_level_keywords(text, name)
            if len(matches) > 1:
                raise SQLParseError(f"Duplicate {name} clause")
            if matches:
                start, end = matches[0]
                markers.append((start, end, name))

        markers.sort(key=lambda item: item[0])
        expected_order = {"WHERE": 0, "GROUP BY": 1, "ORDER BY": 2}
        order = [expected_order[name] for _, _, name in markers]
        if order != sorted(order):
            raise SQLParseError("SELECT clauses must appear as WHERE, GROUP BY, ORDER BY")

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
        predicates = tuple(self._parse_where(raw_where.strip())) if raw_where else ()
        return DeleteStatement(table=table, predicates=predicates)

    # ------------------------------------------------------------------
    # WHERE
    # ------------------------------------------------------------------

    def _parse_where(self, where_clause: str) -> List[Predicate]:
        clause = where_clause.strip()
        if not clause:
            raise SQLParseError("WHERE clause cannot be empty")

        if self._find_top_level_keyword(clause, "OR") is not None:
            raise SQLParseError("OR is not supported yet; use AND predicates only")

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
