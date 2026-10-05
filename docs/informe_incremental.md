# Informe incremental — Minigestor de Base de Datos Multimodal

**Curso:** Base de Datos 2 · UTEC · Ciclo 2026-2
**Entrega:** parcial (semana 8) — Partes 1 y 2
**Repositorio:** https://github.com/tamitooo/Proyecto-BD2

> Las tablas numéricas de este informe se **generan desde los CSV** de
> `benchmark_results/` con `python -m benchmarks.generate_report_tables`. Si se repite
> una corrida, basta con volver a ejecutar ese comando y el informe, el README y los
> CSV quedan sincronizados.

---

## 1. Diseño arquitectónico

El motor está escrito desde cero en Python, usando sólo la librería estándar. Las
dependencias externas son únicamente para las pruebas, las gráficas, el puente HTTP y,
de forma opcional, la comparación contra PostgreSQL. Está organizado en capas:

```
Frontend React + Vite + Leaflet  ──HTTP/JSON──►  API FastAPI (backend/api.py)
                                                        │
                                   backend/engine.py → Catalog + QueryExecutor
                                                        │
  query/sql_parser.py → query/query_planner.py → query/query_executor.py  (ejecutor único)
        │                       │                          │
        │      indexes/ (B+ agrupado, B+ no agrupado, Hash Extendible, R-Tree)
        │      operators/ (External Sort, External Hashing)
        │      spatial/ (Haversine, Euclidiana, polígonos, SpatialIndex)
        └────► storage/ (Heap File, Archivo Secuencial)   transactions/ (locks 2PL)
```

**Decisiones principales**

* **Un único ejecutor** (`query/query_executor.py`). Lo usan el API, la interfaz, las
  demos y todas las pruebas. El ejecutor anterior (`query/executor.py`) se eliminó
  para que no existan dos semánticas distintas.
* **Contrato de respuesta estable** (`QueryResult`). Devuelve filas, columnas, plan
  lógico, traza real con tiempos y errores legibles. El frontend nunca ve RIDs ni
  páginas.
* **Planner basado en reglas y explicable.** Cada paso lleva `reason` y `details`,
  que se muestran en el panel de plan de ejecución.
* **Índices reconstruibles.** El catálogo persiste la definición de tablas e índices
  (incluido el R-Tree, con su par lat/lon) y los reconstruye al arrancar.
* **Reorganización del secuencial.** Reescribe `.main`, cambia todos los RID y obliga
  a reconstruir los índices. El ejecutor lo detecta comparando el contador de
  reorganizaciones.

## 2. Dominio de datos

* **Demo relacional** (`backend/engine.py`):
  * `users` sobre Heap File, con Hash Extendible en la PK.
  * `employees` sobre Archivo Secuencial, con B+ agrupado en `salary` y B+ no agrupado
    en `dept`.
  * `departments` sobre Heap File.
* **Datos de la cátedra:** `tests/fixtures/alumnos_prueba_bd2.csv` con el script
  `queries-proy.sql`, que corre de punta a punta (`tests/test_profesor_script.py`).
* **Demo espacial:** tiendas o restaurantes con `lat`/`lon` alrededor de Lima,
  generados con semilla fija y focos de densidad (`spatial/geo.py`). Se cargan por CSV
  desde el panel de archivos.
* **Tipos:** `INT`, `FLOAT` y `VARCHAR(n)`, en registros binarios de tamaño fijo con
  `struct`. Un punto espacial se modela como dos columnas `FLOAT`. En SQL se nombra
  `ubicacion`.

## 3. Algoritmos — Parte 1

### 3.1 Almacenamiento
* **Heap File:** páginas de tamaño fijo y slots con *tombstone*. Una *free-list*
  persistida (`.free`) permite reutilizar los huecos.
* **Archivo Secuencial Paginado:** `.main` ordenado por PK y área `.aux` de
  desbordamiento. El borrado es *lazy* y la reorganización se dispara al superar el
  **30 %** de espacio desperdiciado. La búsqueda es binaria sobre `.main` más un
  recorrido de `.aux`.

### 3.2 Índices
* **B+ Tree base:** orden configurable, split y merge con redistribución y hojas
  enlazadas para recorrer rangos sin volver a descender.
