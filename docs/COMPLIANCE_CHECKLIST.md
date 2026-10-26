# Checklist de cumplimiento — Proyecto BD2

Este archivo concentra los requisitos que se decidieron cerrar antes de la entrega final.

## Parte 1 — Base de Datos Relacional

- [x] Heap File paginado.
- [x] RID estable `(page, slot)`.
- [x] Reutilización de slots eliminados.
- [x] Archivo Secuencial Paginado con main ordenado + overflow.
- [x] Eliminación lazy y reorganización automática.
- [x] B+ Tree base balanceado con hojas enlazadas.
- [x] B+ Tree no agrupado con `key -> RID`.
- [x] B+ Tree agrupado con **orden físico real** del Heap.
- [x] Máximo un índice clustered por tabla.
- [x] Reclustering tras INSERT/UPDATE que cambia la clave agrupada.
- [x] Reconstrucción de índices dependientes de RID después del reclustering.
- [x] Extendible Hashing con `global_depth`, `local_depth`, split y directorio.
- [x] Hash `UNIQUE` para la PK.
- [x] External Sort con runs + k-way merge.
- [x] External Hashing para `GROUP BY`.
- [x] External Hash Join para equi-join.
- [x] SQL CRUD + DDL + GROUP BY + ORDER BY + JOIN + LIMIT.
- [x] `CREATE INDEX`/`DROP INDEX` para Hash, B+ clustered y B+ unclustered.
- [x] Planner que cambia de scan a índice cuando corresponde.
- [x] `EXPLAIN` y `EXPLAIN ANALYZE`.
- [x] `BEGIN`, `COMMIT`/`END TRANSACTION`, `ROLLBACK`.
- [x] Demo de condición de carrera y corrección con locks.
- [x] Un único ejecutor oficial: `query/query_executor.py`.
- [x] Panel de archivos/tablas/índices.
- [x] Panel de consultas.
- [x] Panel de resultados.
- [x] Panel de plan de ejecución.
- [x] Área de índices secundarios ampliada para que nombre/técnica/acciones no salgan del recuadro.
- [x] Subtítulo “Parte 1 · …” eliminado del encabezado.
- [x] Benchmark Heap vs Secuencial para 1K/10K/100K en búsqueda y espacio.
- [x] Limitación de mutaciones a gran escala documentada sin afirmar mediciones inexistentes.
- [x] Benchmark de B+ clustered / B+ unclustered / Extendible Hash.

## Parte 2 — Base de Datos Espacial

- [x] R-Tree propio.
- [x] Split cuadrático.
- [x] Range Search con poda por MBR.
- [x] k-NN best-first con MINDIST.
- [x] Polígono con poda por MBR + point-in-polygon.
- [x] Haversine.
- [x] Euclidiana propagada correctamente de SQL/UI a la ejecución.
- [x] Validación R-Tree vs fuerza bruta.
- [x] Persistencia/restauración del R-Tree después de reiniciar el motor.
- [x] Coherencia del R-Tree ante INSERT/UPDATE/DELETE.
- [x] `CREATE INDEX ... ON tabla (lat, lon) USING RTREE`.
- [x] `distancia(lat, POINT(...))`.
- [x] Alias del enunciado `distancia(ubicacion, POINT(...))`.
- [x] Punto nombrado de sesión: `SET mi_ubicacion = POINT(...)`.
- [x] `ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT k`.
- [x] Panel espacial solo lista tablas con columnas/índice espacial.
- [x] Modos UI: rango, k-NN y polígono.
- [x] Selector Haversine/Euclidiana.
- [x] Leaflet + OpenStreetMap con zoom, pan y click-to-query.
- [x] Resultados resaltados sobre el mapa.
- [x] Benchmark Secuencial vs R-Tree vs PostgreSQL/PostGIS GiST.
- [x] Matriz 1K/10K/100K, 100 consultas, radios 1/5/10 km y k=10/50/100.
- [x] Tiempo de construcción documentado.
- [x] Tiempo de consulta documentado.
- [x] Métrica de tamaño R-Tree corregida: `deep_size()` recursivo en lugar de `nodes*64`.
- [x] Diferencia metodológica memoria Python vs `pg_relation_size` documentada.
- [x] Informe corregido: GiST descrito como `geometry(Point,4326)` 2D.
- [x] Informe corregido: comparaciones 10K→100K usan tamaños consistentes.
- [x] Tablas numéricas del informe referencian una corrida/CSV explícita.

## Entregables

- [x] README único y coherente con el estado actual.
- [x] Informe incremental no vacío.
- [x] Documento técnico Parte 2.
- [x] Checklist de cumplimiento.
- [x] Demos Parte 1 y Parte 2.
- [x] Suite de tests de cumplimiento.
- [ ] Video de 5–10 minutos: debe grabarlo el equipo con la versión final.
- [ ] Presentación final: debe prepararla el equipo con los resultados definitivos del host de entrega.
