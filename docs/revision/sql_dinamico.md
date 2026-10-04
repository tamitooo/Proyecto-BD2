# Revisión del front-end SQL y su ejecución — Proyecto BD2 (Parte 1)

**Revisor:** agente de revisión (solo lectura sobre el código del repo).
**Fecha de la revisión:** 2026-10-04, 12:05–12:30 (hora local).
**Alcance:** `query/`, `backend/`, `transactions/`, `tools/`, `tests/` y `frontend/src/` (solo lectura), verificado **ejecutando** el flujo del profesor.

---

## 0. Nota imprescindible: el árbol de trabajo cambió DURANTE la revisión

Mientras revisaba, **otro actor siguió editando el repositorio** (los mismos archivos "uncommitted" que había que auditar). Esto condiciona todo el informe, así que lo dejo explícito:

| Archivo | 12:05 (primera lectura) | 12:21:27 | 12:24:08 | 12:27:56 (final) |
|---|---|---|---|---|
| `query/sql_parser.py` | 1013 líneas, **sin** CREATE INDEX ni transacciones | 1183 líneas, +INDEX, +TXN (`7FA241CE…`) | = | `7FA241CE…` |
| `query/query_executor.py` | 1219 líneas, sin `_execute_create_index` / `_execute_transaction` | 1770 líneas (`1E2F05CD…`) | (`57C2A283…`) | `57C2A283…` |
| `query/catalog.py` | 428 líneas | 556 líneas (`96806891…`) | = | `96806891…` |
| `query/query_planner.py` | sin unión por índice | `4A36267C…` | `02E347A8…` | `02E347A8…` |
| `tests/test_sql_parser.py`, `tests/test_end_to_end.py` | rojos (asumían UPDATE no soportado) | rojos | **corregidos** | verdes |

**Cómo lo resolví:** congelé una copia del árbol a las 12:22 en `.review_tmp/snap_A/` (SHA256 verificados arriba) y ejecuté todo contra ella y contra el árbol vivo, comprobando al final que el delta `snap_A → vivo` era **solo cosmético** (etiquetas de plan de transacción: `"BEGIN TRANSACTION"` → `"BEGIN_TRANSACTION"`, `"END TRANSACTION"` → `"COMMIT"`). **Todas las conclusiones de este informe aplican al árbol vivo del 12:27:56**, salvo donde digo expresamente "revisión inicial".

Hashes **al cierre de este informe (12:30:35)** — el árbol siguió cambiando durante la revisión:

```
query/sql_parser.py       7FA241CEB86B7D8444B0F1E3E49DB95D006ED60B31DF3ED6E0814281F5245867
query/query_executor.py   57C2A283383AA1C9CC45495DBAB00DE1CB92F277C07334BE3BC5FDEA40CD9DA9
query/catalog.py          B9777149719CBB75868E6408582C11572217EEE71C5D1720C496D5E10B2D5341
query/query_planner.py    02E347A81D00304AD0E721D4B8994752D7BF3BB92A77A658393953C106695203
backend/engine.py         ABF2E44A7D5767F8817207429B95EE89CDC5B66CC5AE30ACF64501579FB07911
backend/api.py            6D6EABC5397925B715EF9F35AEEB8E645EB5BC184F7119D905F0A196DB1FFC8A
query/csv_loader.py       F385AAA962F638D845F3461522E0E510A8538548EC60F467549F99075D894890
```

**Cambios que aterrizaron MIENTRAS revisaba** (los marco como "ya corregido" donde corresponde en §7):

| Hora | Cambio | Efecto |
|---|---|---|
| 12:20 | `CREATE INDEX` / `DROP INDEX` / `BEGIN`-`END TRANSACTION` entran al parser, al ejecutor y al catálogo | Dos hallazgos graves de las 12:05 quedaron arreglados (ver §3.1, §5.1) |
| 12:23 | Planner: con OR ya no elige un solo predicado como camino de acceso; el recorrido ordenado del B+ solo se usa sin WHERE | Elimina un riesgo de resultados incompletos con `OR` + índice |
| 12:24 | Cosméticos del plan de transacción | — |
| 12:26 | `tests/test_sql_parser.py` y `tests/test_end_to_end.py`: dejan de exigir que `UPDATE` falle | Bajan 3 fallos de la suite |
| 12:28 | `backend/engine.py`: siembra por tabla y `transaction_state()` | El API puede mostrar la transacción abierta |
| 12:29 | `backend/api.py`: `/api/health` devuelve `transaction`; el panel de consultas añade ejemplos y el hint de `CREATE INDEX`/`DROP INDEX`/`BEGIN`/`END`/`ROLLBACK` | Corrige mi P0 #18 |

**Sigue abierto** (verificado a las 12:30): comentarios `--` y multi-sentencia, `columns: []` con 0 filas + `ResultsPanel.tsx:37`, columnas case-sensitive, `SELECT COUNT(*)` sin `GROUP BY`, y **todos** los modos de fallo del CSV (`query/csv_loader.py` no cambió en toda la revisión: hash `F385AAA9…`).

> Consecuencia práctica: dos hallazgos graves que encontré a las 12:05 (**`CREATE INDEX` y `BEGIN/END TRANSACTION` no existían en el parser**) **ya están arreglados** en el árbol vivo. Lo dejo documentado en §3 y §5 porque explican el feedback del profesor y porque el arreglo es de hace minutos: si la demo se grabó/ensayó antes de las 12:20, se grabó **sin** esas funciones.

Todo se ejecutó con directorios de datos *scratch* (`$env:BD2_DATA_DIR` / `data_dir=`), **nunca** `backend/data`.

---

## 1. Veredicto: ¿el flujo del profesor funciona hoy?

### **SÍ. El flujo completo (CREATE TABLE + CSV + las 5 consultas) funciona hoy, de punta a punta, tanto por el motor como por HTTP (el camino real del GUI).**

Transcripción literal, contra el API vivo (`uvicorn backend.api:app --port 8012`, `BD2_DATA_DIR=.review_tmp\data_api2`), con el `.sql` y el `.csv` **exactos** del profesor (`tests/fixtures/queries-proy.sql` es byte-a-byte idéntico al adjunto; el CSV adjunto tiene CRLF y la comilla con coma):

```
### 1) CREATE TABLE por HTTP
200 True CREATE TABLE None
    fila: [{'table': 'alumnos', 'storage': 'heap', 'primary_key': 'id',
            'columns': 'id INT, nombre VARCHAR(100), carrera_id INT, nota INT',
            'indexes': 'idx_alumnos_id_hash'}]

### 2) Importacion CSV por HTTP (csv_text real del profesor)
200 {"table": "alumnos", "columns": ["id", "nombre", "carrera_id", "nota"],
     "rows_read": 12, "inserted": 12, "failed": 0, "errors": [], "success": true}

### 3) Las 5 consultas del script, tal cual (con ';' final)
[2] "SELECT * FROM alumnos\nWHERE nombre = 'Pérez, Juan';"
    HTTP 200 success= True statement= SELECT error= None
    columns: ['id', 'nombre', 'carrera_id', 'nota']
       {"id": 3, "nombre": "Pérez, Juan", "carrera_id": 1, "nota": 14}
[3] 'SELECT * FROM alumnos\nWHERE nota >= 14\nORDER BY id;'
    HTTP 200 success= True statement= SELECT error= None
       {"id": 3,  "nombre": "Pérez, Juan",  "carrera_id": 1, "nota": 14}
       {"id": 4,  "nombre": "Elena Cruz",   "carrera_id": 3, "nota": 14}
       {"id": 8,  "nombre": "Luis Torres",  "carrera_id": 2, "nota": 15}
       {"id": 9,  "nombre": "Pedro Salas",  "carrera_id": 1, "nota": 19}
       {"id": 10, "nombre": "Lucía Vega",   "carrera_id": 2, "nota": 14}
       {"id": 11, "nombre": "Ana María",    "carrera_id": 3, "nota": 20}
[4] 'SELECT * FROM alumnos\nWHERE id = 999;'
    HTTP 200 success= True statement= SELECT error= None
    columns: []
[5] 'EXPLAIN\nSELECT * FROM alumnos\nWHERE nota >= 14\nORDER BY id;'
    HTTP 200 success= True statement= EXPLAIN error= None
    columns: ['plan']
[6] 'EXPLAIN ANALYZE\nSELECT * FROM alumnos\nWHERE nota >= 14\nORDER BY id;'
    HTTP 200 success= True statement= EXPLAIN error= None
    columns: ['plan']
```

Comprobaciones de correctitud (auditoría adicional `SELECT * FROM alumnos ORDER BY id`, camino motor):

* **12 filas** importadas (`row_count real en disco: 12`), `failed: 0`.
* Las 12 filas y sus acentos son correctos, incluidas las de borde:
  `{'id': 5, 'nombre': 'José Núñez', 'carrera_id': 1, 'nota': 0}` (nota 0 = celda legítima, no vacía) y
  `{'id': 12, 'nombre': 'Marta Díaz', 'carrera_id': 3, 'nota': 13}`.
