# Minigestor de Base de Datos Multimodal — Proyecto BD2

Implementación educativa de un minigestor que integra almacenamiento paginado, índices, operadores externos, SQL, transacciones/concurrencia y consultas espaciales.

## Estado de cumplimiento

### Parte 1 — Base de Datos Relacional

- Heap File paginado con RID `(page, slot)`, eliminación lógica y reutilización de espacios libres.
- Archivo Secuencial Paginado con archivo principal ordenado, overflow, búsqueda por PK, range search y reorganización automática al superar el umbral configurado.
- B+ Tree agrupado **real**: como máximo uno por tabla y el Heap se reorganiza físicamente por la clave agrupada; INSERT/UPDATE reconstruyen los RID afectados mediante reclustering.
- B+ Tree no agrupado: hojas `key -> RID`, búsquedas exactas y por rango.
- Hash Extensible: profundidad global/local, split de buckets, duplicación/reducción de directorio, igualdad exacta y unicidad opcional.
- External Sort con generación de runs y k-way merge.
- External Hashing para `GROUP BY` y equi-`JOIN`.
- SQL: `CREATE/DROP TABLE`, `CREATE/DROP INDEX`, `SELECT`, `WHERE`, `BETWEEN`, `AND/OR`, `INSERT`, `UPDATE`, `DELETE`, `GROUP BY`, `ORDER BY`, `LIMIT`, `JOIN`, `EXPLAIN`, `EXPLAIN ANALYZE`.
- Transacciones: `BEGIN TRANSACTION`, `END TRANSACTION`/`COMMIT`, `ROLLBACK`; locks exclusivos y demo de condición de carrera.
- UI con panel de archivos/tablas/índices, consultas, resultados y plan de ejecución.

### Parte 2 — Base de Datos Espacial

- R-Tree propio con split cuadrático, MBR, validación estructural y carga masiva.
- Range Search con poda por MBR + verificación exacta.
- k-NN best-first con `MINDIST`.
- Intersección/punto-en-polígono con poda por MBR.
- Distancia Haversine y Euclidiana, propagadas end-to-end desde SQL/UI hasta el índice.
- SQL espacial compatible con dos estilos:

```sql
SELECT * FROM tiendas
WHERE distancia(lat, POINT(-12.0464, -77.0428), HAVERSINE) < 5000;

SELECT * FROM tiendas
WHERE distancia(ubicacion, POINT(-12.0464, -77.0428), HAVERSINE) < 5000;

SET mi_ubicacion = POINT(-12.0464, -77.0428);
SELECT * FROM tiendas
ORDER BY distancia(ubicacion, mi_ubicacion, HAVERSINE)
LIMIT 10;
```

`ubicacion` es el alias lógico del único R-Tree `(lat, lon)` de la tabla. `SET nombre = POINT(lat, lon)` define un punto nombrado para la sesión.

- Persistencia/restauración del R-Tree tras reinicio del motor.
- Mapa interactivo con **Leaflet + OpenStreetMap**, zoom, pan, clic para fijar centro, rango, k-NN, polígono y resaltado de resultados.
- Benchmark Secuencial vs R-Tree propio vs PostgreSQL/PostGIS GiST.

## Arquitectura

```text
React/Vite
   │ /api
FastAPI
   │
QueryExecutor  ← único ejecutor oficial
   ├── SQLParser
   ├── QueryPlanner
   ├── Catalog
   ├── External Sort / External Hashing
   ├── Heap File / Sequential File
   ├── B+ clustered / B+ unclustered / Extendible Hash
   └── SpatialExecutor / R-Tree
```

`query/query_executor.py` es el único ejecutor vigente. El antiguo `query/executor.py` fue retirado para evitar rutas semánticas duplicadas.

## Instalación

Recomendado: Python 3.12 o 3.13 nativo de Windows.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Frontend:

```powershell
cd frontend
npm install
```

## Ejecución

Terminal 1, desde la raíz:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.api:app --reload --port 8000
```

Terminal 2:

```powershell
cd frontend
npm run dev
```

- UI: `http://localhost:5173`
- Swagger: `http://127.0.0.1:8000/docs`

Leaflet y los tiles de OpenStreetMap se cargan desde CDN, por lo que el mapa base requiere acceso a Internet; el motor espacial y las consultas no dependen de Internet.

## Pruebas

