import pytest

from query.query_planner import (
    IndexMetadata,
    JoinSpec,
    OrderBy,
    Predicate,
    QueryPlanner,
    QuerySpec,
)


def test_equality_prefers_hash_over_bplus():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                name="idx_users_id_hash",
                table="users",
                column="id",
                kind="hash",
                unique=True,
            ),
            IndexMetadata(
                name="idx_users_id_bplus",
                table="users",
                column="id",
                kind="bplus_clustered",
                unique=True,
            ),
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="users",
            predicates=(Predicate("id", "=", 10),),
        )
    )

    assert plan.access_path == "HASH_INDEX_LOOKUP"
    assert plan.used_indexes == ["idx_users_id_hash"]
    assert plan.steps[0].index == "idx_users_id_hash"


def test_equality_uses_clustered_bplus_when_hash_missing():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                name="idx_users_id",
                table="users",
                column="id",
                kind="bplus_clustered",
            )
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="users",
            predicates=(Predicate("id", "=", 10),),
        )
    )

    assert plan.access_path == "BPLUS_CLUSTERED_LOOKUP"
    assert plan.used_indexes == ["idx_users_id"]


def test_equality_uses_unclustered_bplus_when_only_option():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                name="idx_users_email",
                table="users",
                column="email",
                kind="bplus_unclustered",
            )
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="users",
            predicates=(Predicate("email", "=", "a@x.com"),),
        )
    )

    assert plan.access_path == "BPLUS_UNCLUSTERED_LOOKUP"


def test_range_prefers_clustered_bplus():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_salary_clustered",
                "employees",
                "salary",
                "bplus_clustered",
            ),
            IndexMetadata(
                "idx_salary_unclustered",
                "employees",
                "salary",
                "bplus_unclustered",
            ),
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="employees",
            predicates=(Predicate("salary", ">=", 3000),),
        )
    )

    assert plan.access_path == "BPLUS_CLUSTERED_RANGE_SCAN"
    assert plan.used_indexes == ["idx_salary_clustered"]


def test_between_uses_bplus_range_scan():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_age",
                "users",
                "age",
                "bplus_unclustered",
            )
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="users",
            predicates=(Predicate("age", "between", (18, 30)),),
        )
    )

    assert plan.access_path == "BPLUS_UNCLUSTERED_RANGE_SCAN"


def test_hash_is_not_used_for_range_predicate():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_age_hash",
                "users",
                "age",
                "hash",
            )
        ],
        storage_by_table={"users": "heap"},
    )

    plan = planner.plan(
        QuerySpec(
            table="users",
            predicates=(Predicate("age", ">", 18),),
        )
    )

    assert plan.access_path == "HEAP_SCAN"
    assert plan.steps[1].operator == "FILTER"


def test_heap_scan_when_no_index_exists():
    planner = QueryPlanner(
        storage_by_table={"users": "heap"}
    )

    plan = planner.plan(
        QuerySpec(
            table="users",
            predicates=(Predicate("name", "=", "Ana"),),
        )
    )

    assert plan.access_path == "HEAP_SCAN"
    assert plan.steps[0].operator == "HEAP_SCAN"
    assert plan.steps[1].operator == "FILTER"


def test_sequential_scan_when_registered():
    planner = QueryPlanner(
        storage_by_table={"events": "sequential"}
    )

    plan = planner.plan(QuerySpec(table="events"))

    assert plan.access_path == "SEQUENTIAL_SCAN"
    assert len(plan.steps) == 1


def test_default_storage_falls_back_to_heap():
    planner = QueryPlanner()

    plan = planner.plan(QuerySpec(table="unknown"))

    assert plan.access_path == "HEAP_SCAN"


def test_order_by_ascending_can_use_clustered_bplus_without_external_sort():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_salary",
                "employees",
                "salary",
                "bplus_clustered",
            )
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="employees",
            order_by=(OrderBy("salary"),),
        )
    )

    assert plan.access_path == "BPLUS_CLUSTERED_INDEX_SCAN"
    assert [step.operator for step in plan.steps] == [
        "BPLUS_CLUSTERED_INDEX_SCAN"
    ]


def test_order_by_ascending_can_use_unclustered_bplus():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_salary",
                "employees",
                "salary",
                "bplus_unclustered",
            )
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="employees",
            order_by=(OrderBy("salary"),),
        )
    )

    assert plan.access_path == "BPLUS_UNCLUSTERED_INDEX_SCAN"
    assert "EXTERNAL_SORT" not in [
        step.operator for step in plan.steps
    ]