* Literal con coma: `WHERE nombre = 'Pérez, Juan'` → **exactamente 1 fila**, `{'id': 3, 'nombre': 'Pérez, Juan', 'carrera_id': 1, 'nota': 14}`. La comilla dentro del CSV **no** rompe el import (`csv` de la stdlib).
* `nota >= 14 ORDER BY id` → **6 filas en orden ascendente de `id`**: `[3, 4, 8, 9, 10, 11]`, todas con `nota >= 14`.
* `id = 999` → **0 filas**, `success: true`.
* `EXPLAIN` → plan lógico sin ejecutar (`runtime_steps: []`); `EXPLAIN ANALYZE` → añade **traza real** (`HEAP_SCAN 0.87 ms out=12` → `FILTER 0.08 ms in=12 out=6` → `EXTERNAL_SORT 7.45 ms in=6 out=6`).
* También verificado por el camino del **CLI** (`tools/import_csv.py`) y por `engine.import_csv`:

```
$ python -m tools.import_csv --sql "CREATE TABLE alumnos (...)" \
      --table alumnos --file tests\fixtures\alumnos_prueba_bd2.csv --data-dir ...\.review_tmp\data_cli
SQL: CREATE TABLE alumnos (id INT PRIMARY KEY, nombre VARCHAR(100), carrera_id INT, nota INT)
  ok (CREATE TABLE)
Importación en 'alumnos'
  columnas mapeadas : id, nombre, carrera_id, nota
  filas leídas      : 12
  insertadas        : 12
  rechazadas        : 0
```

**Lo que sigue roto en el flujo del profesor (importante para la demo):**

1. **El script `.sql` completo NO se puede pegar en el panel de consultas.** Falla por los comentarios `--`:
   ```
   ### 4) Guion COMPLETO pegado de una vez (con comentarios --)
   HTTP 200 {"success": false, "statement": "UNKNOWN", ...,
             "error": "Unsupported SQL command: --"}
   ```
   Y aunque se quiten los comentarios, falla por multi-sentencia:
   ```
   ### 5) Guion completo sin comentarios, varias sentencias
   HTTP 200 {"success": false, "error": "CREATE TABLE: sufijo no soportado ';\n\n\n\nSELECT * FROM
             alumnos\nWHERE nombre = 'Pérez, Juan'; ...' (usa USING HEAP o USING SEQUENTIAL)"}
   ```
   El parser no soporta comentarios (`query/sql_parser.py:150-196`, no hay stripping) ni varias sentencias por petición. El test del equipo lo **esquiva** dividiendo el script en Python (`tests/test_profesor_script.py:22-34`), lo cual **oculta el problema al usuario**: en el GUI el profesor pega su script y recibe `Unsupported SQL command: --`.
   *El profesor va a pegar su script.* Esto es el mayor riesgo de demo restante.

2. **`SELECT * ... WHERE id = 999` (0 filas) se muestra en el panel de Resultados como si fuera una escritura.**
   `query_executor.py:1593-1597` devuelve `([], [])` (sin columnas) cuando no hay filas y `columns == ("*",)`;
   `frontend/src/panels/ResultsPanel.tsx:37` hace `const isRead = result.columns.length > 0;` → con 0 filas muestra
   **"Filas afectadas: 0"** y el texto **"La mutación se aplicó correctamente sobre el almacenamiento en disco."**
   La consulta #3 del profesor cae exactamente en este caso.

3. **La demo funciona solo con una sentencia por envío.** El GUI manda `sql.trim()` tal cual (`frontend/src/App.tsx:35-47`, `frontend/src/api.ts:18-25`); si el panel dividiera por `;` y quitara comentarios, los puntos 1 y 2 desaparecerían.

---

## 2. EXPLAIN / EXPLAIN ANALYZE reales y análisis del plan

### 2.1 Salida literal (consulta 4 del profesor)

```
{'plan': 'Tabla          : alumnos
Optimizador    : rule_based
Ruta de acceso : HEAP_SCAN
Índices usados : -
Plan lógico:
  1. HEAP_SCAN [alumnos] - no existe indice aplicable
  2. FILTER [alumnos] - predicados no resueltos por el camino de acceso
  3. EXTERNAL_SORT [alumnos] - el camino de acceso no garantiza el ORDER BY'}
```

### 2.2 Salida literal (consulta 5: EXPLAIN ANALYZE)

```
{'plan': 'Tabla          : alumnos
Optimizador    : rule_based
Ruta de acceso : HEAP_SCAN
Índices usados : -
Plan lógico:
  1. HEAP_SCAN [alumnos] - no existe indice aplicable
  2. FILTER [alumnos] - predicados no resueltos por el camino de acceso
  3. EXTERNAL_SORT [alumnos] - el camino de acceso no garantiza el ORDER BY
Ejecución real:
  1. HEAP_SCAN 0.8723 ms in=- out=12
  2. FILTER 0.0751 ms in=12 out=6
  3. EXTERNAL_SORT 7.449 ms in=6 out=6
Resumen: rows=6, execution_time_ms=8.5974'}
```

Y en el campo estructurado `execution_plan` (lo que consume el panel de plan):

```json
{"table": "alumnos", "planner_type": "rule_based", "access_path": "HEAP_SCAN",
 "used_indexes": [],
 "steps": [
   {"operator": "HEAP_SCAN", "table": "alumnos", "index": null,
    "reason": "no existe indice aplicable", "details": {}},
   {"operator": "FILTER", "table": "alumnos", "index": null,
    "reason": "predicados no resueltos por el camino de acceso",
    "details": {"predicates": [{"column": "nota", "operator": ">=", "value": 14}]}},
   {"operator": "EXTERNAL_SORT", "table": "alumnos", "index": null,
    "reason": "el camino de acceso no garantiza el ORDER BY",
    "details": {"columns": [{"column": "id", "direction": "ASC"}]}}],
 "runtime_steps": [
   {"operator": "HEAP_SCAN", "elapsed_ms": 0.5707, "rows_out": 12, "table": "alumnos", "index": null},
   {"operator": "FILTER", "elapsed_ms": 0.0425, "rows_in": 12, "rows_out": 6,
    "predicates": [{"column": "nota", "operator": ">=", "value": 14}], "disjunction": false},
   {"operator": "EXTERNAL_SORT", "elapsed_ms": 4.6175, "rows_in": 6, "rows_out": 6,
    "passes": [{"column": "id", "direction": "ASC", "initial_runs": 1,
                "merge_passes": 0, "temporary_files": 1}]}],
 "analyze": {"rows": 6, "execution_time_ms": 5.4164},
 "total_execution_time_ms": 5.9347}
```

### 2.3 Juicio del plan

| Pregunta | Respuesta | Evidencia |
|---|---|---|
| ¿Es correcto el plan? | **Sí.** Para `nota >= 14` no hay índice sobre `nota` (solo el hash de PK sobre `id`), y un hash no sirve para rangos; `ORDER BY id` con un hash tampoco se puede cubrir (el hash no conserva orden). `HEAP_SCAN + FILTER + EXTERNAL_SORT` es la decisión correcta. | `reason: "no existe indice aplicable"`; `used_indexes: []` |
| ¿Usa un índice? | **No en esta consulta**, y **lo dice**. | `Índices usados : -` |
| ¿Miente el plan (dice índice y hace scan, o al revés)? | **No.** La razón y los operadores coinciden con la traza real: los 3 operadores del plan lógico aparecen en `runtime_steps` con los mismos `rows_out` (12 → 6 → 6). El paquete `QueryExecutionError("access path ... requires an index")` (`query_executor.py:1284-1350`) hace imposible que el camino de acceso "finja" un índice. | traza real vs plan lógico |
| ¿Los conteos estimados/reales tienen sentido? | Sí: `in=- out=12` en el scan (12 filas), `in=12 out=6` en el filtro (6 con `nota>=14`), `in=6 out=6` en el sort. `analyze.rows = 6` coincide con las filas devueltas. | arriba |
| ¿Las cadenas `reason`/`details` son exactas y en español? | **Sí, y son honestas**: `"no existe indice aplicable"`, `"predicados no resueltos por el camino de acceso"`, `"el camino de acceso no garantiza el ORDER BY"`, `"Extendible Hashing es preferido para igualdad exacta"`, `"B+ clustered soporta range scan ordenado"`. | `query/query_planner.py:562-600` (candidatos), `:645-660` (`_fallback_scan`) |
| ¿Es "impresionante"? | El script del profesor, tal cual, es el peor caso para lucir índices (no hay índice secundario). **Pero la historia completa sí impresiona, y ahora se puede provocar en vivo** (ver §4): crear el índice y ver el cambio de plan. | abajo |

