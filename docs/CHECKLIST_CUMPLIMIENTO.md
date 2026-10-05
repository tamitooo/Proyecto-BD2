# Checklist de cumplimiento — Partes 1 y 2

Cada requisito del enunciado (`Proyecto_Integrador_BD2.docx`) con su evidencia en el
repositorio. ✅ = implementado y cubierto por pruebas o por benchmark.

## Parte 1 · Base de datos relacional

| § | Requisito | Estado | Evidencia |
|---|---|---|---|
| 2.1.1 | Heap File con reutilización de espacio libre | ✅ | `storage/heap_file.py` (free-list `.free`), `tests/test_heap_file.py` |
| 2.1.1 | Archivo Secuencial: inserción ordenada, borrado lazy, reorganización al 30 % | ✅ | `storage/sequential_file.py`, `tests/test_sequential_file.py` |
| 2.1.2 | B+ agrupado (uno por tabla) | ✅ | `indexes/clustered_bplus.py`, regla en `query/catalog.py`, `tests/test_storage_integration.py` |
| 2.1.2 | B+ no agrupado | ✅ | `indexes/unclustered_bplus.py` |
| 2.1.2 | Hash dinámico (Extendible Hashing) | ✅ | `indexes/extendible_hash.py` |
| 2.1.2 | ORDER BY con External Sort (k-way merge) | ✅ | `operators/external_sort.py`, `tests/test_end_to_end.py` (runs en disco) |
| 2.1.2 | GROUP BY y JOIN con External Hashing | ✅ | `operators/external_hashing.py` |
| 2.1.3 | SELECT/WHERE, ORDER BY, GROUP BY, INSERT, DELETE | ✅ | `query/sql_parser.py`, `query/query_executor.py` (ejecutor único) |
| 2.1.4 | BEGIN/END TRANSACTION, locks, demo con hilos y race condition | ✅ | `transactions/`, `tests/test_transactions.py`, `python -m transactions.demo_concurrencia` |
| 2.1.5 | 4 paneles: archivos, consultas, resultados, plan | ✅ | `frontend/src/panels/` (índices secundarios en tarjetas que no se desbordan) |
| 2.1.6 | Heap vs Secuencial: inserción, búsqueda por PK, espacio, reorganización (1K/10K/100K) | ✅ | `benchmarks/benchmark_heap_vs_sequential.py`, tablas autogeneradas |
| 2.1.6 | B+ agrupado vs no agrupado vs Hash: construcción, consulta, espacio, mutaciones | ✅ | `benchmarks/benchmark_indexes.py`, con línea base sin índice |
| 2.1.6 | Gráficas, tabla de ventajas/desventajas y conclusiones | ✅ | `benchmark_results/plots/`, `docs/comparacion_ventajas_desventajas.md`, `docs/informe_incremental.md` |

## Parte 2 · Base de datos espacial

| § | Requisito | Estado | Evidencia |
|---|---|---|---|
| 2.2.1 | R-Tree para puntos 2D (lat, lon) | ✅ | `indexes/rtree.py` (split cuadrático, `validate()`) |
| 2.2.1 | Consulta por rango | ✅ | `RTREE_RANGE_SCAN`, verificado contra fuerza bruta |
| 2.2.1 | k-NN | ✅ | `RTREE_KNN` best-first con MINDIST |
| 2.2.1 | Intersección con polígonos | ✅ | `RTREE_POLYGON` |
| 2.2.1 | Euclidiana y Haversine | ✅ | Ambas en SQL, en el R-Tree y en el mapa (`tests/test_cumplimiento.py`) |
| 2.2.2 | Mapa interactivo (Leaflet…) con resultados resaltados | ✅ | `MapPanel.tsx`: Leaflet + OpenStreetMap, zoom, pan, clic, polígono |
| 2.2.3 | `distancia(ubicacion, POINT(...)) < 5000` tal cual | ✅ | Alias `ubicacion` → par (lat, lon) del R-Tree |
| 2.2.3 | `ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT 10` tal cual | ✅ | Variable de sesión: `SET` o clic en el mapa |
| 2.2.4 | Secuencial vs R-Tree vs GiST de PostgreSQL | ✅ | `benchmarks/benchmark_spatial.py --pg-mode postgis` |
| 2.2.4 | Rango 1/5/10 km, k-NN 10/50/100, 1K/10K/100K, promedio de 100 consultas | ✅ | `benchmark_results/spatial_benchmark.csv` |
| 2.2.4 | Construcción, consulta y memoria/espacio | ✅ | R-Tree serializado vs `pg_relation_size`, más memoria Python (`tracemalloc`) |
| 2.2.4 | Gráficas y tabla de cuándo usar cada técnica | ✅ | `spatial_*.png`, `docs/parte2_espacial.md` §5.2 |

## Entregables

| Entregable | Estado | Evidencia |
|---|---|---|
| Código en Git | ✅ | Este repositorio |
| README (arquitectura, organización, instalación) | ✅ | `README.md` |
| Informe incremental | ✅ | `docs/informe_incremental.md` |
| Video demo y presentación | Pendiente del equipo | Guion en `docs/guia_issues_y_entregables.md` |

## Correcciones de la revisión final

| Hallazgo | Corrección |
|---|---|
| `informe_incremental.md` vacío; README contradictorio | Informe escrito; README actualizado (Partes 1 y 2 completas) |
| Tablas del informe de otra corrida distinta al CSV | Todas las tablas se generan desde el CSV (`generate_report_tables.py`, con `--check`) |
| SQL del enunciado (`ubicacion`, `mi_ubicacion`) no funcionaba | Alias espacial + variables de sesión (`SET`, `variables` en el API, clic en el mapa) |
| Mapa SVG propio sin Leaflet | Leaflet + OpenStreetMap |
| Faltaban construcción y espacio; espacio del R-Tree imposible (`nodos × 64`) | R-Tree serializado (≈ 43 B/punto) y memoria Python; GiST medido sólo como índice (antes contaba la tabla y el índice dos veces) |
| §5.4 mezclaba tamaños; "GiST 3D sobre la esfera" | Comparación con el mismo par de tamaños; GiST 2D sobre `geometry(Point, 4326)` |
| Dos ejecutores (legado) | `query/executor.py` eliminado; demo y pruebas migradas al oficial |
| Recuadro de índices secundarios desbordado; subtítulo "Parte 1" | Tarjetas adaptables; subtítulo eliminado |
| *Bugs encontrados al revisar:* k-NN sin índice ordenaba por latitud; Euclidiana ignorada en el R-Tree; el R-Tree no se actualizaba con INSERT/UPDATE/DELETE ni se restauraba al reiniciar; JOIN con columnas de la tabla unida fallaba; radio Euclidiano del mapa en metros leído como grados; CSV pegado fallaba en Linux/macOS | Todos corregidos y cubiertos por `tests/test_cumplimiento.py` |