* **B+ agrupado:** las hojas guardan el **registro completo**. Es la caracterización
  de clase del índice agrupado ("índice en árbol = tabla", estilo InnoDB). Se admite
  **uno por tabla** y el planner lo usa para evitar el External Sort.
* **B+ no agrupado:** hojas `(clave, RID)` con *heap fetch* posterior.
* **Hash Extendible:** directorio con profundidad global y local, split incremental
  de *buckets* e igualdad en `O(1)` promedio. Es el índice único de cada PK.

### 3.3 Algoritmos externos
* **External Sort:** *runs* que caben en memoria y **k-way merge** con un *heap*. Se
  usa en `ORDER BY` cuando ningún índice cubre el orden, incluido
  `ORDER BY distancia(...)` sin R-Tree.
* **External Hashing:** particionado en disco por hash para **GROUP BY** y
  **equi-JOIN** con memoria acotada.

### 3.4 SQL, planner y transacciones
* El parser cubre `SELECT` (proyección, `WHERE` con `AND`/`OR`/`BETWEEN`, `GROUP BY`,
  `ORDER BY`, `LIMIT`, `JOIN`), `INSERT`, `UPDATE`, `DELETE`, `CREATE/DROP TABLE`,
  `CREATE/DROP INDEX`, `EXPLAIN [ANALYZE]`, `BEGIN`/`END TRANSACTION`/`COMMIT`/
  `ROLLBACK` y `SET`.
* El planner compara candidatos: Hash para igualdad; B+ para igualdad, rango y orden;
  unión de índices con `OR`; y escaneo como respaldo.
* **Transacciones:** bloqueo exclusivo por tabla en la primera escritura (2PL
  estricto) y `ROLLBACK` que restaura filas, índices y el DDL de la transacción.
  `transactions/demo_concurrencia.py` reproduce con hilos una *actualización perdida*
  y muestra cómo los locks la evitan.

## 4. Algoritmos — Parte 2

* **R-Tree** (`indexes/rtree.py`):
  * Hojas `(MBR, RID)` y nodos internos `(MBR, hijo)`, con `m = ⌈M/2⌉`.
  * `ChooseLeaf` elige por menor ampliación de área.
  * **Split cuadrático** (`PickSeeds`/`PickNext`, como en clase).
  * Carga masiva empaquetada para construir 100 000 puntos.
  * `validate()` comprueba las invariantes.
* **Rango:** caja del círculo, poda por MBR y verificación exacta con la métrica.
* **k-NN best-first:** min-heap por **MINDIST** con poda global. La distancia real
  sólo se calcula en las hojas visitadas.
* **Polígono:** poda por el MBR del polígono y **ray casting** punto-en-polígono.
* **Métricas:** **Haversine** (metros) y **Euclidiana** (grados).
  * Con Haversine, el árbol se construye en una proyección local en metros.
  * Si la consulta usa otra métrica, la caja y la cota MINDIST se convierten de unidad.
  * El resultado se verifica siempre con la distancia exacta.
* **Mantenimiento:** INSERT, UPDATE y DELETE actualizan el R-Tree, que además se
  restaura al reiniciar.
* **SQL espacial:** `distancia(ubicacion, POINT(...)) < r`,
  `ORDER BY distancia(ubicacion, mi_ubicacion) LIMIT k`, `dentro_de(ubicacion,
  POLYGON(...))` y `SET mi_ubicacion = POINT(...)`. Detalle en
  [`parte2_espacial.md`](parte2_espacial.md) §4.
* **Mapa:**
  * Leaflet + OpenStreetMap, con zoom y pan.
  * Clic para fijar `mi_ubicacion`.
  * Modos rango, k-NN y polígono.
  * Resultados resaltados en el mapa.

## 5. Parte experimental — Parte 1

**Metodología.** Semilla fija 42 y datasets de 1 000, 10 000 y 100 000 registros. La
búsqueda por PK se promedia sobre consultas aleatorias con *hit* y con *miss*. El
espacio es el tamaño real de los archivos en disco y la reorganización se mide al
superar el umbral del 30 %.

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

**Lectura.**
* **Búsqueda por PK:** el Archivo Secuencial gana por varios órdenes de magnitud a
  100 000 registros. Hace una búsqueda binaria `O(log N)` frente al recorrido `O(N)`
  del Heap.