**Demo sugerida (verificada, salida literal):** con la tabla `alumnos` cargada,

```
EXPLAIN SELECT * FROM alumnos WHERE id = 3
  -> Ruta de acceso : HASH_INDEX_LOOKUP
     Índices usados : idx_alumnos_id_hash
     1. HASH_INDEX_LOOKUP [alumnos] usando idx_alumnos_id_hash - Extendible Hashing es preferido para igualdad exacta
EXPLAIN ANALYZE SELECT * FROM alumnos WHERE id = 3
  -> Ejecución real: 1. HASH_INDEX_LOOKUP 0.4789 ms in=- out=1 ; 2. FILTER 0.0277 ms in=1 out=1
```

y el cambio de plan **provocado por el usuario** (esto es "dinámico de verdad", verificado en el árbol vivo):

```
CREATE INDEX idx_nota ON alumnos (nota) USING BPLUS_CLUSTERED   -> OK, filas=12
EXPLAIN SELECT * FROM alumnos WHERE nota >= 15
  -> BPLUS_CLUSTERED_RANGE_SCAN   índices=['idx_nota']
DROP INDEX idx_nota
EXPLAIN SELECT * FROM alumnos WHERE nota >= 15
  -> HEAP_SCAN                    índices=[]
```

Un detalle de credibilidad a corregir: en `EXPLAIN` sin `ANALYZE`, `_render_plan` titula la sección **"Plan lógico"** pero cuando hay `ANALYZE` **sustituye** el payload por el de la ejecución real (`query_executor.py:1171-1268`, `_execute_explain` / `_render_plan`), de modo que "Plan lógico" e "Ejecución real" proceden de la misma corrida. No es incorrecto, pero un profesor exigente puede notar que el "plan lógico" cambió de operadores entre correr `EXPLAIN` y `EXPLAIN ANALYZE`.

---

## 3. Matriz de cobertura SQL

Probado por el camino del API (`DemoEngine.run`, idéntico a `POST /api/query`). Estados: **OK** / **POOR** (mensaje pobre o engañoso) / **NO** (no soportado). "Riesgo demo" = probabilidad de que el profesor lo teclee.

### 3.1 DDL

| Sentencia | ¿Soporta? | Mensaje de error real | Riesgo demo |
|---|---|---|---|
| `CREATE TABLE alumnos (id INT PRIMARY KEY, nombre VARCHAR(100), carrera_id INT, nota INT)` | **OK** | — | — |
| Multilínea / tabs / espacios raros | **OK** | — | — |
| `create table minus (id int primary key, x int)` | **OK** | — | — |
| `CREATE TABLE IF NOT EXISTS …` | **OK** | — | — |
| `CREATE TABLE t (a INT, b INT, PRIMARY KEY (a))` | **OK** | — | — |
| `CREATE TABLE t (a INT, b INT)` sin PK | **OK** (PK = 1.ª columna, documentado) | — | — |
| `USING SEQUENTIAL` / `USING HEAP` | **OK** | — | Documentado **solo en README** (`README.md:469-473`); el hint del GUI (`QueryPanel.tsx:92-96`) no lo menciona |
| `CREATE TABLE mal_tipo (id INT PRIMARY KEY, x DATE)` | NO (tipos INT/FLOAT/VARCHAR) | `Tipo de columna no soportado: DATE (usa INT, FLOAT o VARCHAR(n))` | — |
| `DROP TABLE t` / `DROP TABLE IF EXISTS t` | **OK** | `unknown table: no_existe` | — |
| **`CREATE INDEX idx_nota ON alumnos (nota)`** | **OK** (¡nuevo!) | — | — |
| `CREATE INDEX … USING HASH\|BPLUS_CLUSTERED\|BPLUS_UNCLUSTERED` | **OK** | `CREATE INDEX: técnica desconocida 'X' (usa HASH, BPLUS_CLUSTERED o BPLUS_UNCLUSTERED)` | — |
| `CREATE INDEX ON t (col)` (sin nombre) | **OK** (auto-nombre `idx_<tabla>_<col>_bpu`) | — | — |
| `CREATE UNIQUE INDEX …` sobre columna ya indexada | NO | `la columna 'v' de 'sin_nombre' ya tiene el índice idx_sin_nombre_v_bpu; usa DROP INDEX antes de crear otro` | Bajo, pero **`IF NOT EXISTS` no ayuda**: `CREATE INDEX IF NOT EXISTS otro_nombre ON t (col_indexada)` falla igual (el guardián es por *nombre*, no por *columna*). Sugerencia: si la columna ya tiene índice del mismo tipo, devolver OK idempotente |
| `CREATE INDEX … (col_inexistente)` | NO | `la columna 'no_existe' no existe en la tabla 'cuentas'` | — |
| `DROP INDEX nombre` / `DROP INDEX IF EXISTS nombre` | **OK** | `no existe el índice 'idx_c1'` | — |
| `CREATE TABLE … AS SELECT` | NO | `Syntax error: se esperaba CREATE TABLE nombre (columna TIPO, ...)` — **engañoso**: el usuario escribió `CREATE TABLE ... AS`, no un error de paréntesis | Medio |
| `TRUNCATE TABLE t` | NO | `Unsupported SQL command: TRUNCATE` | Medio |
| `ALTER TABLE t ADD/DROP COLUMN x` | NO | `Unsupported SQL command: ALTER` | Medio |
| `RENAME TABLE t TO t2` | NO | `Unsupported SQL command: RENAME` | Bajo |
| `CREATE DATABASE` / `CREATE VIEW` | NO | `Syntax error: se esperaba CREATE TABLE nombre (columna TIPO, ...)` — **engañoso**, dice "CREATE TABLE" a quien escribió `CREATE VIEW`/`CREATE DATABASE` | Bajo |
| `CREATE INDEX` en la revisión de 12:05 | **NO** | `Syntax error: se esperaba CREATE TABLE …` / `'QueryExecutor' object has no attribute '_execute_create_index'` | **Ya arreglado a las 12:20** |

### 3.2 SELECT

