# Informe incremental — Minigestor de Base de Datos Multimodal

## 1. Alcance

El proyecto implementa dos incrementos evaluables: una base relacional educativa (almacenamiento, índices, SQL, operadores externos y transacciones) y una extensión espacial basada en R-Tree.

## 2. Incremento 1: almacenamiento e índices

### 2.1 Almacenamiento

Se implementaron dos organizaciones físicas:

- **Heap File paginado**: inserción en orden de llegada, RID `(page,slot)`, tombstone y reutilización de espacio libre.
- **Archivo Secuencial Paginado**: `main` físicamente ordenado por PK, área `aux` de overflow y reorganización periódica.

### 2.2 Índices

- **Extendible Hashing** para igualdad exacta, con profundidad global/local y split de buckets.
- **B+ no agrupado** con entradas `key -> RID` y heap fetch posterior.
- **B+ agrupado** con máximo uno por tabla. Crear el índice reorganiza físicamente el Heap por la clave; las mutaciones que afectan ese orden provocan reclustering y reconstrucción de índices dependientes de RID.

### 2.3 Operadores externos

- External Sort: generación de runs y k-way merge.
- External Hashing: GROUP BY y equi-join.

### 2.4 SQL y transacciones

El ejecutor oficial es `query/query_executor.py`. Se retiró la ruta legacy para evitar dos semánticas distintas. El motor soporta CRUD, DDL, filtros, rango, OR, GROUP BY, ORDER BY, JOIN, LIMIT, EXPLAIN/ANALYZE y transacciones con rollback por snapshot educativo y locks exclusivos.

### 2.5 Limitación experimental Parte 1

La matriz funcional llega a **100 000 registros** para búsqueda y espacio. En la corrida histórica del equipo, las operaciones mutacionales uno-a-uno a máxima escala no se midieron de forma completa porque el costo de E/S del host hacía la ejecución impráctica. Por tanto, el informe **no afirma** que inserción/eliminación individual hayan sido medidas a 100 000 cuando no existe esa medición. Las corridas futuras pueden aumentar el límite si el host lo permite.

## 3. Incremento 2: base espacial

### 3.1 R-Tree

El índice espacial utiliza MBR, split cuadrático y nodos con ocupación mínima. Range Search poda subárboles cuyo MBR no intersecta la región candidata; k-NN usa una cola best-first ordenada por MINDIST. El polígono usa MBR para candidatos y ray casting para validación exacta.

### 3.2 Métricas

- **Haversine**: distancia geodésica en metros para lat/lon.
- **Euclidiana**: distancia plana en grados para ejercicios y comparaciones controladas.

La métrica seleccionada se propaga desde SQL/UI hasta `SpatialIndex.range_search()` y `SpatialIndex.knn()`.

### 3.3 SQL espacial

Se soportan tanto los nombres físicos como la notación del enunciado:

```sql
CREATE INDEX idx_geo ON tiendas (lat, lon) USING RTREE;

SELECT * FROM tiendas
WHERE distancia(ubicacion, POINT(-12.0464,-77.0428), HAVERSINE) < 5000;

SET mi_ubicacion = POINT(-12.0464,-77.0428);
SELECT * FROM tiendas
ORDER BY distancia(ubicacion, mi_ubicacion, HAVERSINE)
LIMIT 10;
```

`ubicacion` resuelve el único R-Tree de la tabla y `SET` define un punto nombrado para la sesión.

## 4. Interfaz

La UI contiene panel de archivos/índices, consultas, resultados, plan y un mapa **Leaflet + OpenStreetMap**. El mapa permite zoom, pan, click para fijar el centro, rango, k-NN y polígono, además de resaltado de resultados.

El encabezado se simplificó a “Minigestor de Base de Datos Multimodal” y el panel izquierdo se amplió para evitar overflow visual de la tabla de índices secundarios.

## 5. Resultados espaciales — corrida definitiva documentada

Las siguientes cifras provienen de `benchmark_results/spatial_benchmark.csv` de la corrida PostGIS registrada en el repositorio original. Se usan esos números de forma consistente para evitar mezclar corridas.

### 5.1 Rango de 1 km — promedio por consulta

| N | Secuencial (ms) | R-Tree (ms) | PostGIS GiST (ms) |
|---:|---:|---:|---:|
| 1 000 | 1.763 | 0.122 | 0.575 |
| 10 000 | 18.044 | 0.631 | 0.507 |
| 100 000 | 179.433 | 4.047 | 1.028 |

Para 1 000 puntos, la relación PostGIS/R-Tree es aproximadamente `0.575 / 0.122 = 4.71×`; por ello el R-Tree propio fue ~4.7× más rápido en esa consulta concreta. Esta relación **no** se generaliza a todas las escalas: a 10K y 100K PostGIS es más rápido para ese radio.

### 5.2 k-NN, k=10 — promedio por consulta

| N | Secuencial (ms) | R-Tree (ms) | PostGIS GiST (ms) |
|---:|---:|---:|---:|
| 1 000 | 1.795 | 0.992 | 0.641 |
| 10 000 | 21.513 | 4.230 | 0.713 |
| 100 000 | 216.119 | 19.090 | 0.758 |

### 5.3 Tiempo de construcción

| N | R-Tree (ms) | PostGIS GiST (ms) |
|---:|---:|---:|
| 1 000 | 5.580 | 114.559 |
| 10 000 | 73.875 | 238.387 |
| 100 000 | 1 024.034 | 2 659.405 |

### 5.4 Escalabilidad correcta

Entre **10 000 y 100 000** puntos, rango 1 km:

- R-Tree: `0.631 → 4.047 ms`.
- PostGIS: `0.507 → 1.028 ms`.

No se mezclan cifras de 1K con 10K en la misma comparación de crecimiento.

### 5.5 Espacio/memoria

El CSV histórico calculaba el R-Tree como `nodes * 64`, que producía 426 816 bytes a 100K y no representaba toda la estructura. Esa cifra se considera **obsoleta para comparación de memoria**.

El benchmark corregido usa `deep_size()` recursivo. Una validación local del código corregido con 100 000 puntos obtuvo aproximadamente **94 180 755 bytes (~89.8 MiB)** para el objeto R-Tree Python completo. PostgreSQL reportó históricamente **26 468 352 bytes (~25.2 MiB)** para el índice GiST mediante `pg_relation_size`.

Estas magnitudes se presentan separadas porque miden representaciones distintas:

- R-Tree propio: memoria profunda de objetos Python.
- GiST: tamaño físico del índice PostgreSQL en disco.

No se afirma que sean métricas perfectamente equivalentes; el objetivo es evitar una comparación engañosa.

## 6. PostgreSQL/PostGIS

El baseline utiliza `geometry(Point,4326)` con índice **GiST 2D**. Las consultas de radio usan `ST_DWithin` (con conversión a geography para metros cuando corresponde) y k-NN usa `<->` sobre la geometría. No se describe el índice como “3D sobre la esfera”.

## 7. Validación

La suite de cumplimiento verifica:

- almacenamiento y reorganización;
- B+ clustered físico y unicidad de un clustered por tabla;
- B+ unclustered y Hash;
- SQL/planner/transacciones;
- R-Tree vs fuerza bruta;
- Haversine y Euclidiana;
- persistencia espacial;
- DML con R-Tree;
- `ubicacion` y punto nombrado `mi_ubicacion`.

## 8. Conclusión

El proyecto cubre los requisitos funcionales de las dos partes implementadas y explicita las limitaciones experimentales que dependen del host. Los resultados numéricos se vinculan a una corrida concreta en lugar de mezclar mediciones de distintas ejecuciones.
