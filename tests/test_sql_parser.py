import pytest
from query.sql_parser import SQLParser, SQLParseError, SelectStatement, InsertStatement, DeleteStatement


@pytest.fixture
def parser():
    return SQLParser()


def test_parse_simple_select(parser):
    stmt = parser.parse("SELECT * FROM users")
    assert isinstance(stmt, SelectStatement)
    assert stmt.columns == ("*",)
    assert stmt.query_spec.table == "users"
    assert stmt.query_spec.predicates == ()


def test_parse_select_with_where_and_order_by(parser):
    stmt = parser.parse("SELECT id, name FROM users WHERE age >= 18 ORDER BY name DESC")
    assert isinstance(stmt, SelectStatement)
    assert stmt.columns == ("id", "name")
    assert stmt.query_spec.table == "users"
    assert len(stmt.query_spec.predicates) == 1
    assert stmt.query_spec.predicates[0].column == "age"
    assert stmt.query_spec.predicates[0].operator == ">="
    assert stmt.query_spec.predicates[0].value == 18
    assert len(stmt.query_spec.order_by) == 1
    assert stmt.query_spec.order_by[0].column == "name"
    assert stmt.query_spec.order_by[0].descending is True


def test_parse_select_with_between_and_group_by(parser):
    stmt = parser.parse("SELECT dept, salary FROM employees WHERE salary BETWEEN 2000 AND 5000 GROUP BY dept")
    assert isinstance(stmt, SelectStatement)
    assert stmt.query_spec.group_by == ("dept",)
    assert len(stmt.query_spec.predicates) == 1
    pred = stmt.query_spec.predicates[0]
    assert pred.operator == "between"
    assert pred.value == (2000, 5000)


def test_parse_select_with_join(parser):
    stmt = parser.parse("SELECT * FROM employees JOIN departments ON employees.dept_id = departments.id")
    assert isinstance(stmt, SelectStatement)
    assert len(stmt.query_spec.joins) == 1
    join = stmt.query_spec.joins[0]
    assert join.table == "departments"
    assert join.left_column == "dept_id"
    assert join.right_column == "id"


def test_parse_insert(parser):
    stmt = parser.parse("INSERT INTO users VALUES (1, 'Alice', 25.5)")
    assert isinstance(stmt, InsertStatement)
    assert stmt.table == "users"
    assert stmt.values == (1, "Alice", 25.5)


def test_parse_delete_with_where(parser):
    stmt = parser.parse("DELETE FROM users WHERE id = 10")
    assert isinstance(stmt, DeleteStatement)
    assert stmt.table == "users"
    assert len(stmt.predicates) == 1
    assert stmt.predicates[0].column == "id"
    assert stmt.predicates[0].value == 10


def test_syntax_error_raises_exception(parser):
    with pytest.raises(SQLParseError):
        parser.parse("UPDATE users SET name = 'Bob'")