| Sentencia | ¿Soporta? | Mensaje real | Riesgo |
|---|---|---|---|
| `SELECT * FROM t` / minúsculas / `FROM T` (tabla en mayúsculas) | **OK** | — | — |
| `SELECT * FROM t;` / `;;` | **OK** | — | — |
| Multilínea, tabs, doble espacio, CRLF | **OK** | — | — |
| `SELECT id, name FROM t` | **OK** | — | — |
| `SELECT ID, NOMBRE FROM ALUMNOS WHERE NOTA >= 14` (**columnas en mayúsculas**) | **NO** | `unknown column 'NOTA' in table 'alumnos'` | **ALTO**: el nombre de tabla es case-insensitive (`catalog.py:62-65` normaliza a minúsculas) pero **las columnas no** (`query_executor.py:1709-1746` compara literal). Un profesor que escriba el WHERE en mayúsculas recibe un error incomprensible porque `FROM ALUMNOS` sí funcionó |
| `SELECT id AS identificador FROM t` (alias de columna sin agregado) | NO | `Unsupported SELECT expression: id AS identificador` | Medio |
| `SELECT DISTINCT dept FROM t` | NO | `Unsupported SELECT expression: DISTINCT dept` | Medio |
| `SELECT COUNT(*) FROM t` (**sin GROUP BY**) | **NO** | `aggregate functions currently require GROUP BY` | **ALTO**: es la consulta más natural del mundo y está en el ❌ del README (`README.md:488`). Peor: **el ejecutor viejo sí la soporta** (ver §6) |
| `SELECT SUM(age), MIN(age), MAX(age) FROM t` | NO (mismo motivo) | idem | Medio |
| `SELECT dept, COUNT(*) AS total, AVG(salary) AS prom FROM t GROUP BY dept` | **OK** (`columns=['dept','count_all']` si no hay alias) | — | — |
| `SELECT dept FROM t GROUP BY dept` | **OK** | — | — |
| `ORDER BY a DESC, b ASC` (multiclave, ASC/DESC) | **OK** | — | — |
| `LIMIT n` | **OK** | — | — |
| `LIMIT 2 OFFSET 1` / `OFFSET` | NO | `LIMIT solo admite un entero positivo (recibido: 2 OFFSET 1)` | Medio |
| `LIMIT -1` | NO | `LIMIT solo admite un entero positivo (recibido: -1)` | Bajo |
| `SELECT TOP 3 * FROM t` | NO | `Unsupported SELECT expression: TOP 3 *` | Bajo |
| `WHERE cond AND cond` | **OK** | — | — |
| `WHERE a = 1 OR b = 2` | **OK** (ahora con `HASH_INDEX_UNION` / `BPLUS_INDEX_UNION` si hay índice) | — | — |
| `WHERE (edad >= 20)` — **paréntesis** | **NO** | `Expected a column in WHERE near: (age >= 20)` | **ALTO**: los paréntesis son lo primero que escribe cualquiera |
| `WHERE a >= 20 AND (b = 'CS')` | NO | `Expected a column in WHERE near: (dept = 'CS')` | **ALTO** |
| `WHERE dept IN ('CS','EE')` | NO | `Expected a comparison operator after 'dept'` | **ALTO** |
| `WHERE name LIKE 'Ana%'` / `NOT LIKE` | NO | `Expected a comparison operator after 'name'` | **ALTO** |
| `WHERE NOT age = 20` | NO | `Expected a comparison operator after 'NOT'` | Medio |
| `WHERE name IS NULL` / `IS NOT NULL` | NO | `Expected a comparison operator after 'name'` | **ALTO** (y asimétrico: `INSERT … NULL` sí se acepta en VARCHAR) |
| `WHERE a <> 20` / `!=` | **OK** | — | — |
| `WHERE age BETWEEN 19 AND 25` | **OK** | — | — |
| `WHERE a >= 19 AND a <= 23` | **OK** (el planner lo fusiona en un rango para el índice) | — | — |
| Decimales / negativos (`WHERE age > 19.5`, `age > -1`) | **OK** | — | — |
| Literales `'Pérez, Juan'`, `'O''Brien'`, `"Pérez, Juan"`, `'a;b'`, `'a--b'`, `'a/*b*/c'`, salto dentro del literal, acentos, ñ, emoji | **OK** | — | — |
| `WHERE nota >= 14 AND` (AND colgante al final) | **OK silencioso** → devuelve 6 filas | — | Bajo pero feo: SQL inválido aceptado. `query/sql_parser.py:846-940` consume el `AND` y no exige un predicado después |
| `WHERE nota >= 14 OR` (OR colgante) | NO | `WHERE contiene un OR sin condición` | — |
| `WHERE … AND AND …` | NO | `Expected a comparison operator after 'AND'` | — |
| `SELECT * FROM t WHERE` | NO | `WHERE clause cannot be empty` | — |
| `SELECT 1` | NO | `SELECT requires a FROM clause` | Bajo |
| `SELECT banana FROM t` | NO | `unknown selected column 'banana'` | — |
| `WHERE name = 'sin cerrar` | NO | `Unterminated quoted string` | — |
| **SQL con BOM inicial** (`\ufeffSELECT …`, típico de copiar/pegar de Word/Notepad) | **NO** | `Unsupported SQL command: SELECT` | Medio: el mensaje muestra "SELECT" y parece un bug del motor. Arreglo trivial: `clean_sql = sql.strip().lstrip("\ufeff")` en `sql_parser.py:165` |
| **Comentarios `--` y `/* */`** | **NO** | `--`: `Unsupported SQL command: --`; `SELECT … -- fin`: `Unsupported text after FROM clause: -- fin`; `/* */`: `Unsupported SQL command: /*` | **ALTO: el script del profesor los tiene** |
| **Varias sentencias en una petición** | **NO** | `Unsupported text after FROM clause: ; SELECT * FROM departments` (SELECT) o `CREATE TABLE: sufijo no soportado '; CREATE TABLE m2 …'` (DDL) | **ALTO** |
| Sólo `;` | NO | `Empty SQL statement` | — |

### 3.3 DML

| Sentencia | ¿Soporta? | Mensaje real | Riesgo |
|---|---|---|---|
| `INSERT INTO t VALUES (…)` | **OK** | — | — |
| `INSERT INTO t (cols) VALUES (…)` (**lista de columnas**) | **NO** | `Syntax error in INSERT statement: INSERT INTO users (id, name, age, dept) VALUES (…)` | **ALTO**: es la forma habitual cuando no recuerdas el orden del esquema |
| PK duplicada | NO (correcto) | `duplicate hash key: 99` — **pobre**: no dice tabla, ni columna, ni "clave primaria". Además **no se traduce al usuario** | **ALTO** para la demo de CSV con duplicados |
| Aridad incorrecta | NO | `INSERT expected 4 values for table 'users', got 3` (bien) | — |
| `INSERT … NULL` en columna **INT/FLOAT** | **NO** | `int() argument must be a string, a bytes-like object or a real number, not 'NoneType'` — **fuga de excepción de Python** al usuario | **ALTO** si el profesor prueba NULL en una nota; en VARCHAR sí funciona |
| `UPDATE t SET c = v WHERE …` | **OK** | — | — |
| `UPDATE t SET c = c + 1` (expresión) | **NO** | `invalid literal for int() with base 10: 'age + 1'` — **fuga de excepción de Python** | Medio |
| `UPDATE t SET nope = 1` | NO | `unknown column 'nope' in UPDATE of 'users'` | — |
| `UPDATE t SET c = v` (sin WHERE) | **OK** (afecta a todo) | — | — |
| `DELETE FROM t WHERE c = v` | **OK** | — | — |
| `DELETE FROM t` (sin WHERE) | **OK** | — | — |
| `DELETE * FROM t` | NO | `Syntax error in DELETE statement: …` | Bajo |
| `DELETE FROM t WHERE c IN (…)` | NO | `Expected a comparison operator after 'dept'` | Medio |

### 3.4 EXPLAIN / transacciones / otros

| Sentencia | ¿Soporta? | Mensaje real | Riesgo |
|---|---|---|---|
| `EXPLAIN <select>` | **OK** (no ejecuta) | — | — |
| `EXPLAIN ANALYZE <select>` | **OK** (ejecuta + traza) | — | — |
| `EXPLAIN <insert/update/delete/ddl>` | **OK** (devuelve plan "direct_write") | — | — |
| `EXPLAIN ANALYZE <insert>` | **OK — y ejecuta de verdad** (consistente con Postgres, pero conviene avisarlo) | — | Medio |
| `EXPLAIN EXPLAIN …` | NO | `EXPLAIN anidado no está soportado` | — |
| `EXPLAIN` solo | NO | `Syntax error: se esperaba EXPLAIN [ANALYZE] ...` | — |
| **`BEGIN TRANSACTION` / `BEGIN` / `START TRANSACTION`** | **OK** (¡nuevo!) | `ya hay una transacción activa (T1); usa COMMIT o ROLLBACK antes de iniciar otra` | — |
| **`END TRANSACTION` / `COMMIT` / `ROLLBACK`** | **OK** (¡nuevo!) | `COMMIT: no hay una transacción activa (ejecuta BEGIN TRANSACTION primero)` | — |
| `BEGIN TRANSACTION; INSERT …; END TRANSACTION` (una línea) | **NO** (multi-sentencia) | `Syntax error: sentencia de transacción no soportada '…'` | Medio |
| `SHOW TABLES`, `DESCRIBE t`, `\dt` | NO | `Unsupported SQL command: SHOW/DESCRIBE/\DT` | Medio (el profesor pedirá ver la tabla) |
| `INVALID GIBBERISH` | NO | `Unsupported SQL command: INVALID` | — |

---

## 4. Importación CSV

### 4.1 Caminos disponibles

| Camino | Entrada | Dónde | ¿Funciona? |
|---|---|---|---|
| Motor | `DemoEngine.import_csv(tabla, source, has_header, delimiter, encoding, max_errors)` | `backend/engine.py:114-124` | Sí |
| API REST | `POST /api/tables/{t}/import` con JSON `{csv_text, has_header, delimiter}` | `backend/api.py:41-45, 71-83` | Sí |
| GUI | `<input type="file">` → `file.text()` → mismo `POST` | `frontend/src/panels/FilesPanel.tsx:51-73`, `frontend/src/api.ts:37-47` | Sí, **pero requiere seleccionar una tabla ya existente** (`disabled={!table \|\| importing}`) |
| CLI | `python -m tools.import_csv --table t --file f [--sql DDL] [--no-headers] [--delimiter ;] [--encoding X] [--data-dir D]` | `tools/import_csv.py` | Sí |

* **¿La tabla debe existir antes?** **Sí.** `query/csv_loader.py:96` → `executor.catalog.get_table(table_name)` → `CatalogError: unknown table`. Por HTTP: `HTTP 400 {"detail":"unknown table: no_existe"}`. El flujo del GUI es: crear la tabla en el panel de consultas → recargar → seleccionar → subir. **Verificado que el GUI puede hacerlo** (`App.tsx:41` recarga las tablas tras cada sentencia).
* **¿El CLI crea la tabla?** Sí, con `--sql "CREATE TABLE …"` (verificado, 12/12 filas).
* **Mapeo de columnas:** **por nombre de encabezado** si **todos** los nombres del esquema aparecen en el encabezado; **si no, por posición, en silencio** (`csv_loader.py:111-121`). ← el gran riesgo, ver 4.2 #4.
* **Subida real de archivo:** el GUI usa un `input type=file` real, pero el transporte es **JSON con el CSV como string** (`api.ts:45`): no hay `multipart/form-data`, y `has_header`/`delimiter` están **fijos** en el cliente (`,` y `true`). `encoding` **no se expone en ningún camino del GUI ni del API** (solo el CLI tiene `--encoding`).