```powershell
python -m pytest -q
```

La suite de cumplimiento añadida valida almacenamiento, índices, reclustering físico, SQL/planner, transacciones, R-Tree, Euclidiana/Haversine, persistencia espacial y sintaxis `ubicacion`/`mi_ubicacion`.

## Benchmarks

Índices:

```powershell
python -m benchmarks.benchmark_indexes --sizes 1000 10000 100000
```

Almacenamiento:

```powershell
python -m benchmarks.benchmark_heap_vs_sequential --sizes 1000 10000 100000
```

Espacial sin PostgreSQL:

```powershell
python -m benchmarks.benchmark_spatial --sizes 1000 10000 100000 --queries 100
```

Con PostGIS real:

```powershell
python -m benchmarks.benchmark_spatial --sizes 1000 10000 100000 --queries 100 --pg-dsn "host=127.0.0.1 port=5432 dbname=postgres user=postgres password=postgres"
```

PostgreSQL debe tener PostGIS disponible:

```sql
CREATE EXTENSION IF NOT EXISTS postgis;
```

### Búsqueda textual y vectorial (Partes 3 y 4)

El corpus de los experimentos se genera en local con semilla fija. No requiere
descargas, no se versiona y dos corridas producen el mismo archivo.

```powershell
python -m benchmarks.text_corpus --sizes 1000 10000 100000
```

Escribe `data/text/<tamano>/corpus.jsonl` y `queries.json`, este ultimo con los
documentos que responden a cada consulta.

Motor propio:

```powershell
python -m benchmarks.benchmark_text_motor --sizes 1000 10000 100000
python -m benchmarks.benchmark_vector_ivf_hnsw --sizes 1000 10000
python -m benchmarks.benchmark_vector_ivf_hnsw --sizes 100000 --metricas euclidean
```

Baseline GIN de PostgreSQL (opcional). La base indicada en el DSN debe existir;
el script crea y reemplaza sus propias tablas:

```powershell
python -m benchmarks.benchmark_text_gin --pg-dsn "host=localhost port=5432 user=postgres password=postgres dbname=bd2_experimentos"
```

Los resultados quedan en `benchmark_results/text` y `benchmark_results/vector`,
con un CSV y un JSON por experimento. Las figuras se regeneran con:

```powershell
python -m benchmarks.generate_text_charts
python -m benchmarks.generate_vector_charts
```

Nota de datos: el corpus y los vectores son sinteticos, con semilla fija. La
relevancia esta definida por construccion, no por juicio humano. Esa decision
se justifica en `docs/borrador_informe_parte3_4.md` y no se presenta como una
medicion sobre datos reales.

### Nota metodológica de Parte 1

El dataset llega a 100 000 registros para búsqueda y espacio. En la corrida histórica usada por el equipo, las mutaciones uno-a-uno (inserción/eliminación/reorganización) se limitaron a una escala menor por el costo de E/S del host; esto se declara como limitación y no se presenta como una medición a 100 000 cuando no lo fue.

### Nota metodológica de espacio espacial

El benchmark actualizado usa `deep_size()` para estimar recursivamente la memoria ocupada por todo el objeto R-Tree de Python, en vez de `nodes * 64`. Esta cifra es memoria del proceso Python y **no es directamente equivalente** a `pg_relation_size()` de PostgreSQL; ambas se muestran con su metodología explícita.

## Documentación

- `docs/COMPLIANCE_CHECKLIST.md`: checklist contra el enunciado.
- `docs/informe_incremental.md`: informe incremental completo y limitaciones.
- `docs/parte2_espacial.md`: diseño, SQL y resultados espaciales sincronizados con la corrida definitiva documentada.

## Persistencia física de índices — corrección de rúbrica

Esta versión ya no reconstruye B+, Hash y R-Tree desde cero cada vez que se abre el catálogo.
Cada índice dispone de un archivo propio en `backend/data/indexes/` (o `<data_dir>/indexes/`
en tests/tablas dinámicas), se sincroniza tras mutaciones y se recarga directamente al reiniciar.

Prueba específica:

```bash
python -m pytest tests/test_index_persistence.py -q
python -m examples.demo_persistencia_indices
```

La prueba de reinicio bloquea intencionalmente `HeapFile.scan()`: si el motor tratara de
reconstruir los índices desde la tabla base, fallaría.
