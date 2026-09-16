import sys
import time
from pathlib import Path
import pandas as pd
import streamlit as st

# Configurar path raíz para importar módulos del backend
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from query.query_planner import IndexMetadata, QueryPlanner
from query.sql_parser import SQLParser, SQLParseError, SelectStatement

st.set_page_config(
    page_title="BD2 Engine Studio",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilos CSS personalizados para enriquecer la presentación visual
st.markdown(
    """
    <style>
        .main-header {
            font-size: 2.1rem;
            font-weight: 700;
            color: #1E293B;
            margin-bottom: 0.2rem;
        }
        .metric-card {
            background-color: #F8FAFC;
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            padding: 12px;
            margin-bottom: 10px;
        }
        .badge-heap {
            background-color: #FEF3C7;
            color: #92400E;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 600;
        }
        .badge-seq {
            background-color: #DBEAFE;
            color: #1E40AF;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.8rem;
            font-weight: 600;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def init_catalog_engine():
    planner = QueryPlanner()
    # Registro de tablas en disco y estructuras de acceso secundarias
    planner.register_storage("users", "heap")
    planner.register_storage("employees", "sequential")
    planner.register_storage("departments", "heap")

    planner.register_index(IndexMetadata("idx_users_id_hash", "users", "id", "hash", unique=True))
    planner.register_index(IndexMetadata("idx_emp_salary_bplus", "employees", "salary", "bplus_clustered"))
    planner.register_index(IndexMetadata("idx_emp_dept_bplus", "employees", "dept", "bplus_unclustered"))
    parser = SQLParser()
    return planner, parser


planner, parser = init_catalog_engine()

# ==============================================================================
# PANEL 1: ARCHIVOS, ESQUEMAS Y ALMACENAMIENTO FÍSICO (Issue #20)
# ==============================================================================
with st.sidebar:
    st.markdown("###  Catálogo Físico & Esquemas")
    st.caption("Inspección de almacenamiento y metadatos en disco")

    tables_catalog = {
        "users": {
            "tipo": "Heap File",
            "badge": "badge-heap",
            "archivo_datos": "storage/data/users.dat",
            "archivo_free": "storage/data/users.free",
            "columnas": [
                {"col": "id", "tipo": "INT", "key": "PK / Unique"},
                {"col": "name", "tipo": "VARCHAR(32)", "key": "-"},
                {"col": "age", "tipo": "INT", "key": "-"},
                {"col": "active", "tipo": "BOOL", "key": "-"},
            ],
            "indices": [
                {"nombre": "idx_users_id_hash", "col": "id", "tipo": "Extendible Hashing (D={1..n})"}
            ],
        },
        "employees": {
            "tipo": "Sequential File",
            "badge": "badge-seq",
            "archivo_datos": "storage/data/employees.main",
            "archivo_aux": "storage/data/employees.aux",
            "columnas": [
                {"col": "id", "tipo": "INT", "key": "PK"},
                {"col": "dept", "tipo": "VARCHAR(24)", "key": "FK"},
                {"col": "salary", "tipo": "FLOAT", "key": "-"},
            ],
            "indices": [
                {"nombre": "idx_emp_salary_bplus", "col": "salary", "tipo": "B+ Tree (Clustered)"},
                {"nombre": "idx_emp_dept_bplus", "col": "dept", "tipo": "B+ Tree (Unclustered)"},
            ],
        },
        "departments": {
            "tipo": "Heap File",
            "badge": "badge-heap",
            "archivo_datos": "storage/data/departments.dat",
            "archivo_free": "storage/data/departments.free",
            "columnas": [
                {"col": "id", "tipo": "INT", "key": "PK"},
                {"col": "name", "tipo": "VARCHAR(32)", "key": "-"},
            ],
            "indices": [],
        },
    }

    selected_table = st.selectbox("Tabla activa:", list(tables_catalog.keys()))
    t_info = tables_catalog[selected_table]

    st.markdown(
        f"Estructura: <span class='{t_info['badge']}'>{t_info['tipo']}</span>",
        unsafe_allow_html=True,
    )
    st.text(f"Ficheros: {t_info['archivo_datos']}")

    with st.expander("Ver Esquema y Atributos", expanded=True):
        schema_df = pd.DataFrame(t_info["columnas"])
        st.dataframe(schema_df, hide_index=True, use_container_width=True)

    with st.expander("Índices Secundarios Activos", expanded=False):
        if t_info["indices"]:
            st.dataframe(pd.DataFrame(t_info["indices"]), hide_index=True, use_container_width=True)
        else:
            st.info("Sin índices secundarios asignados.")

    st.divider()
    st.markdown("####  Consultas Prediseñadas")
    quick_queries = {
        "Búsqueda Hash exacta": "SELECT * FROM users WHERE id = 10",
        "Rango con B+ Clustered": "SELECT * FROM employees WHERE salary >= 3200 ORDER BY salary ASC",
        "Agrupamiento Hash": "SELECT dept, salary FROM employees GROUP BY dept",
        "Equi-JOIN Externo": "SELECT * FROM employees JOIN departments ON employees.dept = departments.name",
        "Inserción DML": "INSERT INTO users VALUES (11, 'Elena Gomez', 29, True)",
    }
    selected_sample = st.selectbox("Cargar caso de uso:", list(quick_queries.keys()))
    if st.button("Transferir al Editor SQL", use_container_width=True):
        st.session_state["active_query"] = quick_queries[selected_sample]

# ==============================================================================
# ENCABEZADO Y PANEL 2: EDITOR DE CONSULTAS SQL (Issue #21)
# ==============================================================================
st.markdown("<div class='main-header'>Motor Relacional & Optimizador de Consultas</div>", unsafe_allow_html=True)
st.caption("Proyecto Base de Datos 2 - Arquitectura de Almacenamiento, Indexación y Consulta")

default_sql = st.session_state.get("active_query", "SELECT * FROM employees WHERE salary >= 3000 ORDER BY salary ASC")
query_text = st.text_area("Sentencia SQL a procesar:", value=default_sql, height=95)

c_exec, c_clear, c_space = st.columns([2, 1, 7])
with c_exec:
    run_query = st.button("Procesar Consulta", type="primary", use_container_width=True)
with c_clear:
    if st.button("Limpiar", use_container_width=True):
        st.session_state["active_query"] = ""
        st.rerun()

# Lógica de Ejecución y Planificación
parsed_obj = None
execution_plan = None
execution_error = None
elapsed_time_ms = 0.0

if run_query and query_text.strip():
    start_t = time.perf_counter()
    try:
        parsed_obj = parser.parse(query_text.strip())
        if isinstance(parsed_obj, SelectStatement):
            execution_plan = planner.plan(parsed_obj.query_spec)
        elapsed_time_ms = (time.perf_counter() - start_t) * 1000
    except (SQLParseError, ValueError, TypeError) as err:
        execution_error = str(err)
        elapsed_time_ms = (time.perf_counter() - start_t) * 1000

# ==============================================================================
# PANELES 3 Y 4: RESULTADOS Y PLAN DE EJECUCIÓN (Issues #22 y #23)
# ==============================================================================
tab_results, tab_plan, tab_raw = st.tabs([
    "Panel de Resultados (Issue #22)",
    "Plan de Ejecución Optimizado (Issue #23)",
    "Estructura AST (Parser)",
])

# PANEL 3: RESULTADOS
with tab_results:
    if execution_error:
        st.error(f"**Fallo en la resolución:** {execution_error}")
    elif run_query and parsed_obj:
        st.success(f"Ejecución completada en **{elapsed_time_ms:.2f} ms**")

        if isinstance(parsed_obj, SelectStatement):
            # =========================================================================
            # INTEGRACIÓN CON BACKEND (CUANDO QUERY EXECUTOR ESTÉ LISTO):
            #
            # 1. Importar el ejecutor arriba en los imports:
            #    from query.query_executor import QueryExecutor
            #
            # 2. Reemplazar la lista de mock_records por la llamada real al motor:
            #    executor = QueryExecutor(storage_engine=planner.storage_catalog)
            #    result_tuples = executor.execute(execution_plan)
            #    res_df = pd.DataFrame(result_tuples)
            # =========================================================================

            # --- MOCK TEMPORAL PARA DEMOSTRACIÓN VISUAL Y PRUEBAS DEL FRONTEND ---
            mock_records = [
                {"id": 101, "dept": "IT", "salary": 4800.0, "name": "Carlos M."},
                {"id": 102, "dept": "HR", "salary": 3200.0, "name": "Valeria S."},
                {"id": 103, "dept": "IT", "salary": 5300.0, "name": "Fernando T."},
                {"id": 104, "dept": "Finance", "salary": 3900.0, "name": "Lucía P."},
            ]
            res_df = pd.DataFrame(mock_records)

            if parsed_obj.columns != ("*",):
                cols = [c for c in parsed_obj.columns if c in res_df.columns]
                if cols:
                    res_df = res_df[cols]

            m1, m2, m3 = st.columns(3)
            m1.metric("Registros Recuperados", len(res_df))
            m2.metric("Páginas Evaluadas (I/O)", "2 bloques")
            m3.metric("Tiempo de Escaneo", f"{elapsed_time_ms:.3f} ms")

            st.dataframe(res_df, use_container_width=True)
        else:
            st.info("Comando de mutación procesado exitosamente en búfer de almacenamiento.")
    else:
        st.info("Ingresa una consulta SQL o selecciona un ejemplo para ver la ejecución tabular.")


# PANEL 4: PLAN DE EJECUCIÓN
with tab_plan:
    if execution_plan:
        st.markdown("### Estrategia de Acceso Seleccionada")
        p_col1, p_col2, p_col3 = st.columns(3)
        p_col1.metric("Ruta Primaria", execution_plan.access_path)
        p_col2.metric("Optimizador", execution_plan.planner_type)
        idx_label = ", ".join(execution_plan.used_indexes) if execution_plan.used_indexes else "Ninguno (Scan secuencial)"
        p_col3.metric("Índice(s) Utilizado(s)", idx_label)

        st.markdown("#### Explicación Formal (`explain`)")
        st.code(execution_plan.explain(), language="yaml")

        st.markdown("#### Secuencia Operativa del Motor")
        plan_dict = execution_plan.to_dict()
        steps_df = pd.DataFrame(plan_dict["steps"])
        st.dataframe(steps_df, use_container_width=True, hide_index=True)
    elif execution_error:
        st.warning("No fue posible compilar un plan de ejecución.")
    else:
        st.info("El planificador de consultas desplegará aquí la secuencia de operadores tras pulsar 'Procesar Consulta'.")

# PESTAÑA EXTRA: INSPECCIÓN DEL PARSER
# PESTAÑA EXTRA: INSPECCIÓN DEL PARSER
from dataclasses import asdict

with tab_raw:
    if parsed_obj:
        st.markdown("#### Árbol Sintáctico (AST)")
        st.json(asdict(parsed_obj))
    else:
        st.caption("Sin objeto AST en memoria.")