### 4.2 Modos de fallo, con el input exacto que los provoca

Todos verificados; salida literal:

| # | Input exacto | Resultado real | Gravedad |
|---|---|---|---|
| 1 | `--file tests\fixtures\no_existe_typo.csv` (o `import_csv("alumnos","C:\no\existe.csv")`) | `filas leídas: 0, insertadas: 0, rechazadas: 0`, **`exit=0`**, y el reporte dice **`"success": true`** | **CRÍTICO**: un nombre mal escrito produce "éxito" sin datos. Causa: `query/csv_loader.py:49-66` — si el string no es un fichero existente, **se interpreta como contenido CSV**. `CsvImportReport.success` (`:33-35`) es `failed == 0`, y `tools/import_csv.py:104` devuelve 0. **Arreglo:** si `source` es `str`/`Path` sin saltos de línea y no existe → `raise`/`failed=1` con "no se encontró el archivo X"; y `success = (failed == 0 and rows_read > 0)` |
| 2 | `id,nombre,carrera_id,nota` + `"1,Ana,2,ABC"` | `{"rows_read": 3, "inserted": 1, "failed": 2, "errors": ["fila 1: could not convert string to float: 'ABC'", "fila 2: could not convert string to float: 'x'"], "success": false}` | Media: el import es **parcial** (1 de 3 filas) — ¿es lo deseado? El mensaje filtra el error de Python **en inglés**, sin columna ni valor esperado |
| 3 | PK duplicada: `"1,Ana,2,15\n1,Otra,2,16\n2,Beto,3,18"` | `inserted: 2, failed: 1, errors: ["fila 2: duplicate hash key: 1"]` | Media: **importación parcial con reporte** (bien), mensaje pobre |
| 4 | Encabezado con otros nombres **y otro orden**: `NOTA,NOMBRE,ID,CARRERA` + `15,Ana,1,2` | `success: true`, y en la tabla queda `{'id': 15, 'nombre': 'Ana', 'carrera_id': 1, 'nota': 2}` | **CRÍTICO**: **corrupción silenciosa de datos**. El fallback posicional (`csv_loader.py:116-117`) mapea por posición sin avisar. Con un CSV en inglés (`id,name,score`) o con el encabezado en otro orden y otros nombres, los datos entran mal y el reporte dice OK |
| 5 | Faltan columnas: `id,nombre` + `1,Ana` (tabla de 4) | `success: true`, filas `{'id': 1, 'nombre': 'Ana', 'carrera_id': 0, 'nota': 0}` | Alta: celdas ausentes → **0** (`csv_loader.py:129`, `:69-75`). No se distingue "vacío" de "cero" |
| 6 | Celdas vacías: `1,,,14` | `{'id': 1, 'nombre': '', 'carrera_id': 0, 'nota': 14}` | Alta: `""` → `0` / `""` sin aviso |
| 7 | `"NULL"` como texto en una celda | Se guarda la **cadena** `'NULL'`, no `NULL` | Baja pero incoherente con el SQL (`INSERT … NULL` sí produce NULL en VARCHAR) |
| 8 | BOM UTF-8: `\ufeffid,nombre,…` | El encabezado no coincide (`\ufeffid` ≠ `id`) → **fallback posicional**; aquí funcionó de casualidad por el orden, pero con BOM + otro orden → caso #4 | Alta: `csv_loader.py:112` hace `.strip().lower()`, que **no** quita `\ufeff`. Arreglo: `encoding="utf-8-sig"` por defecto |
| 9 | CSV **latin-1** (`José Núñez` en bytes 0xE9) por el GUI | El navegador hace `file.text()` (UTF-8 con reemplazo) → se guarda **`'Jos� N��ez'`** con `success: true` | **CRÍTICO de cara a la demo**: caracteres corruptos sin ningún aviso. Y si se pasa `encoding="utf-8"` a bytes latin-1 (CLI equivocado), salta `UnicodeDecodeError` **desde `csv_loader.py:56`**, que escapa de `import_csv` (no hay `try`) y HTTP devuelve 400 sin reporte |
| 10 | `has_header=True` (default) sobre un CSV **sin** encabezado: `1,Ana,2,15\n2,Beto,3,18` | La primera fila se come como encabezado → **se pierde la fila del id 1** en silencio (`success: true`) | Alta |
| 11 | Archivo vacío o solo encabezado | `rows_read: 0, inserted: 0, failed: 0, "success": true` | Media: reportar éxito con 0 filas |
| 12 | `VARCHAR(100)` con un nombre de 150 caracteres | Se guarda truncado a **100 bytes**, `success: true`, sin aviso (`storage/record.py:62`) | Media |
| 13 | `VARCHAR(2)` con `'ñe'` (3 bytes UTF-8) / `'😀'` (4 bytes) | Se guarda `'ñ'` / `''` (porque `record.py:62` corta **bytes** y `record.py:73` decodifica con `errors="ignore"`) | Media: **pérdida silenciosa de caracteres**; `VARCHAR(n)` cuenta bytes, no caracteres |
| 14 | FLOAT con `1e400` | Se guarda `inf` con `success: true` | Baja |
| 15 | 20 000 filas | Funciona: `rows_read: 20000, inserted: 20000`, pero el proceso tardó > 2 min | Media: `csv_loader.py:100-105` **carga el fichero entero en memoria** (lista de listas) y hace 1 INSERT por fila con `catalog.rebuild_indexes` en tablas secuenciales. No hay streaming ni `executemany` |
| 16 | Comillas dobladas, comas y salto de línea dentro de un campo | **Correcto**: `'Pérez, Juan'`, `'Dijo "hola"'`, `'Con\nsalto'` | OK (lo único realmente sólido del importador) |
| 17 | `delimiter=';'` (CLI y API) | **OK** | OK |
| 18 | `has_header=False` (CLI y API) | **OK** | OK |
| 19 | Tabla `USING SEQUENTIAL` + CSV del profesor | **OK**: 12/12 y `SELECT … WHERE id = 12` por índice | OK |
| 20 | Índice secundario + reorganización del Archivo Secuencial (40 altas, 20 bajas, 10 altas) | **Coherente**: `BPLUS_UNCLUSTERED_RANGE_SCAN` devuelve los mismos ids que `SEQUENTIAL_SCAN` (`IGUALES: True`) | OK — sin resultados fantasma por RID inválidos |

### 4.3 ¿Qué falta para que sea "dinámico de verdad"?

