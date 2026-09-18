# Proyecto BD2 — Minigestor de Base de Datos Multimodal

Motor de base de datos construido **desde cero en Python** (solo librería estándar) con
almacenamiento paginado en disco, índices B+ y Hash, algoritmos externos, procesamiento
SQL, transacciones con locks y una interfaz web de 4 paneles.

> **Curso:** Base de Datos 2 — Ciclo 2026-2
> **Institución:** Universidad de Ingeniería y Tecnología (UTEC)
> **Entrega actual:** Avance 1 (Semana 6) — **Parte 1: Base de Datos Relacional completa**

---

## Tabla de contenido

1. [Descripción](#1-descripción)
2. [Estado del avance](#2-estado-del-avance)
3. [Integrantes y responsabilidades](#3-integrantes-y-responsabilidades)
4. [Arquitectura del sistema](#4-arquitectura-del-sistema)
5. [Organización del código fuente (arquetipo)](#5-organización-del-código-fuente-arquetipo)
6. [Modelo de datos de demostración](#6-modelo-de-datos-de-demostración)
7. [Módulos de la Parte 1](#7-módulos-de-la-parte-1)
8. [Manual de instalación y ejecución](#8-manual-de-instalación-y-ejecución)
9. [Subconjunto SQL soportado](#9-subconjunto-sql-soportado)
10. [API REST del motor](#10-api-rest-del-motor)
11. [Pruebas](#11-pruebas)
12. [Experimentos y resultados](#12-experimentos-y-resultados)
13. [Flujo de trabajo con Git e issues](#13-flujo-de-trabajo-con-git-e-issues)
14. [Roadmap: Partes 2 a 5](#14-roadmap-partes-2-a-5)
15. [Documentación de apoyo](#15-documentación-de-apoyo)

---

## 1. Descripción

El proyecto consiste en un **gestor de base de datos multimodal** implementado de forma
progresiva. La **Parte 1** (este avance) cubre el núcleo relacional:

- almacenamiento físico en disco (**Heap File** y **Archivo Secuencial Paginado**),
- indexación (**B+ agrupado**, **B+ no agrupado** y **Hash Extendible**),
- algoritmos externos (**External Sort** para `ORDER BY`, **External Hashing** para
  `GROUP BY` y `JOIN`),
- procesamiento de consultas (**parser SQL**, **query planner** basado en reglas y
  **ejecutor**),
- transacciones y concurrencia (**BEGIN/END TRANSACTION** y **LockManager** con
  demostración multihilo),
- una **interfaz gráfica de 4 paneles** (archivos, consultas, resultados y plan de
  ejecución), construida en React sobre un API REST en FastAPI,
- la **comparación experimental** de todas las técnicas implementadas.

Todo el motor usa **únicamente la librería estándar de Python**. Los paquetes externos
solo se necesitan para las pruebas (`pytest`), las gráficas (`matplotlib`) y el puente
HTTP hacia la interfaz (`fastapi`, `uvicorn`).

---

## 2. Estado del avance

| Bloque del enunciado | Estado | Ubicación |
|---|---|---|
| 2.1.1 Gestión de archivos y almacenamiento | ✅ Completo | `storage/` |
| 2.1.2 Indexación y optimización | ✅ Completo | `indexes/`, `operators/` |
| 2.1.3 Procesamiento de consultas SQL | ✅ Completo | `query/` |
| 2.1.4 Transacciones y concurrencia | ✅ Completo | `transactions/` |
| 2.1.5 Interfaz de usuario (frontend) | ✅ Completo | `backend/`, `frontend/` |
| 2.1.6 Comparación experimental | ✅ Completo | `benchmarks/`, `benchmark_results/`, `docs/` |
| Documentación técnica (README) | ✅ Este documento | `README.md` |
| Informe incremental | 🚧 En elaboración | `docs/` |

Las Partes 2 a 5 (espacial, texto, multimedia y aplicación con IA) están planificadas en
la sección [14](#14-roadmap-partes-2-a-5).

---

## 3. Integrantes y responsabilidades

| Integrante (GitHub) | Módulos a cargo |
|---|---|
| [@tamitooo](https://github.com/tamitooo) | `storage/` (base), `transactions/` (BEGIN/END, LockManager, demo de concurrencia), revisión de PRs |
| [@SebastianLoli](https://github.com/sebastianloli) | `indexes/` (B+ agrupado, B+ no agrupado, Hash Extendible), `operators/` (External Sort y External Hashing), `query/query_planner.py` |
| [@Badi-Rodriguez](https://github.com/Badi-Rodriguez) | `query/sql_parser.py`, `query/catalog.py`, `query/query_executor.py`, `query/query_result.py` |
| [@dillescas01](https://github.com/dillescas01) | `benchmarks/`, `benchmark_results/`, `docs/` experimentales, `examples/demo_parte1.py`, pruebas end-to-end |
| [@FabricioBautista](https://github.com/FabricioBautista) | `query/sql_parser.py` (versión inicial), `backend/` (API REST), `frontend/` (React), `README.md`, informe |

---

## 4. Arquitectura del sistema

### 4.1 Vista de capas

```
┌───────────────────────────────────────────────────────────────────────────┐
│                    FRONTEND — React 19 + Vite + TypeScript                │
│                       (http://localhost:5173)                             │
│  ┌───────────────┬────────────────┬─────────────────┬──────────────────┐  │
│  │ Panel de      │ Panel de       │ Panel de        │ Panel de plan    │  │
│  │ archivos (#20)│ consultas (#21)│ resultados (#22)│ de ejecución(#23)│  │
│  └───────────────┴────────────────┴─────────────────┴──────────────────┘  │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   │  HTTP + JSON  (proxy /api → :8000)
┌──────────────────────────────────▼────────────────────────────────────────┐
│                     API REST — FastAPI   (backend/api.py)                 │
│      GET /api/health   GET /api/tables   GET /api/tables/{name}           │
│      POST /api/query   (documentación interactiva en /docs)               │
│                     backend/engine.py → Catalog + QueryExecutor           │
└──────────────────────────────────┬────────────────────────────────────────┘
                                   │  llamadas Python directas (sin red)
┌──────────────────────────────────▼────────────────────────────────────────┐
│                         MOTOR DE BASE DE DATOS (Python stdlib)            │
│                                                                           │
│   query/sql_parser.py ──► query/query_planner.py ──► query/query_executor │
│            │                       │                          │           │
│            │              indexes/ (B+ agrupado, B+ no agrupado,          │
│            │                        Hash Extendible)          │           │
│            │              operators/ (External Sort,          │           │
│            │                          External Hashing)       │           │
│            │                                                  │           │
│            └──────────────► storage/ (Heap File, Archivo Secuencial) ◄────┘
│                             transactions/ (BEGIN/END, LockManager)        │
└───────────────────────────────────────────────────────────────────────────┘
```

### 4.2 Flujo de una consulta

1. El usuario escribe SQL en el **panel de consultas** (React).
2. El frontend hace `POST /api/query` con `{ "sql": "..." }`; el proxy de Vite lo
   redirige a `http://127.0.0.1:8000`.
3. `backend/engine.py` entrega el texto al **`QueryExecutor`**.
4. El **parser** (`query/sql_parser.py`) construye el AST: `SelectStatement`,
   `InsertStatement` o `DeleteStatement`, con un `QuerySpec` (tabla, predicados,
   `GROUP BY`, `ORDER BY`, joins).
5. El **planner** (`query/query_planner.py`) elige la ruta de acceso comparando
   candidatos: `HASH_INDEX_LOOKUP` (igualdad con Hash Extendible),
   `BPLUS_CLUSTERED_LOOKUP` / `BPLUS_UNCLUSTERED_LOOKUP` (igualdad con B+),
   `BPLUS_CLUSTERED_RANGE_SCAN` / `BPLUS_UNCLUSTERED_RANGE_SCAN` (rango),
   `BPLUS_*_INDEX_SCAN` (`ORDER BY` cubierto por el índice, evita el `External Sort`)
   o `HEAP_SCAN` / `SEQUENTIAL_SCAN` como respaldo.
6. El **ejecutor** (`query/query_executor.py`) resuelve la tabla contra el **`Catalog`**,
   lee del almacenamiento físico, aplica índices y operadores externos, y devuelve un
   `QueryResult`.
7. El `QueryResult` se serializa con `to_dict()` y React pinta los **resultados** y el
   **plan de ejecución** (plan lógico + traza de ejecución real con tiempos).

### 4.3 Decisiones de diseño relevantes

- **Contrato de respuesta estable.** `QueryResult` (`query/query_result.py`) expone
  `success`, `statement`, `columns`, `rows` (diccionarios), `affected_rows`,
  `execution_time_ms`, `execution_plan` y `error`. El frontend nunca conoce RIDs,
  páginas ni estructuras físicas; por eso el mismo contrato sirve para una API REST o
  GraphQL futura.
- **El planner es basado en reglas y explicable.** Cada paso del plan lleva `reason`
  (justificación en lenguaje natural) y `details` (predicado, tipo de índice, columna),
  lo que permite mostrar *por qué* se eligió cada ruta (issue #23).
- **Reorganización del Archivo Secuencial e índices.** `reorganizar()` reescribe
  `.main` completo, por lo que **todos los RID cambian**; después de reorganizar hay que
  reconstruir los índices (`Catalog.rebuild_indexes()`). El ejecutor lo hace cuando la
  inserción dispara una reorganización.
- **Serialización de acceso concurrente en el API.** Aunque el motor soporta
  transacciones y locks, el API web atiende peticiones en un *threadpool*; por eso
  `DemoEngine.run()` toma un `threading.Lock` antes de ejecutar cada sentencia y así
  evita corromper archivos desde dos peticiones simultáneas.
- **Dos ejecutores en el repositorio.** `query/query_executor.py` es la **ruta de
  integración vigente** (la que usa el API y la interfaz). `query/executor.py` es el
  ejecutor end-to-end anterior (PR #37) que siguen usando `examples/demo_parte1.py` y
  `tests/test_end_to_end.py`; se mantiene para no romper la suite de la Parte 1.

---

## 5. Organización del código fuente (arquetipo)

```
Proyecto-BD2/
├── storage/                     # 2.1.1 Gestión de archivos y almacenamiento
│   ├── record.py                #   Schema, Field y serialización binaria de tamaño fijo
│   ├── heap_file.py             #   Heap File paginado + free-list (.free) para reutilizar espacio
│   └── sequential_file.py       #   Archivo Secuencial Paginado (.main/.aux), borrado lazy y reorganización
│
├── indexes/                     # 2.1.2 Estructuras de indexación
│   ├── bplus_tree.py            #   B+ Tree base (split, merge, recorrido ordenado)
│   ├── clustered_bplus.py       #   B+ agrupado (hojas con el registro completo)
│   ├── unclustered_bplus.py     #   B+ no agrupado (hojas con clave + RID)
│   └── extendible_hash.py       #   Hash Extendible (directorio, split de buckets, profundidad)
│
├── operators/                   # 2.1.2 Algoritmos externos
│   ├── external_sort.py         #   ORDER BY por k-way merge con runs en disco
│   └── external_hashing.py      #   GROUP BY y JOIN por particionado en disco
│
├── query/                       # 2.1.3 Procesamiento de consultas SQL
│   ├── sql_parser.py            #   Parser SQL (SELECT/INSERT/DELETE, WHERE/GROUP BY/ORDER BY/JOIN)
│   ├── query_planner.py         #   Optimizador basado en reglas + estructura del plan
│   ├── catalog.py               #   Registro de tablas, esquemas e índices en tiempo de ejecución
│   ├── query_executor.py        #   Ejecutor SQL sobre storage + índices + operadores  ← ruta vigente
│   ├── query_result.py          #   Contrato de respuesta serializable a JSON
│   ├── executor.py              #   Ejecutor end-to-end anterior (legado, usado por examples/ y tests e2e)
│   └── test_query_executor.py   #   Pruebas del ejecutor y del contrato del frontend
│
├── transactions/                # 2.1.4 Transacciones y concurrencia
│   ├── transaction_manager.py   #   BEGIN TRANSACTION / END TRANSACTION
│   ├── lock_manager.py          #   Locks compartidos/exclusivos, crecimiento y detección de conflictos
│   └── demo_concurrencia.py     #   Demostración con hilos: race conditions y su resolución
│
├── backend/                     # 2.1.5 Integración motor ↔ interfaz (API REST)
│   ├── api.py                   #   Endpoints FastAPI
│   ├── engine.py                #   Catálogo de demo, índices e instancia del QueryExecutor
│   └── data/                    #   Archivos de datos de la demo (ignorado por Git)
│
├── frontend/                    # 2.1.5 Interfaz de usuario (React + Vite + TypeScript)
│   ├── src/App.tsx              #   Composición de la pantalla y estado global
│   ├── src/api.ts               #   Cliente HTTP del API
│   ├── src/types.ts             #   Tipos del contrato (QueryResult, ExecutionPlan, TableInfo…)
│   ├── src/panels/              #   FilesPanel, QueryPanel, ResultsPanel, PlanPanel
│   ├── src/styles.css           #   Hoja de estilos del layout de 4 paneles
│   └── vite.config.ts           #   Proxy /api → http://127.0.0.1:8000
│
├── benchmarks/                  # 2.1.6 Comparación experimental
│   ├── benchmark_heap_vs_sequential.py   # Heap File vs Archivo Secuencial
│   ├── benchmark_indexes.py              # B+ agrupado vs B+ no agrupado vs Hash
│   └── generate_charts.py                # Gráficas PNG a partir de los CSV/JSON
│
├── benchmark_results/           # CSVs, JSONs y plots/*.png de los experimentos
├── docs/                        # Documentación de apoyo (ventajas/desventajas y conclusiones)
├── examples/demo_parte1.py      # Demo end-to-end de la Parte 1 por consola
├── tests/                       # 17 archivos de prueba (unitarias, integración y end-to-end)
├── conftest.py                  # Configuración de pytest (raíz del proyecto en sys.path)
├── requirements.txt             # Dependencias (pruebas, gráficas y API)
└── README.md                    # Este documento
```

---

## 6. Modelo de datos de demostración

La interfaz trabaja sobre tres tablas registradas en `backend/engine.py`, elegidas para
que se vean **las dos técnicas de almacenamiento y las tres de indexación**:

| Tabla | Almacenamiento | Clave primaria | Columnas | Índices |
|---|---|---|---|---|
| `users` | **Heap File** (`users.dat` + `.free`) | `id` | `id INT`, `name VARCHAR(32)`, `age INT`, `dept VARCHAR(16)` | `idx_users_id_hash` → **Hash Extendible** (único) |
| `employees` | **Archivo Secuencial Paginado** (`employees.main` / `.aux`) | `id` | `id INT`, `name VARCHAR(32)`, `dept VARCHAR(16)`, `salary FLOAT` | `idx_emp_salary_bplus` → **B+ agrupado**; `idx_emp_dept_bplus` → **B+ no agrupado** |
| `departments` | **Heap File** (`departments.dat`) | `id` | `id INT`, `name VARCHAR(32)`, `city VARCHAR(24)` | — |

> El esquema solo soporta `INT`, `FLOAT` y `VARCHAR(n)` (ver `storage/record.py`); no
> existe el tipo `BOOL`.
>
> Los datos de ejemplo se cargan automáticamente la primera vez que arranca el API y
> viven en `backend/data/` (ignorado por Git). Para reiniciar la demo basta con borrar
> esa carpeta.

---

## 7. Módulos de la Parte 1

### 7.1 Almacenamiento (`storage/`)

**Heap File** (`heap_file.py`)
- Páginas de tamaño fijo; cada página contiene `PAGE_SIZE // record_size` slots.
- Inserción en el primer slot libre; **free-list** persistida en un archivo `.free`
  (`pickle`) con las páginas que tienen huecos.
- Borrado por *tombstone* (marca `FLAG_DELETED`), reutilización de slots en línea.
- API: `insert`, `read`, `update`, `delete`, `scan`, `espacio_utilizado_bytes`.

**Archivo Secuencial Paginado** (`sequential_file.py`)
- Archivo **principal** `.main` siempre ordenado por clave primaria.
- Área de desbordamiento `.aux` para inserciones nuevas, con **borrado lazy**
  (tombstones) y búsqueda binaria sobre `.main`.
- **Reorganización** al superar el **30 % de espacio desperdiciado**, que reescribe
  `.main` compactado.
- API: `insert`, `search` (búsqueda binaria sobre `.main`), `range_search`, `delete`,
  `reorganizar`, `scan`, `espacio_utilizado_bytes`.

**Registros** (`record.py`)
- `Schema` + `Field`: serialización binaria de tamaño fijo con `struct`, flag por
  registro (`EMPTY`, `USED`, `DELETED`) y `to_dict()`/`from_dict()` para el catálogo.

### 7.2 Indexación (`indexes/`)

- **B+ Tree base** (`bplus_tree.py`): orden configurable, split/merge y recorrido
  ordenado por las hojas.
- **B+ agrupado** (`clustered_bplus.py`): las hojas almacenan el registro completo;
  permite que el planner **evite el External Sort** en `ORDER BY` sobre esa clave.
- **B+ no agrupado** (`unclustered_bplus.py`): hojas con `(clave, RID)`; ideal para
  igualdad **y** rango sin el costo de copiar registros.
- **Hash Extendible** (`extendible_hash.py`): directorio con profundidad global/local,
  split incremental de buckets, `O(1)` promedio en igualdad, sin soporte de rangos.

### 7.3 Algoritmos externos (`operators/`)

- **External Sort** (`external_sort.py`): genera *runs* ordenados que caben en memoria y
  los fusiona con **k-way merge**, con limpieza de archivos temporales. Se usa cuando el
  `ORDER BY` no puede resolverse con un índice.
- **External Hashing** (`external_hashing.py`): particionado en disco por función hash y
  procesamiento partición a partición para **GROUP BY** y **equi-JOIN** con memoria
  acotada.

### 7.4 Procesamiento SQL (`query/`)

| Etapa | Archivo | Responsabilidad |
|---|---|---|
| Parser | `sql_parser.py` | Tokeniza y valida la sentencia, construye el AST y el `QuerySpec` |
| Planner | `query_planner.py` | Compara candidatos de acceso y emite el plan con `reason` y `details` |
| Catálogo | `catalog.py` | Asocia nombres SQL con `HeapFile`/`SequentialFile` y sus índices |
| Ejecutor | `query_executor.py` | Ejecuta el AST: acceso, filtros, joins, agrupación, orden, proyección, DML |
| Contrato | `query_result.py` | Resultado serializable (`to_dict()`) para el frontend |

Mensajes de error claros y sin excepciones hacia el API: si algo falla, el `QueryResult`
vuelve con `success = false` y un texto legible para el panel de resultados.

### 7.5 Transacciones y concurrencia (`transactions/`)

- `transaction_manager.py`: `BEGIN TRANSACTION` / `END TRANSACTION` agrupando
  operaciones.
- `lock_manager.py`: locks **compartidos y exclusivos** por recurso, con crecimiento de
  locks y detección de conflictos.
- `demo_concurrencia.py`: simulación con **hilos** que muestra varias transacciones
  ejecutándose a la vez, una *race condition* y cómo el sistema la resuelve.

### 7.6 Interfaz de usuario e integración (`backend/` + `frontend/`)

Los 4 paneles exigidos por el enunciado (2.1.5):

| Panel | Issue | Qué muestra |
|---|---|---|
| **Archivos** | #20 | Tablas registradas, tipo de almacenamiento (Heap/Secuencial), archivos `.dat`/`.free` y `.main`/`.aux` con su tamaño, esquema con PK, índices con su técnica y cantidad de registros |
| **Consultas** | #21 | Editor SQL con ejemplos por caso de uso, ejecución con botón o `Ctrl+Enter` y mensajes de error del parser |
| **Resultados** | #22 | Tabla dinámica con las columnas devueltas, filas, filas afectadas (INSERT/DELETE), tiempo de ejecución y vista JSON cruda |
| **Plan de ejecución** | #23 | Ruta de acceso elegida, índices utilizados, optimizador, plan lógico con justificación y traza real de operadores con tiempos y filas |

---

## 8. Manual de instalación y ejecución

### 8.1 Requisitos

| Herramienta | Versión | Necesaria para |
|---|---|---|
| Python | 3.10 o superior (probado con 3.13) | Motor, pruebas y API |
| pip | incluido con Python | Dependencias |
| Node.js | 20.19 o superior (probado con 24) | Frontend React |
| npm | 10 o superior | Dependencias del frontend |
| Navegador moderno | — | Interfaz |

El motor **no requiere ninguna dependencia externa**: `pytest`, `matplotlib`, `fastapi` y
`uvicorn` solo son necesarios para pruebas, gráficas y el API.

### 8.2 Instalación

```bash
# 1) Clonar
git clone https://github.com/tamitooo/Proyecto-BD2.git
cd Proyecto-BD2

# 2) Entorno virtual de Python
python -m venv venv
venv\Scripts\activate            # Windows (PowerShell / CMD)
# source venv/bin/activate       # Linux / macOS

# 3) Dependencias de Python
pip install -r requirements.txt

# 4) Dependencias del frontend
cd frontend
npm install
cd ..
```

### 8.3 Ejecución

**Terminal 1 — API del motor (Python):**

```bash
venv\Scripts\activate
python -m uvicorn backend.api:app --reload --port 8000
# Documentación interactiva: http://127.0.0.1:8000/docs
```

**Terminal 2 — Interfaz web (React):**

```bash
cd frontend
npm run dev
# Abrir http://localhost:5173
```

El proxy definido en `frontend/vite.config.ts` redirige `/api` a
`http://127.0.0.1:8000`, por lo que **ambos procesos deben estar corriendo**.

**Demo de consola (sin interfaz):**

```bash
python examples/demo_parte1.py                       # recorrido end-to-end de la Parte 1
python -m transactions.demo_concurrencia             # transacciones y race conditions con hilos
```

**Benchmarks y gráficas (opcional, tardan varios minutos):**

```bash
python benchmarks/benchmark_heap_vs_sequential.py --sizes 1000 10000 100000
python -m benchmarks.benchmark_indexes --sizes 1000 10000 100000
python -m benchmarks.generate_charts                 # PNG en benchmark_results/plots/
```

**Pruebas:**

```bash
python -m pytest -q
```

### 8.4 Verificación rápida del API

```bash
# Windows PowerShell
curl.exe http://127.0.0.1:8000/api/health
curl.exe -X POST http://127.0.0.1:8000/api/query -H "Content-Type: application/json" -d "{\"sql\":\"SELECT * FROM users\"}"
```

Respuesta esperada de `/api/query` (contrato del frontend):

```json
{
  "success": true,
  "statement": "SELECT",
  "columns": ["id", "name", "age", "dept"],
  "rows": [{ "id": 1, "name": "Ana Torres", "age": 20, "dept": "CS" }],
  "affected_rows": 1,
  "execution_time_ms": 0.26,
  "execution_plan": {
    "table": "users",
    "planner_type": "rule_based",
    "access_path": "HASH_INDEX_LOOKUP",
    "used_indexes": ["idx_users_id_hash"],
    "steps": [{ "operator": "HASH_INDEX_LOOKUP", "reason": "Extendible Hashing es preferido para igualdad exacta" }],
    "runtime_steps": [{ "operator": "HASH_INDEX_LOOKUP", "elapsed_ms": 0.12, "rows_out": 1 }],
    "total_execution_time_ms": 0.26
  },
  "error": null
}
```

### 8.5 Problemas comunes

| Síntoma | Causa y solución |
|---|---|
| `ModuleNotFoundError: No module named 'storage'` | `uvicorn` se lanzó desde otra carpeta. Ejecútalo **desde la raíz** del repositorio: `python -m uvicorn backend.api:app --port 8000` |
| El frontend muestra *"No se pudo contactar al API"* | El API no está corriendo o está en otro puerto. Levántalo en el `8000`, que es el destino del proxy |
| `EADDRINUSE` / puerto ocupado | Cambia el puerto de Vite (`npm run dev -- --port 5174`) o detén el proceso que usa el 8000 |
| Cambié los datos y quiero empezar de cero | Borra `backend/data/` y reinicia el API (vuelve a cargar los datos de ejemplo) |
| `OR`, `LIMIT` o alias de tabla dan error | No forman parte del subconjunto SQL implementado; ver la sección [9](#9-subconjunto-sql-soportado) |
| `pytest` falla al crear archivos temporales | Ejecuta las pruebas en una carpeta con permisos de escritura y sin antivirus que bloquee `%TEMP%` |

---

## 9. Subconjunto SQL soportado

El enunciado pide "solo lo esencial que dé soporte a las técnicas implementadas". El
parser implementa exactamente:

```sql
SELECT [*|col1, col2, ...] FROM tabla
  [JOIN tabla2 ON tabla.col = tabla2.col]
  [WHERE predicado [AND predicado] ...]
  [GROUP BY col]
  [ORDER BY col [ASC|DESC]]
  [LIMIT n]                 -- no soportado todavía

INSERT INTO tabla VALUES (v1, v2, ...)
DELETE FROM tabla [WHERE predicado [AND predicado] ...]
```

| Característica | Estado | Ejemplo |
|---|---|---|
| `SELECT *` y proyección de columnas | ✅ | `SELECT id, name FROM users` |
| Operadores de comparación | ✅ | `=`, `!=`, `<>`, `<`, `<=`, `>`, `>=` |
| Rangos | ✅ | `WHERE age BETWEEN 19 AND 22` |
| Conjunción de predicados | ✅ `AND` | `WHERE age >= 20 AND dept = 'CS'` |
| Disyunción | ❌ `OR` | — |
| Ordenamiento | ✅ `ASC`/`DESC` | `ORDER BY salary DESC` |
| Agrupación y agregados | ✅ con `GROUP BY` | `SELECT dept, COUNT(*) AS total, AVG(salary) AS prom FROM employees GROUP BY dept` |
| Agregados sin `GROUP BY` | ❌ | `SELECT COUNT(*) FROM users` |
| Equi-JOIN | ✅ igualdad entre columnas, **sin alias** | `SELECT users.name, employees.id FROM users JOIN employees ON users.dept = employees.dept` |
| Alias de tabla (`FROM users u`) | ❌ | — |
| `LIMIT` | ❌ | — |

**Índices utilizables por el planner:** Hash Extendible (igualdad), B+ no agrupado
(igualdad y rango), B+ agrupado (igualdad, rango y `ORDER BY` sin `External Sort`).

Las limitaciones marcadas con ❌ corresponden a los issues abiertos #24–#28 del tablero
del equipo y no afectan a los ejemplos precargados en la interfaz.

---

## 10. API REST del motor

Base: `http://127.0.0.1:8000` · Documentación interactiva (Swagger UI): `/docs`

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/health` | Estado del API y lista de tablas registradas |
| `GET` | `/api/tables` | Catálogo completo: tablas, almacenamiento, esquema, índices, archivos, tamaño y número de registros |
| `GET` | `/api/tables/{name}` | Igual que el anterior para una sola tabla (404 si no existe) |
| `POST` | `/api/query` | Ejecuta una sentencia SQL y devuelve el `QueryResult` completo (nunca lanza excepción) |

Ejemplo de petición:

```bash
curl.exe -X POST http://127.0.0.1:8000/api/query \
  -H "Content-Type: application/json" \
  -d "{\"sql\":\"SELECT dept, COUNT(*) AS total FROM employees GROUP BY dept\"}"
```

---

## 11. Pruebas

La suite contiene **261 funciones de prueba** distribuidas en `tests/` (17 archivos) y
`query/test_query_executor.py`:

| Archivo | Qué verifica |
|---|---|
| `tests/test_record.py` | Serialización y esquema de registros |
| `tests/test_heap_file.py`, `tests/test_sequential_file.py` | Inserción, búsqueda, borrado, reutilización de espacio y reorganización |
| `tests/test_bplus_tree.py`, `tests/test_clustered_bplus.py`, `tests/test_unclustered_bplus.py` | Split, merge, búsqueda, rango y recorrido ordenado de los B+ |
| `tests/test_extendible_hash.py` | Crecimiento del directorio, split de buckets y unicidad |
| `tests/test_external_sort.py`, `tests/test_external_hashing.py` | Orden externo, `GROUP BY`/`JOIN` particionados y limpieza de temporales |
| `tests/test_sql_parser.py` | Sentencias válidas e inválidas del subconjunto SQL |
| `tests/test_query_planner.py` | Elección de ruta de acceso y estructura del plan |
| `query/test_query_executor.py` | Ejecución real (SELECT/INSERT/DELETE, WHERE, ORDER BY, GROUP BY, JOIN) y contrato del frontend |
| `tests/test_storage_integration.py` | Integración almacenamiento + índices (incluye la invalidación de RID al reorganizar) |
| `tests/test_end_to_end.py` | Flujo parser → planner → ejecutor → almacenamiento |
| `tests/test_transactions.py` | Transacciones y locks |
| `tests/test_benchmark_*.py` | Validez metodológica de los benchmarks (carga masiva idéntica a la API pública) |

```bash
python -m pytest -q                                   # suite completa
python -m unittest discover -s tests -t . -v          # alternativa sin pytest
```

---

## 12. Experimentos y resultados

Metodología completa en
[`docs/conclusiones_experimentales.md`](docs/conclusiones_experimentales.md) y tabla de
ventajas/desventajas en
[`docs/comparacion_ventajas_desventajas.md`](docs/comparacion_ventajas_desventajas.md).
Datasets de 1 000, 10 000 y 100 000 registros, semilla fija 42 y 3 repeticiones.

### 12.1 Heap File vs Archivo Secuencial Paginado

| Métrica | Ganador | Evidencia |
|---|---|---|
| Inserción | Empate técnico | ≈ 15 ms/registro en ambos (dominado por el costo de E/S del entorno) |
| Búsqueda por clave primaria | **Archivo Secuencial** | 451 µs frente a 317 507 µs con 100 000 registros → **≈ 700×** (binaria `O(log N)` vs *scan* `O(N)`) |
| Borrado | **Heap File** | 1 950–2 094 µs frente a 12 630–15 640 µs (tombstone + free-list vs posible reorganización) |
| Reorganización | — | Costo lineal: 5.9 ms (1 000) y 36.5 ms (10 000) |
| Espacio | Empate | Heap: 0.03–0.7 % de desperdicio; Secuencial: exacto tras reorganizar, hasta 30 % de tombstones entre reorganizaciones |
| Reutilización de espacio | **Heap File** | 300/300 y 3000/3000 inserciones reutilizaron un slot liberado |

### 12.2 B+ agrupado vs B+ no agrupado vs Hash Extendible (100 000 claves)

| Métrica | B+ agrupado | B+ no agrupado | Hash extendible |
|---|---|---|---|
| Construcción | 14 566 ms | 8 912 ms | **2 760 ms** |
| Igualdad exacta (*hit*) | 13.97 µs | 2.72 µs | **1.58 µs** |
| Búsqueda por rango | 8 456 µs | **949 µs** | no aplica |
| Recorrido ordenado | 949 ms | **131 ms** | no aplica |
| Inserción / borrado | 30.7 / 36.9 µs | 22.6 / 47.6 µs | **1.9 / 7.8 µs** |
| Espacio | 4.71 MB | 1.44 MB | **1.38 MB** |

**Cuándo usar cada estructura:**

- **Hash Extendible** → igualdad exacta con muchas lecturas (el más rápido y el más
  barato de construir).
- **B+ no agrupado** → igualdad **y** rangos sobre la misma columna.
- **B+ agrupado** → `ORDER BY` frecuente sobre la clave de orden físico: es el único que
  permite al planner **evitar** el `External Sort`.
- **External Sort** → `ORDER BY` sin índice disponible; **External Hashing** →
  `GROUP BY` y equi-`JOIN` sobre datasets grandes (`O(N+M)` promedio).

### 12.3 Gráficas

`benchmark_results/plots/`: `storage_dashboard.png`, `storage_insert.png`,
`storage_search.png`, `storage_space.png`, `storage_mutation.png`,
`index_dashboard.png`, `index_build_time.png`, `index_exact_lookup.png`,
`index_range_search.png`, `index_ordered_scan.png`, `index_size.png`,
`index_mutations.png`.

**Limitación declarada:** el entorno de medición intercepta la E/S de archivos
(≈ 0.46 ms por escritura y ≈ 2.56 ms por lectura de 43 bytes), por lo que los tiempos
absolutos están inflados. Las conclusiones se apoyan en las diferencias relativas, en la
tendencia con `N` y en el análisis de complejidad.

---

## 13. Flujo de trabajo con Git e issues

1. Partir siempre de `main` actualizado: `git checkout main && git pull origin main`.
2. Una rama por bloque de trabajo: `git checkout -b feat/<modulo>-<descripcion>`.
3. Commits pequeños con *conventional commits* y el número de issue:
   `git commit -m "feat(ui): panel de archivos (#20)"`.
4. Subir y abrir el Pull Request: `git push -u origin <rama>`.
5. En el cuerpo del PR, **una línea por issue** con `Closes #N` para que GitHub los cierre
   automáticamente al fusionar.
6. Antes de pedir revisión: `python -m pytest -q`.

Detalle ampliado en
[`docs/guia_issues_y_entregables.md`](docs/guia_issues_y_entregables.md).

---

## 14. Roadmap: Partes 2 a 5

| Parte | Contenido | Estructuras previstas |
|---|---|---|
| **2. Base de datos espacial** | Puntos 2D (latitud, longitud), consultas por rango, k-NN, intersección con polígonos, Euclidiana y Haversine, panel de mapa | `indexes/rtree.py`, extensión del parser para `distancia(...)` y `POINT(...)` |
| **3. Búsqueda de texto** | Índice invertido con SPIMI, ranking TF-IDF + coseno y BM25, extensión `MATCH(...) USING` | `text/spimi.py`, `text/ranking.py` |
| **4. Multimedia / vectorial** | SIFT/MFCC, Bag of Visual Words con K-Means, índices IVF y HNSW, métricas Euclidiana, producto punto y coseno | `vector/features.py`, `indexes/ivf.py`, `indexes/hnsw.py` |
| **5. Aplicación con IA** | Aplicación que consume el API REST del motor e integra al menos dos tipos de datos | Reutiliza `backend/api.py` como base |

---

## 15. Documentación de apoyo

| Documento | Contenido |
|---|---|
| [`docs/comparacion_ventajas_desventajas.md`](docs/comparacion_ventajas_desventajas.md) | Tabla comparativa de técnicas con evidencia medida |
| [`docs/conclusiones_experimentales.md`](docs/conclusiones_experimentales.md) | Metodología, resultados completos, interpretación y limitaciones |
| [`docs/guia_issues_y_entregables.md`](docs/guia_issues_y_entregables.md) | Flujo de trabajo con issues, checklist del avance y guion de la exposición |
| [`frontend/README.md`](frontend/README.md) | Notas del proyecto React generado con Vite |