def test_order_by_descending_requires_external_sort():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_salary",
                "employees",
                "salary",
                "bplus_clustered",
            )
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="employees",
            order_by=(OrderBy("salary", descending=True),),
        )
    )

    operators = [step.operator for step in plan.steps]

    assert plan.access_path == "HEAP_SCAN"
    assert operators == ["HEAP_SCAN", "EXTERNAL_SORT"]


def test_hash_lookup_plus_order_by_requires_external_sort():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_id_hash",
                "users",
                "id",
                "hash",
            ),
            IndexMetadata(
                "idx_name_bplus",
                "users",
                "name",
                "bplus_clustered",
            ),
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="users",
            predicates=(Predicate("id", "=", 1),),
            order_by=(OrderBy("name"),),
        )
    )

    operators = [step.operator for step in plan.steps]

    assert plan.access_path == "HASH_INDEX_LOOKUP"
    assert "EXTERNAL_SORT" in operators


def test_range_on_same_bplus_column_covers_order_by_ascending():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_salary",
                "employees",
                "salary",
                "bplus_clustered",
            )
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="employees",
            predicates=(Predicate("salary", ">=", 3000),),
            order_by=(OrderBy("salary"),),
        )
    )

    assert plan.access_path == "BPLUS_CLUSTERED_RANGE_SCAN"
    assert "EXTERNAL_SORT" not in [
        step.operator for step in plan.steps
    ]


def test_multiple_order_by_columns_require_external_sort():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_dept",
                "employees",
                "dept",
                "bplus_clustered",
            )
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="employees",
            order_by=(
                OrderBy("dept"),
                OrderBy("salary"),
            ),
        )
    )

    operators = [step.operator for step in plan.steps]

    assert "EXTERNAL_SORT" in operators


def test_group_by_adds_external_hash_group_by():
    planner = QueryPlanner()

    plan = planner.plan(
        QuerySpec(
            table="employees",
            group_by=("dept",),
        )
    )

    assert [step.operator for step in plan.steps] == [
        "HEAP_SCAN",
        "EXTERNAL_HASH_GROUP_BY",
    ]


def test_group_by_then_order_by_requires_external_sort():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_dept",
                "employees",
                "dept",
                "bplus_clustered",
            )
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="employees",
            group_by=("dept",),
            order_by=(OrderBy("dept"),),
        )
    )

    assert [step.operator for step in plan.steps] == [
        "BPLUS_CLUSTERED_INDEX_SCAN",
        "EXTERNAL_HASH_GROUP_BY",
        "EXTERNAL_SORT",
    ]


def test_equi_join_uses_external_hash_join():
    planner = QueryPlanner()

    plan = planner.plan(
        QuerySpec(
            table="employees",
            joins=(
                JoinSpec(
                    table="departments",
                    left_column="dept_id",
                    right_column="id",
                    operator="=",
                ),
            ),
        )
    )

    assert [step.operator for step in plan.steps] == [
        "HEAP_SCAN",
        "EXTERNAL_HASH_JOIN",
    ]

    assert plan.steps[1].details["join_type"] == "inner"


def test_non_equi_join_falls_back_to_nested_loop():
    planner = QueryPlanner()

    plan = planner.plan(
        QuerySpec(
            table="a",
            joins=(
                JoinSpec(
                    table="b",
                    left_column="x",
                    right_column="y",
                    operator="<",
                ),
            ),
        )
    )

    assert plan.steps[-1].operator == "NESTED_LOOP_JOIN"


def test_join_breaks_order_and_requires_external_sort():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_salary",
                "employees",
                "salary",
                "bplus_clustered",
            )
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="employees",
            order_by=(OrderBy("salary"),),
            joins=(
                JoinSpec(
                    table="departments",
                    left_column="dept_id",
                    right_column="id",
                ),
            ),
        )
    )

    operators = [step.operator for step in plan.steps]

    assert operators == [
        "BPLUS_CLUSTERED_INDEX_SCAN",
        "EXTERNAL_HASH_JOIN",
        "EXTERNAL_SORT",
    ]


def test_residual_predicate_is_added_after_index_lookup():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_id",
                "users",
                "id",
                "hash",
            )
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="users",
            predicates=(
                Predicate("id", "=", 10),
                Predicate("active", "=", True),
            ),
        )
    )

    assert plan.steps[0].operator == "HASH_INDEX_LOOKUP"
    assert plan.steps[1].operator == "FILTER"

    residual = plan.steps[1].details["predicates"]

    assert residual == [
        {
            "column": "active",
            "operator": "=",
            "value": True,
        }
    ]