1. **Subir el archivo entero en un solo POST** (`multipart/form-data`) y **detectar la codificación** (`utf-8-sig` → `utf-8` → `cp1252/latin-1`) con aviso al usuario. Hoy `file.text()` destruye cualquier CSV no-UTF-8 sin avisar (4.2 #9).
2. **No adivinar el mapeo**: si el encabezado no coincide, **abortar** o abrir un paso de confirmación con la correspondencia propuesta. Nunca importar por posición en silencio (4.2 #4).
3. **Vista previa / dry-run**: primeras 5 filas + columnas detectadas + tipos inferidos, antes de escribir.
4. **Reporte honesto**: `success = failed == 0 AND rows_read > 0`; devolver `inserted + failed == rows_read`; diferenciar "archivo no encontrado" de "CSV vacío" (4.2 #1, #11).
5. **Modo transaccional interactivo**: importar dentro de un `BEGIN` y hacer `ROLLBACK` si supera `max_errors` (hoy deja importaciones a medias sin pedirlo).
6. **Streaming** (`csv.reader` sobre el fichero, no sobre una lista) y **inserción por lotes**; el caso 20 000 filas debe tardar segundos, no minutos.
7. **Separar "vacío" de "cero"**: `""` → `NULL` (con `IS NULL` soportado) o error, no `0` silencioso (4.2 #5, #6).
8. **Índices: ya se pueden crear desde SQL** (`CREATE INDEX` / `DROP INDEX`, verificado en §3.1 y §2.3) y **persisten** entre reinicios (verificado: `catalog.json` los guarda y tras reiniciar el planner los usa). Lo que falta es **descubribilidad y control**: el hint del panel (`QueryPanel.tsx:92-96`) no los menciona, no hay ejemplos en `EXAMPLE_GROUPS`, `IF NOT EXISTS` no es idempotente por columna, y no hay UI para elegir técnica (HASH / B+ agrupado / no agrupado) más allá de escribir el `USING …`.
9. **`TRUNCATE` / `ALTER TABLE` / `CREATE TABLE … AS SELECT`**: siguen fuera; `TRUNCATE` y `ALTER TABLE ADD COLUMN` son los candidatos más rentables para "más dinámico".
10. **`INSERT INTO t (cols) VALUES`**: imprescindible en cuanto el CSV tenga un subconjunto de columnas.

---

## 5. Transacciones y concurrencia

### 5.1 ¿Está integrado con el API/GUI? **SÍ, hoy** (no lo estaba a las 12:05)

Verificado **por HTTP**, en el mismo camino que usa el GUI (`POST /api/query` → `DemoEngine.run` → `QueryExecutor.execute`):

```
### 6) Transacciones por HTTP
    'BEGIN TRANSACTION'    -> HTTP 200 success=True  error=None
    'END TRANSACTION'      -> HTTP 200 success=True  error=None
    'COMMIT'               -> HTTP 200 success=False error=COMMIT: no hay una transacción activa (ejecuta BEGIN TRANSACTION primero)
    'ROLLBACK'             -> HTTP 200 success=False error=ROLLBACK: no hay una transacción activa (ejecuta BEGIN TRANSACTION primero)
```

Y el ciclo completo con datos reales en disco (ROLLBACK revierte de verdad):

```
BEGIN TRANSACTION
  {"transaction": "T1", "estado": "activa", "sentencias": 0}
INSERT INTO cuentas VALUES (3, 25)          -> OK
UPDATE cuentas SET saldo = 0 WHERE id = 1   -> OK
SELECT * FROM cuentas ORDER BY id -> [{id:1,saldo:0},{id:2,saldo:50},{id:3,saldo:25}]
ROLLBACK
  {"transaction":"T1","estado":"revertida (ROLLBACK)","tablas_restauradas":"cuentas"}
SELECT * FROM cuentas ORDER BY id -> [{id:1,saldo:100},{id:2,saldo:50}]   <-- restaurado
```

También verificado:
* `BEGIN … COMMIT` conserva los cambios.
* `BEGIN … CREATE TABLE … CREATE INDEX … ROLLBACK` → la tabla nueva desaparece (`unknown table: nueva`).
* `BEGIN … DROP TABLE cuentas … ROLLBACK` → la tabla **vuelve con sus filas** (`[{1,100},{2,50},{4,10}]`).
* `ROLLBACK` sin transacción / doble `BEGIN` → mensajes claros en español.

**Implementación** (`query/query_executor.py`): `TransactionState` con snapshot completo por tabla en la **primera** escritura (`_snapshot_for_write`, líneas 940-975), bloqueo **exclusivo por tabla** (`lock_manager.acquire_exclusive(txn.id, table.name)`), buffer de deshacer para DDL (`ddl_undo`), y ROLLBACK que restaura con `storage.replace_all(...)` + `catalog.rebuild_indexes(...)` (líneas 825-901). Es 2PL estricto *a nivel de tabla* para las tablas que toca.

Visibilidad en el GUI (añadida a las 12:28-12:29, mientras redactaba): `backend/engine.py:129-145` expone `transaction_state()`, `backend/api.py:48-56` lo devuelve en `GET /api/health` (`{"status","tables","transaction"}`) y `frontend/src/panels/QueryPanel.tsx:92-104` incluye un grupo de ejemplos con los 4 pasos `BEGIN → DML → END/ROLLBACK`. Buen trabajo: es exactamente lo que faltaba para poder demostrar transacciones desde la interfaz.

### 5.2 La limitación que hay que decir en voz alta

**Solo puede haber UNA transacción activa por ejecutor**, y el API tiene **un único** `DemoEngine`/`QueryExecutor` global (`backend/engine.py:101, 231`). Prueba literal:

```
### H) Dos transacciones solapadas (mismo ejecutor/API)
    OK  'BEGIN TRANSACTION'      -> T7
    OK  'INSERT INTO cuentas VALUES (9, 9)'
    segundo BEGIN -> False  ya hay una transacción activa (T7); usa COMMIT o ROLLBACK antes de iniciar otra
```

Consecuencias:
* **La "demostración obligatoria" (2.1.4: varias transacciones simultáneas, race condition visible y cómo el sistema la maneja) NO se puede hacer desde el GUI ni desde SQL.** Dos ventanas del navegador comparten el mismo proceso y el segundo `BEGIN` se rechaza. Un profesor que pida "abre dos sesiones y hazlo concurrente" no se puede satisfacer por la interfaz.
* El `LockManager` del ejecutor queda **de adorno** para el caso multi-transacción: nunca dos transacciones compiten por la misma tabla porque solo existe una. Sí evita el auto-bloqueo, y sí produce `RecursoBloqueado` a los 2 s (`lock_manager.py:19`) si se usara con dos ejecutores.

### 5.3 La demo con hilos (`transactions/demo_concurrencia.py`): funciona, pero está desconectada del motor

Ejecutada tal cual (`python -m transactions.demo_concurrencia`, documentado en `README.md:390`):

```
--- CASO 1: SIN control de concurrencia (sin locks) ---
    T1 (X = X - 10) (T1) leyo X=100, escribio X=90, COMMIT
    T2 (X = X + 100) (T2) leyo X=100, escribio X=200, COMMIT
   Intento 1: X final = 200 (esperado 190) -> *** RACE CONDITION: SE PERDIO UNA ACTUALIZACION ***
   ...
--- CASO 2: CON control de concurrencia (bloqueo exclusivo PX) ---
    T1 (X = X - 10) (T7) leyo X=100, escribio X=90, COMMIT
    T2 (X = X + 100) (T8) leyo X=90, escribio X=190, COMMIT
   Intento 1: X final = 190 (esperado 190) -> CORRECTO
```

Cumple literalmente el enunciado (varias transacciones, race condition visible en 3/3 intentos, resolución correcta) **pero la "tabla" es un `dict` de Python** (`demo_concurrencia.py:21`: `tabla = {"X": 100}`), no una tabla del motor: no pasa por `HeapFile`, ni por el parser, ni por el API. Es una demo de un `LockManager` genérico.

**Lo que falta frente al enunciado 2.1.4:**
* 2PL: no hay verificación del protocolo (no se impide adquirir un lock después de liberar otro); el lock se toma en `leer`/`escribir`, así que es estricto *de facto* solo en el ejecutor nuevo.
* **Detección de interbloqueos: no hay.** No existe grafo de espera; el deadlock se resuelve por **timeout de 2 s** (`lock_manager.py:19, 41-45, 61-65`) → `RecursoBloqueado`, y en la demo eso acaba en ROLLBACK. Sin reintentos ni backoff.
* **Sin niveles de aislamiento** (no hay READ COMMITTED / REPEATABLE READ), sin detección de escrituras perdidas, sin versiones ni timestamps.
* Granularidad: **por tabla** en el ejecutor, por *clave de diccionario* en el `LockManager`; no hay locks por fila ni por página (el enunciado del curso no lo pide explícitamente, pero "múltiples usuarios" sí sugiere granularidad fina).
* La demo con hilos **no usa** `QueryExecutor` ni `TransactionState`; son dos mundos. Idealmente `demo_concurrencia.py` debería lanzar dos `QueryExecutor` (uno por hilo) sobre el mismo `Catalog` y mostrar el conflicto real sobre una tabla del motor.

---

## 6. Arquitectura: duplicación de ejecutores

Hay **dos ejecutores** y **dos catálogos** distintos:

| | `query/query_executor.py` (nuevo) | `query/executor.py` (viejo) |
|---|---|---|
| Clases | `QueryExecutor` + `query/catalog.py::Catalog` | `QueryExecutor` + su propio `Catalog`/`TableDefinition`/`IndexHandle` (`query/executor.py:90-281`) |
| Lo usa | **API/GUI** (`backend/engine.py:22,101`), `query/test_query_executor.py:6` | `examples/demo_parte1.py:26-28`, `tests/test_end_to_end.py:22-24`, `tests/test_storage_integration.py:24` |
| Entrada | `execute(sql_o_ast)` y `execute_sql` | sólo `execute_sql` (su `execute()` rechaza strings: `TypeError: sentencia no soportada: str`) |
| DDL | CREATE/DROP TABLE, **CREATE/DROP INDEX**, transacciones | ❌ `TypeError: sentencia no soportada: CreateTableStatement` (excepción sin capturar, `query/executor.py:345`) |
| UPDATE / LIMIT | ✅ UPDATE, ✅ LIMIT | ❌ `TypeError: … UpdateStatement`; **LIMIT se ignora en silencio** (`query/executor.py:356-400` nunca lee `statement.limit`) |
| OR | ✅ | ❌ **devuelve 0 filas / borra 0 filas** (`or_groups` ignorado, `query/executor.py:482-490, 611-620`) |
| Agregados sin GROUP BY | ❌ error | ✅ funciona |

Prueba literal sobre el **mismo SQL** (ambos ejecutores, mismos datos):

```
#### EJECUTOR NUEVO (query/query_executor.py = API/GUI) ####
  'SELECT COUNT(*) FROM users'          success=False error=aggregate functions currently require GROUP BY
  'SELECT * FROM users WHERE id = 1 OR id = 2'  success=True  filas=2
  'DELETE FROM users WHERE id = 1 OR id = 2'    success=True  affected=2
  'SELECT * FROM users ORDER BY age LIMIT 2'    success=True  filas=2
  'CREATE TABLE nueva …'                success=True
  'UPDATE users SET age = 1 WHERE id = 3'       success=True
  'BEGIN TRANSACTION'                   success=True

#### EJECUTOR VIEJO (query/executor.py = examples y tests) ####
  'SELECT COUNT(*) FROM users'          kind=SELECT filas=1 rows=[{'COUNT(*)': 3}]
  'SELECT * FROM users WHERE id = 1 OR id = 2'  kind=SELECT filas=0 rows=[]
  'DELETE FROM users WHERE id = 1 OR id = 2'    kind=DELETE affected=0   (¡no borra nada!)
  'SELECT * FROM users ORDER BY age LIMIT 2'    kind=SELECT filas=3      (¡LIMIT ignorado!)
  'CREATE TABLE nueva …'                EXCEPCION TypeError: sentencia no soportada: CreateTableStatement
  'UPDATE users SET age = 1 WHERE id = 3'        EXCEPCION TypeError: sentencia no soportada: UpdateStatement
  'BEGIN TRANSACTION'                   EXCEPCION TypeError: sentencia no soportada: TransactionStatement
```

**Riesgos concretos:**
1. **Discrepancia en demo:** si el equipo enseña `examples/demo_parte1.py` (ejecutor viejo) y luego el GUI (ejecutor nuevo), **la misma consulta da resultados distintos**: `LIMIT` se ignora en el viejo (devuelve 3 filas en vez de 2) y `WHERE a OR b` devuelve vacío.
2. **Resultados silenciosamente incorrectos en el camino viejo:** `DELETE … WHERE a=1 OR b=2` no borra nada y no avisa (afectados=0); `LIMIT n` devuelve todo.
3. **Caída con traceback** en el camino viejo (`TypeError` crudo) para UPDATE/DDL/transacciones, mientras el nuevo devuelve `success=false` con mensaje. El README promete "Mensajes de error claros y sin excepciones hacia el API" (`README.md:~300`) — cierto solo en el camino nuevo.
4. **Riesgo de "dice índice pero escanea":** en el viejo, si el planner elige un índice que la `TableDefinition` no tiene, `query/executor.py:405-410` **cae a `table.scan()` en silencio** mientras `result.stats["access_path"]` sigue anunciando `BPLUS_*`/`HASH_INDEX_LOOKUP`. En el nuevo, `_execute_access_path` **lanza** (`query_executor.py:1284-1350`), así que no puede mentir. (No logré reproducirlo con la configuración por defecto —el planner se construye del mismo catálogo—, pero el código lo permite y es la peor clase de bug para una demo de planes.)
5. **Divergencia de comportamiento ya visible en los tests:** `tests/test_end_to_end.py` prueba el ejecutor viejo y `query/test_query_executor.py` el nuevo; un cambio en uno no se valida en el otro.

**Recomendación:** consolidar en `query/query_executor.py` + `query/catalog.py`; migrar `examples/demo_parte1.py`, `tests/test_end_to_end.py` y `tests/test_storage_integration.py` al ejecutor nuevo; y dejar `query/executor.py` como *shim* de compatibilidad (o borrarlo) para que no existan dos semánticas de `LIMIT`/`OR`/DDL. Un comentario en `query/executor.py:1-24` ("Fuera de alcance: CREATE TABLE … transacciones (issue aparte)") es hoy **falso** y engaña al lector y al evaluador.

---

## 7. Lista priorizada de arreglos concretos

Orden: primero lo que puede romper la demo en vivo.

### P0 — Rompe la demo del profesor

| # | Archivo:línea | Cambio propuesto | Prueba que lo demuestra |
|---|---|---|---|
| 1 | `query/sql_parser.py:150-196` (`parse`) + `backend/api.py:86-89` | Aceptar el script completo: (a) eliminar comentarios `--…\n` y `/*…*/` antes de parsear; (b) `lstrip("\ufeff")`; (c) si tras quitar el `;` final queda más texto, dividir por `;` de nivel superior y ejecutar en secuencia, devolviendo el último resultado (o un array de resultados). Mínimo viable: dividir y ejecutar en orden. | `POST /api/query` con el contenido literal de `tests/fixtures/queries-proy.sql` → hoy `{"error":"Unsupported SQL command: --"}`; debe devolver las 5 sentencias |
| 2 | `frontend/src/panels/QueryPanel.tsx:132-138` / `App.tsx:35-47` | Si se prefiere no tocar el parser: dividir en el cliente por `;` + quitar líneas `--` antes de enviar (y mostrar el número de sentencias ejecutadas). | pegar el script → ejecutar → resultados de las 5 consultas |
| 3 | `query/query_executor.py:1593-1597` (`_project_rows`) | Cuando `columns == ("*",)` y `rows` está vacío, devolver las columnas del esquema (`table.schema.col_names()`) en vez de `[]`. El ejecutor ya tiene `table` en `_execute_select` (`:184`). | `SELECT * FROM alumnos WHERE id = 999` → hoy `columns: []`; debe devolver `['id','nombre','carrera_id','nota']` con 0 filas |
| 4 | `frontend/src/panels/ResultsPanel.tsx:37` | No usar `columns.length > 0` como "es lectura". Usar `result.statement === 'SELECT' \|\| 'EXPLAIN'` (o un flag `is_read` en `QueryResult`). | con el arreglo 3 o con este, la consulta #3 del profesor deja de decir **"La mutación se aplicó correctamente sobre el almacenamiento en disco."** |
| 5 | `query/query_executor.py:1709-1746` (`_validate_columns_for_select`) | Normalizar a minúsculas los nombres de columna al comparar (o normalizar en el parser), igual que `Catalog._normalize_identifier` hace con las tablas (`query/catalog.py:62-65`). | `SELECT ID, NOMBRE FROM ALUMNOS WHERE NOTA >= 14` → hoy `unknown column 'NOTA' in table 'alumnos'`; debe devolver 6 filas |
| 6 | `query/sql_parser.py:165` | `clean_sql = sql.strip().lstrip("\ufeff")`. | `"\ufeffSELECT * FROM alumnos"` → hoy `Unsupported SQL command: SELECT`; debe funcionar |
| 7 | `query/query_executor.py:254-257` | Soportar agregados sin `GROUP BY` con una única fila global (el ejecutor viejo ya lo hace con `key=lambda _r: 0`, `query/executor.py:504-507`); reutilizar ese camino. | `SELECT COUNT(*) FROM users` → hoy error; debe devolver 5 (o 12 con `alumnos`) |
| 8 | `query/csv_loader.py:49-66` + `:33-35` + `tools/import_csv.py:104` | Si `source` es `str`/`Path` (sin `\n`), **exigir que el fichero exista**; y `success = failed == 0 and rows_read > 0`. | `--file no_existe.csv` → hoy `insertadas: 0, exit=0`; debe fallar con "no se encontró el archivo" y `exit!=0` |
| 9 | `query/csv_loader.py:111-121` | Si el encabezado no coincide con el esquema, **abortar** (`failed = rows_read`, error "encabezado no reconocido: …") o exigir `has_header=False` explícito. Nunca mapear por posición en silencio. | `NOTA,NOMBRE,ID,CARRERA` + `15,Ana,1,2` → hoy guarda `{'id':15,'nombre':'Ana','carrera_id':1,'nota':2}` con `success:true` |
| 10 | `query/csv_loader.py:92` y `frontend/src/api.ts:37-47` + `backend/api.py:41-45` | Exponer y usar `encoding` (por defecto `utf-8-sig`, con detección/fallback `cp1252`) y hacer la subida `multipart/form-data` (o al menos `encoding` en el JSON). | CSV latin-1 desde el GUI → hoy `'Jos� N��ez'` con `success:true` |
| 11 | `storage/record.py:58` | Tratar `None` en INT/FLOAT (`NULL` real o error claro en español "la columna 'nota' es INT y no admite NULL"), en lugar de `int(None)` → `int() argument must be a string…`. | `INSERT INTO alumnos VALUES (54, 'X', 1, NULL)` |

### P1 — Credibilidad y cobertura SQL esperable

| # | Archivo:línea | Cambio propuesto | Prueba |
|---|---|---|---|
| 12 | `query/sql_parser.py:846-940` (`_parse_where`) | Paréntesis en `WHERE` (al menos un nivel) y `IN (…)`, `LIKE`, `IS [NOT] NULL`, `NOT`. Si no se implementan, mejorar el mensaje: hoy `Expected a comparison operator after 'name'` no dice "no soportado". | `WHERE (age >= 20)` / `WHERE dept IN ('CS')` / `WHERE name LIKE 'Ana%'` / `WHERE name IS NULL` |
| 13 | `query/sql_parser.py:392-410` (`_parse_insert`) | `INSERT INTO t (c1, c2) VALUES (…)` (mapear por nombre; el ejecutor nuevo ya construye el dict por `zip(columns, values)` en `:298-320`, basta con pasar los nombres). | `INSERT INTO users (id, name, age, dept) VALUES (98,'Yan',22,'CS')` |
| 14 | `query/sql_parser.py:809-818` + `query_executor.py:270-281` | `LIMIT n OFFSET m`. | `SELECT * FROM users ORDER BY age LIMIT 2 OFFSET 1` |
| 15 | `query/query_executor.py:470-495` (UPDATE) | Rechazar expresiones con un mensaje propio ("UPDATE sólo admite valores literales; usa dos sentencias") en vez de dejar escapar `invalid literal for int()…`. | `UPDATE users SET age = age + 1 WHERE id = 99` |
| 16 | `indexes/extendible_hash.py:96` (origen del `ValueError`) + `query/query_executor.py:301-305` (INSERT) | Traducir `duplicate hash key: 1` a "clave primaria duplicada: id=1 (ya existe una fila con ese valor)". El ejecutor conoce `table.schema.primary_key`, así que puede envolverlo con contexto de tabla/columna. | importar dos veces el mismo CSV |
| 17 | `query/sql_parser.py:622-681` (`_parse_create_index`) / `catalog.create_index` | `CREATE INDEX IF NOT EXISTS` idempotente también por **columna** (si la columna ya tiene índice del mismo tipo → OK, sin error). | `CREATE INDEX IF NOT EXISTS idx2 ON t (v)` cuando `v` ya tiene índice |
| 18 | `frontend/src/panels/QueryPanel.tsx:92-96` y `EXAMPLE_GROUPS` (15-153) | Añadir al hint y a los ejemplos: `CREATE INDEX … USING HASH\|BPLUS_CLUSTERED\|BPLUS_UNCLUSTERED`, `DROP INDEX`, `BEGIN/END TRANSACTION`, `USING SEQUENTIAL`, `IF [NOT] EXISTS`. — **YA CORREGIDO durante la revisión (12:29)**: el hint ya lista `CREATE INDEX / DROP INDEX / BEGIN TRANSACTION / END TRANSACTION / ROLLBACK` y hay un grupo de ejemplos "Transacciones". Falta añadir `USING SEQUENTIAL` y `IF [NOT] EXISTS`. | inspección del panel |
| 19 | `query/sql_parser.py:493-...`/`_parse_create_table` | Mensaje específico para `CREATE INDEX`/`CREATE VIEW`/`CREATE DATABASE` mal escritos, en vez de `Syntax error: se esperaba CREATE TABLE …`. | `CREATE VIEW v AS SELECT * FROM users` |
| 20 | `query/csv_loader.py:100-105` | Streaming (`csv.reader(open(...))`) e inserción por lotes; hoy carga todo en memoria y tarda > 2 min con 20 000 filas. | CSV de 20 000 filas |
| 21 | `storage/record.py:62` | Truncar por **caracteres** (o rechazar si excede) y no cortar una secuencia UTF-8; `VARCHAR(n)` debería contar caracteres. | `s VARCHAR(2)` con `'ñe'` → hoy `'ñ'`; `'😀'` → hoy `''` |

### P2 — Arquitectura y transacciones

| # | Archivo:línea | Cambio propuesto | Prueba |
|---|---|---|---|
| 22 | `query/executor.py:1-24, 337-345, 356-400, 405-410, 482-490` | Consolidar: migrar `examples/demo_parte1.py`, `tests/test_end_to_end.py`, `tests/test_storage_integration.py` a `query/query_executor.py` y reducir `query/executor.py` a shim o eliminarlo. Mientras exista: al menos **ignorar `LIMIT` ≠ ignorarlo en silencio** y `or_groups` con semántica AND no es aceptable. | tabla de §6 (`LIMIT 2` → 3 filas; `WHERE a OR b` → 0 filas) |
| 23 | `query/query_executor.py:729-737` + `backend/engine.py:101,231` | Permitir **varias transacciones concurrentes**: una sesión por conexión/request (`QueryExecutor` por sesión) o una pila de transacciones con id de sesión, y hacer que `engine.run` reciba un `session_id`. Sin esto, la demo obligatoria 2.1.4 no se puede hacer desde el GUI. | segundo `BEGIN` → hoy `ya hay una transacción activa (T7)` |
| 24 | `transactions/demo_concurrencia.py:20-40` | Reescribir la demo para que opere sobre tablas reales del motor (dos `QueryExecutor` sobre el mismo `Catalog`, dos hilos, `BEGIN/UPDATE/COMMIT`), de modo que la race condition y el bloqueo se vean sobre `HeapFile`, no sobre un `dict`. | hoy `tabla = {"X": 100}` (línea 21) |
| 25 | `transactions/lock_manager.py:19, 41-45, 61-65` | Añadir detección de interbloqueos (grafo de espera o "wound-wait") y reintentos con backoff; documentar que hoy el deadlock se resuelve por timeout de 2 s + rollback. | dos transacciones con locks cruzados |
| 26 | `README.md:44, 309, 488, 496` | Actualizar el README al estado real: 2.1.4 ya tiene BEGIN/END en SQL **pero es de una sola transacción activa**; agregar `CREATE INDEX`/`DROP INDEX`/`BEGIN`/`END` al subconjunto SQL de §9; y corregir el ❌ de agregados sin `GROUP BY` cuando se arregle (P0 #7). | — |
| 27 | `tests/test_benchmark_indexes.py:130` | La suite queda **roja** por este test (`assert False` en `test_all_expected_metrics_are_present`), sin relación con SQL. Dejarlo verde o marcarlo `xfail` con justificación: un profesor que corra `pytest` ve `1 failed`. | `python -m pytest -q` → `1 failed, 297 passed, 1 skipped` |

### Estado de la suite de pruebas en el momento del informe

```
$ python .review_tmp/run_tests_sql.py --tb=line -rf tests query/test_query_executor.py
1 failed, 297 passed, 1 skipped in 21.53s
FAILED tests/test_benchmark_indexes.py::test_all_expected_metrics_are_present
```

Los **3 fallos del SQL layer que encontré a las 12:10 ya están corregidos** por el actor concurrente (12:26):
`tests/test_sql_parser.py:68` y `tests/test_end_to_end.py:297-299` afirmaban que `UPDATE` debía lanzar `SQLParseError`
(hoy usan `SELECT * FROM` / `TRUNCATE TABLE users`, correcto). Revisión inicial de esas fallas, por si sirve de traza:

```
FALLA tests/test_sql_parser.py:69    Failed: DID NOT RAISE SQLParseError
FALLA tests/test_end_to_end.py::TestEndToEndHeap::test_sql_invalido_lanza_error_de_parseo
FALLA tests/test_end_to_end.py::TestEndToEndSecuencial::test_sql_invalido_lanza_error_de_parseo
      -> TypeError: sentencia no soportada: UpdateStatement  (query/executor.py:345)
```

---

## 8. Resumen ejecutivo en 6 líneas

1. **El flujo del profesor funciona hoy**: CREATE TABLE + CSV (12/12) + las 5 consultas, con los 6 resultados correctos, por motor, por CLI y por HTTP. Evidencia literal en §1.
2. Lo que **rompe** la demo: pegar el `.sql` del profesor falla por los comentarios `--` y por multi-sentencia (§1.1); `WHERE id = 999` se anuncia como "mutación aplicada" (§1.2); columnas en mayúsculas fallan aunque la tabla no (§3.2); `SELECT COUNT(*)` sin `GROUP BY` no existe (§3.2).
3. El **CSV es frágil**: fichero inexistente = éxito con 0 filas; encabezado distinto = corrupción silenciosa por mapeo posicional; latin-1 = mojibake; BOM, celdas vacías y VARCHAR se tratan en silencio (§4.2). **No hay `encoding` ni subida multipart** en el GUI/API.
4. **Índices: ahora sí hay `CREATE INDEX`/`DROP INDEX` desde SQL**, con `USING HASH|BPLUS_CLUSTERED|BPLUS_UNCLUSTERED`, persistencia en `catalog.json` y uso real por el planner (`BPLUS_CLUSTERED_RANGE_SCAN`). Esto es nuevo de hace ~10 minutos; el GUI todavía no lo anuncia (§3.1, §4.3).
5. **Transacciones: `BEGIN/END TRANSACTION` ya funcionan por el mismo camino del API/GUI**, con ROLLBACK real de datos y DDL. Pero **solo una transacción activa por proceso**, así que la demo multihilo obligatoria sigue viviendo en `transactions/demo_concurrencia.py` sobre un `dict`, desconectada del motor (§5.2, §5.3).
6. **Dos ejecutores con semánticas distintas** (`query/query_executor.py` vs `query/executor.py`): el viejo ignora `LIMIT`, devuelve 0 filas con `OR` y lanza `TypeError` con DDL/UPDATE/transacciones. Consolidar (§6).