* **Inserción:** ambos pagan una escritura por registro. El Secuencial añade el costo
  de ordenar y reorganizar.
* **Borrado:** el Heap gana gracias al *tombstone* y la *free-list*.
* **Espacio:** el Heap sólo desperdicia la última página. El Secuencial es exacto tras
  reorganizar y llega hasta un 30 % de *tombstones* entre reorganizaciones.

**Cuándo usar cada uno:**
* **Heap File:** cargas con muchas escrituras y borrados, y lecturas por índice.
* **Archivo Secuencial:** lecturas por clave y por rango sobre la PK, con pocas
  modificaciones.

**Índices.** Sobre las mismas claves se midieron:
* tiempo de construcción;
* igualdad exacta (sólo el índice y también trayendo la fila);
* rango trayendo la fila;
* recorrido ordenado;
* inserciones y borrados frecuentes;
* espacio adicional;
* una **línea base sin índice** (búsqueda lineal) para cuantificar la mejora.

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

**Lectura.**
* **Hash Extendible:** es el más rápido en igualdad y el más barato de construir,
  pero no soporta rangos ni orden.
* **B+ agrupado:** gana el rango **trayendo la fila**, porque el registro ya está en
  su hoja. A cambio ocupa más espacio, porque guarda los registros completos.
* **B+ no agrupado:** es el más compacto de los B+ y sirve para igualdad y rango sobre
  columnas secundarias. Paga una lectura por RID.

### 5.1 Limitaciones declaradas
* Los tiempos absolutos dependen del host. La corrida original del equipo en Windows
  tenía ~15 ms por escritura (E/S interceptada por el sistema). Por eso las
  conclusiones se apoyan en las **diferencias relativas** y en la complejidad.
* **Límite de las mutaciones.** En la corrida publicada, la inserción y el borrado uno
  a uno del comparativo Heap vs Secuencial se midieron hasta **10 000** registros. El
  comparativo de índices se midió hasta **50 000** claves. A 100 000 registros, el
  costo de E/S del entorno de ejecución (~15 ms por escritura) hacía impracticable
  medir 100 000 operaciones individuales. Las mediciones de **búsqueda, espacio y
  carga masiva** sí llegan a **100 000** registros. El CSV marca lo no medido con
  `supported=False` y las tablas lo muestran como "—": el informe **no afirma**
  mediciones que no existen.
* **Cómo completar la matriz a 100 000** en un equipo con E/S rápida:
  `python benchmarks/benchmark_heap_vs_sequential.py --sizes 1000 10000 100000 --mutation-limit 100000`
  y `python -m benchmarks.benchmark_indexes --sizes 1000 10000 100000`, seguidos de
  `python -m benchmarks.generate_charts` y `python -m benchmarks.generate_report_tables`.
  Las tablas del informe y del README se actualizan solas.

## 6. Parte experimental — Parte 2

Secuencial vs **R-Tree propio** vs **GiST de PostgreSQL con PostGIS**:
* rango de 1, 5 y 10 km;
* k-NN con k = 10, 50 y 100;
* 1 000, 10 000 y 100 000 puntos;
* promedio de 100 consultas por medición;
* tiempo de construcción y espacio.

Tablas completas, gráficas y discusión en [`parte2_espacial.md`](parte2_espacial.md)
§5 y [`resultados_experimentales.md`](resultados_experimentales.md).

**Conclusiones**
1. Los dos índices eliminan el crecimiento lineal de la búsqueda secuencial.
2. **PostGIS** domina el k-NN gracias a su *Index Scan* ordenado por `<->`, en C e
   integrado en el optimizador.
3. El **R-Tree propio** gana con datasets pequeños (sin planificación ni ida y vuelta)
   y en intersección con polígonos.
4. Con radios grandes, R-Tree y GiST quedan parejos: domina el costo de devolver
   filas.
5. Medidos de forma comparable (índice serializado frente a `pg_relation_size`),
   ambos ocupan ~41-43 B por punto.

## 7. Cómo se valida

* `python -m pytest -q` corre toda la suite (unitarias, integración, end-to-end,
  script de la cátedra y cumplimiento).
* `python -m benchmarks.generate_report_tables --check` verifica que las tablas
  coinciden con los CSV.
* `cd frontend && npm run build` compila la interfaz.