def test_single_index_predicate_does_not_add_filter():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_id",
                "users",
                "id",
                "hash",
            )
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="users",
            predicates=(Predicate("id", "=", 10),),
        )
    )

    assert len(plan.steps) == 1
    assert plan.steps[0].operator == "HASH_INDEX_LOOKUP"


def test_mapping_query_is_coerced():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_age",
                "users",
                "age",
                "bplus_clustered",
            )
        ]
    )

    plan = planner.plan(
        {
            "table": "users",
            "predicates": [
                ("age", ">=", 18),
            ],
            "order_by": [
                ("age", "asc"),
            ],
        }
    )

    assert plan.access_path == "BPLUS_CLUSTERED_RANGE_SCAN"
    assert "EXTERNAL_SORT" not in [
        step.operator for step in plan.steps
    ]


def test_register_index_and_storage():
    planner = QueryPlanner()

    planner.register_storage("users", "sequential")
    planner.register_index(
        IndexMetadata(
            "idx_id",
            "users",
            "id",
            "hash",
        )
    )

    plan = planner.plan(
        QuerySpec(
            table="users",
            predicates=(Predicate("id", "=", 1),),
        )
    )

    assert plan.access_path == "HASH_INDEX_LOOKUP"


def test_query_plan_to_dict():
    planner = QueryPlanner()

    plan = planner.plan(QuerySpec(table="users"))
    data = plan.to_dict()

    assert data["table"] == "users"
    assert data["planner_type"] == "rule_based"
    assert data["access_path"] == "HEAP_SCAN"
    assert data["steps"][0]["operator"] == "HEAP_SCAN"


def test_query_plan_explain_contains_real_plan_information():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_id_hash",
                "users",
                "id",
                "hash",
                unique=True,
            )
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="users",
            predicates=(Predicate("id", "=", 7),),
        )
    )

    explanation = plan.explain()

    assert "Planner: rule_based" in explanation
    assert "Table: users" in explanation
    assert "Access path: HASH_INDEX_LOOKUP" in explanation
    assert "idx_id_hash" in explanation


def test_invalid_index_kind():
    with pytest.raises(ValueError, match="unsupported index kind"):
        IndexMetadata(
            "bad",
            "users",
            "id",
            "bitmap",
        )


def test_invalid_storage_kind():
    planner = QueryPlanner()

    with pytest.raises(ValueError, match="storage_kind"):
        planner.register_storage("users", "columnar")


def test_invalid_predicate_operator():
    planner = QueryPlanner()

    with pytest.raises(ValueError, match="unsupported predicate operator"):
        planner.plan(
            QuerySpec(
                table="users",
                predicates=(Predicate("id", "like", "%x%"),),
            )
        )


def test_invalid_between_value():
    planner = QueryPlanner()

    with pytest.raises(ValueError, match="BETWEEN"):
        planner.plan(
            QuerySpec(
                table="users",
                predicates=(Predicate("age", "between", 18),),
            )
        )


def test_invalid_join_type():
    planner = QueryPlanner()

    with pytest.raises(ValueError, match="unsupported join type"):
        planner.plan(
            QuerySpec(
                table="a",
                joins=(
                    JoinSpec(
                        table="b",
                        left_column="id",
                        right_column="id",
                        join_type="cross",
                    ),
                ),
            )
        )


def test_missing_table_is_rejected():
    planner = QueryPlanner()

    with pytest.raises(ValueError, match="query.table"):
        planner.plan(QuerySpec(table=""))


def test_hash_equality_beats_bplus_even_if_order_by_matches_bplus():
    planner = QueryPlanner(
        indexes=[
            IndexMetadata(
                "idx_id_hash",
                "users",
                "id",
                "hash",
            ),
            IndexMetadata(
                "idx_id_bplus",
                "users",
                "id",
                "bplus_clustered",
            ),
        ]
    )

    plan = planner.plan(
        QuerySpec(
            table="users",
            predicates=(Predicate("id", "=", 10),),
            order_by=(OrderBy("id"),),
        )
    )

    # Hash exact lookup remains the selected access path.
    # ORDER BY sobre la misma columna de igualdad no requiere sort:
    # todas las filas encontradas tienen id = 10.
    assert plan.access_path == "HASH_INDEX_LOOKUP"
    assert [step.operator for step in plan.steps] == [
        "HASH_INDEX_LOOKUP",
    ]
