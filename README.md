# Proyecto BD2 — Minigestor de Base de Datos Multimodal

Motor de base de datos construido **desde cero en Python** (solo librería estándar) con
almacenamiento paginado en disco, índices B+ y Hash, algoritmos externos, procesamiento
SQL, transacciones con locks y una interfaz web de 4 paneles.

> **Curso:** Base de Datos 2 — Ciclo 2026-2
> **Institución:** Universidad de Ingeniería y Tecnología (UTEC)
> **Entrega actual:** Entrega parcial (Semana 8) — **Partes 1 (relacional) y 2 (espacial) completas**

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
14. [Roadmap: Partes 3 a 5](#14-roadmap-partes-3-a-5)
15. [Documentación de apoyo](#15-documentación-de-apoyo)

---

## 1. Descripción

El proyecto consiste en un **gestor de base de datos multimodal** implementado de forma
progresiva. Esta entrega cubre la **Parte 1** (núcleo relacional) y la **Parte 2**
(datos espaciales: R-Tree, rango, k-NN, polígonos, Haversine/Euclidiana, mapa Leaflet,
SQL espacial y comparación contra el GiST de PostGIS). La Parte 1 incluye:

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
| **2.2 Parte 2 · Base de datos espacial** | ✅ **Completo** | `indexes/rtree.py`, `spatial/`, `benchmarks/benchmark_spatial.py` |
| Documentación técnica (README) | ✅ Este documento | `README.md` |
| Informe incremental | ✅ Completo | [`docs/informe_incremental.md`](docs/informe_incremental.md) |
| Checklist de cumplimiento | ✅ | [`docs/CHECKLIST_CUMPLIMIENTO.md`](docs/CHECKLIST_CUMPLIMIENTO.md) |

Las Partes 3 a 5 (texto, multimedia y aplicación con IA) corresponden a entregas
posteriores y están planificadas en la sección [14](#14-roadmap-partes-3-a-5).

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
│      GET  /api/health   GET /api/tables   GET /api/tables/{name}          │
│      GET  /api/catalog  POST /api/query                                   │
│      POST /api/tables                  (crear tabla desde el panel)       │
│      POST /api/tables/{name}/import    (CSV en una tabla existente)       │
│      POST /api/tables/import-csv       (CSV que crea la tabla)            │
│      GET  /api/spatial/points/{name}   POST /api/spatial/query   (Parte 2)│
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
- **Un solo ejecutor.** `query/query_executor.py` es el **único ejecutor** del motor:
  lo usan el API, la interfaz, las demos y todas las pruebas. El ejecutor end-to-end
  anterior (`query/executor.py`, PR #37) se eliminó y sus pruebas se migraron, para que
  no existan dos semánticas distintas.

---

## 5. Organización del código fuente (arquetipo)

```
Proyecto-BD2/
├── storage/                     # 2.1.1 Gestión de archivos y almacenamiento
│   ├── record.py                #   Schema, Field y serialización binaria de tamaño fijo
│   ├── heap_file.py             #   Heap File paginado + free-list (.free) para reutilizar espacio
│   └── sequential_file.py       #   Archivo Secuencial Paginado (.main/.aux), borrado lazy y reorganización
│
├── indexes/                     # 2.1.2 / 2.2.1 Estructuras de indexación
│   ├── bplus_tree.py            #   B+ Tree base (split, merge, recorrido ordenado)
│   ├── clustered_bplus.py       #   B+ agrupado (hojas con el registro completo)
│   ├── unclustered_bplus.py     #   B+ no agrupado (hojas con clave + RID)
│   ├── extendible_hash.py       #   Hash Extendible (directorio, split de buckets, profundidad)
│   └── rtree.py                 #   R-Tree espacial: MBR, MINDIST, split cuadrático, k-NN best-first
│
├── spatial/                     # 2.2 Parte 2 · datos espaciales
│   ├── geo.py                   #   Haversine, Euclidiana, polígonos (ray casting), datasets
│   └── index.py                 #   SpatialIndex: R-Tree con lat/lon y las dos métricas
│
├── operators/                   # 2.1.2 Algoritmos externos
│   ├── external_sort.py         #   ORDER BY por k-way merge con runs en disco
│   └── external_hashing.py      #   GROUP BY y JOIN por particionado en disco
│
├── query/                       # 2.1.3 Procesamiento de consultas SQL
│   ├── sql_parser.py            #   Parser SQL (SELECT/INSERT/UPDATE/DELETE, CREATE/DROP TABLE, CREATE/DROP INDEX, BEGIN/END, EXPLAIN)
│   ├── query_planner.py         #   Optimizador basado en reglas + estructura del plan
│   ├── catalog.py               #   Registro de tablas, esquemas e índices + DDL (CREATE/DROP TABLE e INDEX)
│   ├── query_executor.py        #   Ejecutor SQL único: storage + índices + operadores + transacciones + espacial
│   ├── query_result.py          #   Contrato de respuesta serializable a JSON
│   ├── csv_loader.py            #   Importación de CSV por el mismo camino que INSERT
│   ├── spatial_queries.py       #   Ejecución de rango / k-NN / polígono sobre el R-Tree
│   └── test_query_executor.py   #   Pruebas del ejecutor y del contrato del frontend
│
├── transactions/                # 2.1.4 Transacciones y concurrencia
│   ├── transaction_manager.py   #   Ciclo de vida BEGIN/COMMIT/ROLLBACK (módulo didáctico)
│   ├── lock_manager.py          #   Locks compartidos/exclusivos (PS/PX) + timeout (2PL estricto)
│   └── demo_concurrencia.py     #   Demostración con hilos: race conditions y su resolución
│                                #   (las transacciones por SQL las ejecuta query/query_executor.py)
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
│   ├── src/panels/              #   FilesPanel, QueryPanel, ResultsPanel, PlanPanel, MapPanel (Leaflet)
│   ├── src/styles.css           #   Hoja de estilos del layout de 4 paneles
│   └── vite.config.ts           #   Proxy /api → http://127.0.0.1:8000
│
├── benchmarks/                  # 2.1.6 / 2.2.4 Comparación experimental
│   ├── benchmark_heap_vs_sequential.py   # Heap File vs Archivo Secuencial
│   ├── benchmark_indexes.py              # B+ agrupado vs B+ no agrupado vs Hash
│   ├── benchmark_spatial.py              # Secuencial vs R-Tree vs GiST (PostGIS)
│   ├── generate_charts.py                # Gráficas PNG de la Parte 1
│   ├── generate_spatial_charts.py        # Gráficas PNG de la Parte 2
│   └── generate_report_tables.py         # Tablas del informe/README generadas desde los CSV
│
├── benchmark_results/           # CSVs, JSONs y plots/*.png de los experimentos
├── docs/                        # Documentación de apoyo (ventajas/desventajas y conclusiones)
├── examples/                    # demo_parte1.py y demo_parte2.py (consola, ejecutor oficial)
├── tests/                       # Pruebas unitarias, de integración, end-to-end y de cumplimiento
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

Hay **dos niveles**, y conviene no confundirlos al exponer el proyecto:

1. **Transacciones dentro del motor (lo que se demuestra en la interfaz).**
   `BEGIN TRANSACTION`, `END TRANSACTION`, `COMMIT` y `ROLLBACK` los ejecuta el
   **mismo `QueryExecutor`** que atiende el panel de consultas y el API REST. En la
   primera escritura de cada tabla se guarda su estado previo y se toma su **bloqueo
   exclusivo**; `ROLLBACK` restaura las filas, reconstruye los índices y además deshace
   el DDL de la transacción (`CREATE TABLE`, `CREATE INDEX`, `DROP TABLE`). `END
   TRANSACTION`/`COMMIT` confirma y libera. El endpoint `GET /api/health` informa si hay
   una transacción abierta (`transaction`), con su id, sentencias y tablas bloqueadas.
2. **Módulo didáctico con hilos (`transactions/`).** `transaction_manager.py` modela el
   ciclo de vida sobre una tabla en memoria y `lock_manager.py` implementa los bloqueos
   compartidos (PS) y exclusivos (PX) por recurso con **protocolo 2PL estricto** (todo se
   libera en COMMIT/ROLLBACK). El mecanismo frente a conflictos es **timeout** (2 s) que
   lanza `RecursoBloqueado`, no una detección de interbloqueos por grafo de espera.
   `demo_concurrencia.py` ejecuta varias transacciones con **hilos** y muestra una
   *race condition* (actualización perdida sobre `X = 100`) y cómo los locks la evitan.

### 7.6 Interfaz de usuario e integración (`backend/` + `frontend/`)

Los 4 paneles exigidos por el enunciado (2.1.5):

| Panel | Issue | Qué muestra |
|---|---|---|
| **Archivos** | #20 | Tablas registradas, tipo de almacenamiento (Heap/Secuencial), archivos `.dat`/`.free` y `.main`/`.aux` con su tamaño, esquema con PK, índices con su técnica (incluido el R-Tree espacial) y cantidad de registros; formulario para **crear y eliminar índices** y para **cargar CSV** eligiendo separador |
| **Consultas** | #21 | Editor SQL con ejemplos por caso de uso (incluidos los espaciales), ejecución con botón o `Ctrl+Enter` y mensajes de error del parser |
| **Resultados** | #22 | Tabla dinámica con las columnas devueltas, filas, filas afectadas, tiempo de ejecución y vista JSON cruda |
| **Plan de ejecución** | #23 | Ruta de acceso elegida, índices utilizados, optimizador, plan lógico con justificación y traza real de operadores con tiempos y filas |
| **Mapa** (Parte 2) | 2.2.2 | Mapa interactivo **Leaflet + OpenStreetMap** (zoom, pan, mapa base). Clic para fijar `mi_ubicacion`; modos rango, k-NN y polígono (por clics); selector Haversine/Euclidiana; resalta los resultados, dibuja el radio en metros reales y numera los k vecinos; reporta `access_path`, índice usado y tiempo. Sólo lista tablas espaciales |

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

**Dependencias opcionales** (el proyecto funciona sin ellas):

| Dependencia | Para qué | Si falta |
|---|---|---|
| `psycopg2-binary` (Python) | Que el benchmark espacial se conecte a PostgreSQL | El benchmark mide secuencial y R-Tree y marca PostgreSQL como *no disponible* |
| **PostGIS** (extensión de PostgreSQL, **no** es un paquete de Python) | Reproducir la comparativa contra el GiST de PostgreSQL | Igual: cae al modo `earthdistance`, o marca PostgreSQL como *no disponible* |

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

> **Si ya tenías el entorno creado de antes**, vuelve a ejecutar
> `pip install -r requirements.txt`: se añadieron `python-multipart` (lo exige la subida
> del CSV del panel de archivos) y `psycopg2-binary` (benchmark espacial). Sin
> `python-multipart` el API **no arranca**, porque FastAPI lo necesita para leer el
> archivo que se sube.

### 8.2.1 PostGIS (opcional, solo para la comparativa espacial)

La Parte 2 compara el R-Tree propio contra el **GiST de PostgreSQL**, y para eso la
medición de referencia usa **PostGIS**. **No hace falta para usar el motor**: solo si
quieres reproducir esa comparativa completa.

PostGIS **no es un paquete de Python**, así que no aparece en `requirements.txt`: es una
extensión del **servidor** PostgreSQL y se instala aparte.

```bash
# 1) Instalar PostGIS para tu versión de PostgreSQL
#    Windows: paquete oficial en https://download.osgeo.org/postgis/windows/
#             (elegir la carpeta pg17, pg16, ... según tu versión) y ejecutar el .exe
#    Debian/Ubuntu: sudo apt install postgresql-17-postgis
#    macOS (Homebrew): brew install postgis

# 2) Activar la extensión en la base de datos
psql -U postgres -c "CREATE EXTENSION postgis;"

# 3) Comprobar que quedó activa
psql -U postgres -c "SELECT postgis_full_version();"

# 4) Ejecutar la comparativa contra PostGIS
python -m benchmarks.benchmark_spatial --sizes 1000 10000 100000 --pg-mode postgis
```

Los pasos exactos que se siguieron en este proyecto (con la verificación del MD5 del
instalador y el detalle de por qué `geom::geography` impide que PostgreSQL use el índice)
están en [`docs/parte2_espacial.md`](docs/parte2_espacial.md) §6.

**Sin PostGIS el benchmark funciona igual**, no se rompe:

| Situación | Qué hace el benchmark |
|---|---|
| PostGIS instalado (`--pg-mode postgis`) | Compara contra GiST con `geometry(Point,4326)`, `ST_DWithin` y `<->` |
| Sin PostGIS, con `--pg-mode earthdistance` | Compara contra GiST nativo con `cube` + `earthdistance` |
| Sin PostGIS, sin argumentos (`--pg-mode auto`) | **Prefiere PostGIS** y cae a `earthdistance` si no está |
| Sin PostgreSQL o sin `psycopg2` | Mide secuencial y R-Tree, y marca PostgreSQL como *no disponible* con el motivo |

El informe JSON de resultados deja constancia de lo que se midió
(`"gist_backend"` y `"postgis_available"`), así que no hay duda de qué baseline se usó.

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
python -m examples.demo_parte2                       # Parte 2: R-Tree y SQL espacial
python -m transactions.demo_concurrencia             # transacciones y race conditions con hilos
```

**Benchmarks y gráficas (opcional, tardan varios minutos):**

```bash
python benchmarks/benchmark_heap_vs_sequential.py --sizes 1000 10000 100000
python -m benchmarks.benchmark_indexes --sizes 1000 10000 100000
python -m benchmarks.generate_charts                 # PNG en benchmark_results/plots/

# Parte 2 · comparativa espacial (necesita PostgreSQL; ver §8.2.1)
python -m benchmarks.benchmark_spatial --sizes 1000 10000 100000 --pg-mode postgis
python -m benchmarks.generate_spatial_charts         # PNG espaciales

# Tablas del informe y del README, generadas desde los CSV (nunca a mano)
python -m benchmarks.generate_report_tables
python -m benchmarks.generate_report_tables --check  # verifica que estén sincronizadas
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
| Cambié los datos y quiero empezar de cero | Borra `backend/data/` (incluido `catalog.json` para descartar las tablas creadas por SQL) y reinicia el API |
| El alias de tabla (`FROM users u`) o un agregado sin `GROUP BY` dan error | Son las dos únicas limitaciones vigentes del subconjunto SQL; ver la sección [9](#9-subconjunto-sql-soportado) |
| Creé una tabla y desapareció al reiniciar | No debería: su definición se guarda en `backend/data/catalog.json`. Si borraste esa carpeta, vuelve a crearla |
| `pytest` falla al crear archivos temporales | Ejecuta las pruebas en una carpeta con permisos de escritura y sin antivirus que bloquee `%TEMP%` |

---

## 9. Subconjunto SQL soportado

El enunciado pide "solo lo esencial que dé soporte a las técnicas implementadas". El
parser implementa exactamente:

```sql
SELECT [*|col1, col2, ...] FROM tabla
  [JOIN tabla2 ON tabla.col = tabla2.col]
  [WHERE predicado [AND|OR predicado] ...]
  [GROUP BY col]
  [ORDER BY col [ASC|DESC]]
  [LIMIT n]

INSERT INTO tabla VALUES (v1, v2, ...)
UPDATE tabla SET col = valor, ... [WHERE ...]
DELETE FROM tabla [WHERE predicado [AND|OR predicado] ...]

CREATE TABLE [IF NOT EXISTS] tabla (
    col TIPO [PRIMARY KEY], ...
    [, PRIMARY KEY (col)]
) [USING HEAP|SEQUENTIAL]
DROP TABLE [IF EXISTS] tabla

CREATE [UNIQUE] INDEX [nombre] ON tabla (columna)
    [USING HASH|BPLUS_CLUSTERED|BPLUS_UNCLUSTERED]
-- Índice espacial: se declaran las dos columnas
CREATE INDEX [nombre] ON tabla (latitud, longitud) USING RTREE
DROP INDEX [IF EXISTS] nombre [ON tabla]

-- Parte 2 · consultas espaciales (las del enunciado se aceptan TAL CUAL)
SELECT * FROM tiendas WHERE distancia(ubicacion, POINT(-12.0464, -77.0428)) < 5000
SET mi_ubicacion = POINT(-12.0464, -77.0428)       -- o clic en el panel de mapa
SELECT * FROM restaurantes ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10
SELECT * FROM tabla WHERE dentro_de(ubicacion, POLYGON((lat lon, lat lon, ...)))
-- distancia(col|indice|ubicacion, POINT(lat, lon) | variable [, HAVERSINE|EUCLIDEAN])

BEGIN TRANSACTION | END TRANSACTION | COMMIT | ROLLBACK

EXPLAIN [ANALYZE] <sentencia>
```

| Característica | Estado | Ejemplo |
|---|---|---|
| `SELECT *` y proyección de columnas | ✅ | `SELECT id, name FROM users` |
| Operadores de comparación | ✅ | `=`, `!=`, `<>`, `<`, `<=`, `>`, `>=` |
| Rangos | ✅ | `WHERE age BETWEEN 19 AND 22` |
| Conjunción de predicados | ✅ `AND` | `WHERE age >= 20 AND dept = 'CS'` |
| Disyunción | ✅ `OR` (sin paréntesis) | `WHERE age >= 24 OR dept = 'CS'` |
| Ordenamiento | ✅ `ASC`/`DESC` | `ORDER BY salary DESC` |
| Límite de filas | ✅ `LIMIT` | `SELECT id FROM employees ORDER BY salary DESC LIMIT 3` |
| Agrupación y agregados | ✅ con `GROUP BY` | `SELECT dept, COUNT(*) AS total FROM employees GROUP BY dept` |
| Agregados sin `GROUP BY` | ❌ | `SELECT COUNT(*) FROM users` |
| Equi-JOIN | ✅ igualdad entre columnas, **sin alias** | `SELECT users.name, employees.id FROM users JOIN employees ON users.dept = employees.dept` |
| Alias de tabla (`FROM users u`) | ❌ | — |
| `CREATE TABLE` / `DROP TABLE` (DDL) | ✅ | `CREATE TABLE alumnos (id INT PRIMARY KEY, nombre VARCHAR(100))` |
| `CREATE INDEX` / `DROP INDEX` | ✅ las tres técnicas, `UNIQUE` solo con Hash | `CREATE INDEX idx_alumnos_nota ON alumnos (nota) USING BPLUS_UNCLUSTERED` |
| `UPDATE` | ✅ | `UPDATE users SET age = 21 WHERE id = 3` |
| `BEGIN` / `END TRANSACTION` / `COMMIT` / `ROLLBACK` | ✅ dentro del motor | `BEGIN TRANSACTION` … `ROLLBACK` |
| `EXPLAIN` / `EXPLAIN ANALYZE` | ✅ | `EXPLAIN ANALYZE SELECT * FROM employees WHERE salary >= 4000` |
| Carga de CSV | ✅ (endpoint + botón + CLI) | ver [§9.1](#91-carga-de-datos-desde-csv) |
| SQL espacial del enunciado (`ubicacion`, `mi_ubicacion`) | ✅ | `SELECT * FROM tiendas ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10` |
| Variables de sesión espaciales | ✅ `SET` | `SET mi_ubicacion = POINT(-12.05, -77.04)` |
| `CREATE INDEX ... USING RTREE` | ✅ dos columnas | `CREATE INDEX idx_geo ON tiendas (lat, lon) USING RTREE` |

`ubicacion` designa el punto (lat, lon) del índice R-Tree de la tabla (o, sin índice,
el par de columnas `lat`/`lon`); `mi_ubicacion` es una variable de sesión. Detalle en
[`docs/parte2_espacial.md`](docs/parte2_espacial.md) §4.

**Crear tablas: dos puertas, una sola implementación.** El motor crea tablas
dinámicas por dos caminos, y los dos terminan en el mismo `CREATE TABLE`:

| Puerta | Uso | Función interna |
|---|---|---|
| `CREATE TABLE t (...)` en el panel de consultas | Escribir SQL a mano | `Catalog.create_table` |
| Formulario del panel de archivos → `POST /api/tables` | Usuario final, sin SQL | `engine.create_table` → construye el SQL y lo ejecuta |

Como el formulario reutiliza el parser y el ejecutor, el índice Hash de la clave
primaria, el registro en el catálogo y la persistencia se comportan **igual** por
las dos puertas: corregir el DDL una vez lo corrige en ambas. La lógica vive en
[`query/table_manager.py`](query/table_manager.py).

**Subir CSV: también dos casos distintos** (el profesor pidió los dos):

| Caso | Endpoint | Qué hace |
|---|---|---|
| Cargar en una tabla **que ya existe** | `POST /api/tables/{name}/import` | Valida el encabezado y respeta PK e índices; reporta fila a fila |
| **Crear la tabla desde el CSV** | `POST /api/tables/import-csv` | Deduce el esquema (`INT`/`FLOAT`/`VARCHAR(n)` por longitud observada) y es atómico: si el CSV es inválido no deja tabla a medias |

**Índices utilizables por el planner:** Hash Extendible (igualdad), B+ no agrupado
(igualdad y rango), B+ agrupado (igualdad, rango y `ORDER BY` sin `External Sort`).
Un `WHERE` con `OR` sobre una misma columna indexada se resuelve como **unión de
búsquedas por índice** (`HASH_INDEX_UNION` / `BPLUS_INDEX_UNION`), y un rango con los
dos extremos (`age >= 19 AND age <= 23`) usa **un solo** `range_search` en lugar de
indexar un extremo y filtrar el resto.

**Índices creados por el usuario:** `CREATE INDEX` construye el índice y lo puebla
recorriendo la tabla, así que funciona también sobre datos ya cargados (el caso de la
demo: se carga el CSV y después se indexa). El índice sobrevive al reinicio porque queda
en el manifiesto del catálogo y se reconstruye al abrirlo. El índice de la `PRIMARY KEY`
no se puede eliminar: es lo que garantiza que no haya claves primarias duplicadas.

**Tipos de columna admitidos:** `INT` (INTEGER/SMALLINT/BIGINT), `FLOAT`
(REAL/DOUBLE/DECIMAL/NUMERIC) y `VARCHAR(n)` (CHAR/TEXT/STRING). La `PRIMARY KEY`
declarada (o la primera columna si no se declara) genera automáticamente un **índice
Hash único**.

`EXPLAIN` devuelve el plan lógico sin ejecutar la consulta; `EXPLAIN ANALYZE` además la
ejecuta y añade la **traza real** con tiempos y filas por operador. Ambas responden en el
campo `execution_plan` y como texto en la columna `plan`.

Las limitaciones marcadas con ❌ quedan como trabajo futuro (agregados sin `GROUP BY` y
alias de tabla).

### 9.1 Carga de datos desde CSV

El flujo siempre es: **primero se crea la tabla** (con su esquema y tipos) y **después se
carga el CSV**. La tabla puede llamarse como sea y tener las columnas que quieras; el CSV
no necesita estar en el mismo orden que el `CREATE TABLE`, porque el mapeo es **por
nombre de columna**.

```sql
CREATE TABLE animales (
    id INT PRIMARY KEY,
    nombre VARCHAR(40),
    especie VARCHAR(30),
    edad INT,
    peso FLOAT
);
```

Luego se carga un CSV cuya cabecera nombre esas columnas (en cualquier orden):

```csv
peso,especie,id,nombre,edad
12.5,Perro,1,Firulais,5
4.2,Gato,2,"Michi, el gato",3
```

Tres formas equivalentes (todas usan el mismo camino que `INSERT`, por lo que respetan la
clave primaria y mantienen los índices):

```bash
# 1) Línea de comandos (sin API en ejecución)
python -m tools.import_csv --list
python -m tools.import_csv --sql "CREATE TABLE alumnos (id INT PRIMARY KEY, nombre VARCHAR(100), carrera_id INT, nota INT)" \
                           --table alumnos --file alumnos_prueba_bd2.csv

# 2) API REST
curl.exe -X POST http://127.0.0.1:8000/api/tables/alumnos/import \
  -H "Content-Type: application/json" \
  -d "{\"csv_text\":\"id,nombre,carrera_id,nota\n1,Ana,1,15\n\",\"has_header\":true}"
```

3. **Interfaz web:** panel de **Archivos → "Cargar CSV en la tabla seleccionada"**, donde
   además se elige el **separador** (coma, punto y coma de Excel en español, o tabulador)
   y si la primera fila es el **encabezado**.

El CSV se interpreta con la librería estándar `csv` (admite comillas y comas dentro de un
campo: `"Pérez, Juan"`). Las columnas se mapean **por nombre de encabezado**, así que el
CSV puede traerlas en cualquier orden. Si el encabezado no nombra todas las columnas de la
tabla, la importación **falla con un mensaje que lista las columnas esperadas** en lugar de
mapear por posición y guardar datos en la columna equivocada (para forzar el mapeo por
posición, usa `has_header=False`). El reporte devuelve filas leídas, insertadas,
rechazadas y los errores por fila.

Las tablas creadas con `CREATE TABLE` **persisten entre reinicios** del API: su definición
se guarda en `backend/data/catalog.json` y se restauran al arrancar. Un CSV con una ruta
que no existe, un encabezado que no coincide o cero filas de datos se reporta como
**error**, no como una importación exitosa de 0 filas.

---

## 10. API REST del motor

Base: `http://127.0.0.1:8000` · Documentación interactiva (Swagger UI): `/docs`

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/health` | Estado del API y lista de tablas registradas |
| `GET` | `/api/tables` | Catálogo completo: tablas, almacenamiento, esquema, índices, archivos, tamaño y número de registros |
| `GET` | `/api/tables/{name}` | Igual que el anterior para una sola tabla (404 si no existe) |
| `GET` | `/api/catalog` | Tablas creadas por el usuario (las persistidas en `catalog.json`) |
| `POST` | `/api/tables/{name}/import` | Importa un CSV (`csv_text`, `has_header`, `delimiter`) en una tabla existente |
| `POST` | `/api/query` | Ejecuta una sentencia SQL (`sql`) y devuelve el `QueryResult` completo; acepta `variables`, p. ej. `{"mi_ubicacion": [-12.04, -77.04]}` |
| `POST` | `/api/tables` | Crea una tabla desde el formulario del panel |
| `POST` | `/api/tables/import-csv` | Crea la tabla deduciendo el esquema desde un CSV |
| `GET` | `/api/spatial/points/{name}` | Puntos (lat, lon) de una tabla, para el mapa |
| `POST` | `/api/spatial/query` | Rango / k-NN / polígono sobre el R-Tree (radio siempre en metros) |

Ejemplo de petición:

```bash
curl.exe -X POST http://127.0.0.1:8000/api/query \
  -H "Content-Type: application/json" \
  -d "{\"sql\":\"SELECT dept, COUNT(*) AS total FROM employees GROUP BY dept\"}"
```

---

## 11. Pruebas

La suite completa se ejecuta con:

```bash
python -m pytest -q                                   # suite completa
python -m unittest discover -s tests -t . -v          # alternativa sin pytest
```

| Archivo | Qué verifica |
|---|---|
| `tests/test_record.py` | Serialización y esquema de registros |
| `tests/test_heap_file.py`, `tests/test_sequential_file.py` | Inserción, búsqueda, borrado, reutilización de espacio y reorganización |
| `tests/test_bplus_tree.py`, `tests/test_clustered_bplus.py`, `tests/test_unclustered_bplus.py` | Split, merge, búsqueda, rango y recorrido ordenado de los B+ |
| `tests/test_extendible_hash.py` | Crecimiento del directorio, split de buckets y unicidad |
| `tests/test_external_sort.py`, `tests/test_external_hashing.py` | Orden externo, `GROUP BY`/`JOIN` particionados y limpieza de temporales |
| `tests/test_sql_parser.py`, `tests/test_query_planner.py` | Subconjunto SQL y elección de la ruta de acceso |
| `query/test_query_executor.py` | Ejecución real y contrato del frontend |
| `tests/test_storage_integration.py` | Almacenamiento + índices + catálogo oficial (incluye invalidación de RID al reorganizar y un solo agrupado por tabla) |
| `tests/test_end_to_end.py` | Cadena SQL → parser → planner → **ejecutor oficial** → almacenamiento, con Heap y Secuencial y operadores externos forzados a disco |
| `tests/test_transactions.py`, `tests/test_dinamica_parte1.py` | Transacciones, locks, `CREATE/DROP INDEX`, unión de índices en `OR` |
| `tests/test_profesor_script.py` | El script SQL de la cátedra sobre el CSV de prueba |
| `tests/test_rtree.py`, `tests/test_spatial_sql.py` | **Parte 2**: MINDIST, invariantes, rango/k-NN/polígono contra fuerza bruta y SQL espacial |
| `tests/test_cumplimiento.py` | Correcciones de la revisión final: SQL **literal** del enunciado con y sin índice, `SET`/`mi_ubicacion`, Euclidiana por R-Tree, R-Tree con INSERT/UPDATE/DELETE y tras reiniciar, espacio serializado, JOIN calificado, CSV en Linux/macOS |
| `tests/test_benchmark_*.py` | Validez metodológica de los benchmarks |

---

## 12. Experimentos y resultados

Todas las tablas de esta sección se **generan desde los CSV** de `benchmark_results/`
con `python -m benchmarks.generate_report_tables`; ningún número se escribe a mano, así
que README, informe y CSV siempre coinciden. Metodología, análisis y conclusiones en
[`docs/informe_incremental.md`](docs/informe_incremental.md) y
[`docs/parte2_espacial.md`](docs/parte2_espacial.md). Todas las tablas juntas:
[`docs/resultados_experimentales.md`](docs/resultados_experimentales.md).

### 12.1 Heap File vs Archivo Secuencial Paginado

<!-- BEGIN:AUTO:parte1_storage -->
_Generado por `python -m benchmarks.generate_report_tables` desde `benchmark_results/*.csv`. No editar a mano._

Entorno de la corrida: Windows-11-10.0.26200-SP0 · Python 3.13.7.

Inserción y borrado uno a uno medidos hasta **10 000** registros.

| N | Técnica | Inserción (1 a 1, prom.) | Carga masiva | Búsqueda por PK | Espacio en disco | Borrado (prom.) | Reorganización |
|---|---|---|---|---|---|---|---|
| 1 000 | Heap File | 15.39 ms | 36.5 ms | 3.44 ms | 43.9 KiB | 1.95 ms | no aplica |
| 1 000 | Secuencial | 15.23 ms | 6.1 ms | 321.99 µs | 42.0 KiB | 15.64 ms | 5.9 ms |
| 10 000 | Heap File | 14.83 ms | 25.4 ms | 36.60 ms | 422.9 KiB | 2.09 ms | no aplica |
| 10 000 | Secuencial | 16.37 ms | 26.9 ms | 245.96 µs | 419.9 KiB | 12.63 ms | 36.5 ms |
| 100 000 | Heap File | — | 258.3 ms | 317.51 ms | 4.10 MiB | — | no aplica |
| 100 000 | Secuencial | — | 316.4 ms | 450.82 µs | 4.10 MiB | — | — |
<!-- END:AUTO:parte1_storage -->

### 12.2 B+ agrupado vs B+ no agrupado vs Hash Extendible

<!-- BEGIN:AUTO:parte1_indices -->
_Generado por `python -m benchmarks.generate_report_tables` desde `benchmark_results/*.csv`. No editar a mano._

**Comparación con 50 000 claves** (tiempos promedio por operación)

| Métrica | B+ agrupado | B+ no agrupado | Hash extendible |
|---|---|---|---|
| Construcción | 1 334.34 ms | 859.87 ms | 314.51 ms |
| Igualdad exacta (hit) | 10.96 µs | 1.97 µs | 1.43 µs |
| Mejora vs búsqueda lineal | 2 327.3× | 12 956.2× | 17 788.0× |
| Igualdad + traer la fila | 11.63 µs | 135.11 µs | 127.34 µs |
| Rango + traer la fila | 4.10 ms | 61.34 ms | no aplica |
| Recorrido ordenado | 449.83 ms | 60.71 ms | no aplica |
| Inserción (prom.) | 22.50 µs | 15.77 µs | 2.23 µs |
| Borrado (prom.) | 18.50 µs | 28.05 µs | 4.11 µs |
| Espacio adicional | 2.18 MiB | 1.21 MiB | 1.18 MiB |
| Búsqueda lineal (sin índice) | 25.51 ms |  |  |

**Escalabilidad de la igualdad exacta**

| N | B+ agrupado (igualdad) | B+ no agrupado (igualdad) | Hash extendible (igualdad) | Lineal |
|---|---|---|---|---|
| 1 000 | 10.40 µs | 1.04 µs | 1.05 µs | 74.31 µs |
| 10 000 | 10.76 µs | 1.68 µs | 1.26 µs | 3.58 ms |
| 50 000 | 10.96 µs | 1.97 µs | 1.43 µs | 25.51 ms |
<!-- END:AUTO:parte1_indices -->

**Cuándo usar cada estructura:** **Hash Extendible** para igualdad exacta con muchas
lecturas; **B+ no agrupado** para igualdad y rangos sobre una columna secundaria;
**B+ agrupado** (uno por tabla) cuando el `ORDER BY` o los rangos van sobre la clave de
orden físico, porque es el único que permite al planner **evitar el External Sort** y
no paga una lectura por RID; **External Sort** para `ORDER BY` sin índice y
**External Hashing** para `GROUP BY` y equi-`JOIN`.

### 12.3 Parte 2 · Secuencial vs R-Tree propio vs GiST (PostGIS)

Promedio de 100 consultas por medición. Baseline: **GiST de PostgreSQL con PostGIS**
sobre `geometry(Point, 4326)` (índice 2D). El espacio se compara de forma justa:
R-Tree **serializado** frente a `pg_relation_size` del índice GiST.

<!-- BEGIN:AUTO:readme_parte2 -->
_Generado por `python -m benchmarks.generate_report_tables` desde `benchmark_results/*.csv`. No editar a mano._

| Consulta | Secuencial | R-Tree propio | GiST/PostGIS |
|---|---|---|---|
| Rango 1 km | 88.545 ms | 2.055 ms (43.1×) | 0.342 ms (258.7×) |
| Rango 5 km | 88.845 ms | 11.630 ms (7.6×) | 10.032 ms (8.9×) |
| Rango 10 km | 89.167 ms | 38.093 ms (2.3×) | 43.485 ms (2.1×) |
| k-NN k=10 | 116.289 ms | 11.350 ms (10.2×) | 0.258 ms (451.2×) |
| k-NN k=50 | 148.088 ms | 11.033 ms (13.4×) | 0.433 ms (341.8×) |
| k-NN k=100 | 174.897 ms | 12.949 ms (13.5×) | 0.633 ms (276.5×) |
| Polígono (4 vértices) | — | 11.127 ms | — |

**Construcción y espacio:**

| N | Construcción R-Tree | Construcción GiST | Índice R-Tree (serializado) | Índice GiST (pg_relation_size) | R-Tree en memoria Python | Tabla PostgreSQL (contexto) |
|---|---|---|---|---|---|---|
| 1 000 | 4.5 ms | 9.5 ms | 42.0 KiB | 48.0 KiB | 515.0 KiB | 88.0 KiB |
| 10 000 | 52.2 ms | 49.0 ms | 419.4 KiB | 384.0 KiB | 4.29 MiB | 832.0 KiB |
| 100 000 | 715.5 ms | 287.0 ms | 4.09 MiB | 3.94 MiB | 42.92 MiB | 8.05 MiB |

- Rango 1 km con 1 000 puntos: R-Tree 0.038 ms vs GiST 0.163 ms → el R-Tree es 4.3× más rápido que PostGIS.
- Escalabilidad del R-Tree (rango 1 km, de 10 000 a 100 000 puntos): 0.242 ms → 2.055 ms (8.5× más tiempo para 10× datos; los resultados por consulta también crecen 9.8× (6 → 59)).
- Escalabilidad del GiST (rango 1 km, de 10 000 a 100 000 puntos): 0.197 ms → 0.342 ms (1.7× más tiempo para 10× datos; los resultados por consulta también crecen 9.8× (6 → 59)).
<!-- END:AUTO:readme_parte2 -->

> **Para reproducir la comparativa contra PostGIS**, ver
> [§8.2.1](#821-postgis-opcional-solo-para-la-comparativa-espacial). Si en el `WHERE` o
> en el `ORDER BY` se castea a `geography`, PostgreSQL no puede usar el índice GiST
> (*Seq Scan*); el benchmark usa la forma indexable (`geom && ST_Expand(...)` +
> `ST_DWithin`, y `<->` sobre la columna).

### 12.4 Gráficas

`benchmark_results/plots/`: `storage_*.png`, `index_*.png` y `spatial_*.png`
(rango 1/5/10 km, k-NN 10/50/100, mejora frente a secuencial, construcción y espacio).

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

## 14. Roadmap: Partes 3 a 5

| Parte | Contenido | Estructuras previstas |
|---|---|---|
| **1. Relacional** | ✅ Completa | `storage/`, `indexes/`, `operators/`, `query/`, `transactions/` |
| **2. Espacial** | ✅ Completa | `indexes/rtree.py`, `spatial/`, panel de mapa Leaflet y comparativa vs PostGIS |
| **3. Búsqueda de texto** | Índice invertido con SPIMI, TF-IDF + coseno y BM25, `MATCH(...) USING` | `text/spimi.py`, `text/ranking.py` |
| **4. Multimedia / vectorial** | SIFT/MFCC, Bag of Words con K-Means, IVF y HNSW | `vector/features.py`, `indexes/ivf.py`, `indexes/hnsw.py` |
| **5. Aplicación con IA** | Aplicación sobre el API REST con al menos dos tipos de datos | Reutiliza `backend/api.py` |

---

## 15. Documentación de apoyo

| Documento | Contenido |
|---|---|
| [`docs/informe_incremental.md`](docs/informe_incremental.md) | **Informe incremental**: arquitectura, dominio de datos, algoritmos y parte experimental de las Partes 1 y 2 |
| [`docs/CHECKLIST_CUMPLIMIENTO.md`](docs/CHECKLIST_CUMPLIMIENTO.md) | Requisito por requisito del enunciado (Partes 1 y 2) con su evidencia |
| [`docs/resultados_experimentales.md`](docs/resultados_experimentales.md) | Todas las tablas experimentales, generadas desde los CSV |
| [`docs/parte2_espacial.md`](docs/parte2_espacial.md) | **Parte 2**: R-Tree, métricas, sintaxis SQL espacial, panel de mapa, resultados experimentales y decisiones de diseño |
| [`docs/revision_parte1.md`](docs/revision_parte1.md) | **Revisión a fondo de la Parte 1**: qué se corrigió, verificación en vivo del flujo de la demo, hallazgos abiertos con su defensa, alineación con la clase y guion de demo de 5 minutos |
| [`docs/revision/indices.md`](docs/revision/indices.md) | Corrección de las estructuras de indexación, uso de índices en el planner y metodología de los experimentos |
| [`docs/revision/sql_dinamico.md`](docs/revision/sql_dinamico.md) | Superficie SQL, importación de CSV, transacciones y los dos ejecutores |
| [`docs/revision/frontend.md`](docs/revision/frontend.md) | Tema claro, los 4 paneles y los flujos de CSV y DDL en la interfaz |
| [`docs/revision/alineacion_clase.md`](docs/revision/alineacion_clase.md) | Comparación con el material de clase (semanas 1–7), componente por componente, con plan de repaso |
| [`docs/comparacion_ventajas_desventajas.md`](docs/comparacion_ventajas_desventajas.md) | Tabla comparativa de técnicas con evidencia medida |
| [`docs/conclusiones_experimentales.md`](docs/conclusiones_experimentales.md) | Metodología, resultados completos, interpretación y limitaciones |
| [`docs/guia_issues_y_entregables.md`](docs/guia_issues_y_entregables.md) | Flujo de trabajo con issues, checklist del avance y guion de la exposición |
| [`frontend/README.md`](frontend/README.md) | Notas del proyecto React generado con Vite |
