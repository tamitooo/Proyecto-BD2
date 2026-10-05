# Resultados experimentales (generado)

Archivo generado automáticamente desde los CSV de `benchmark_results/`. Las mismas tablas aparecen en el informe y en el README.

## Parte 1 · Heap File vs Archivo Secuencial Paginado

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

## Parte 1 · B+ agrupado vs B+ no agrupado vs Hash Extendible

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

## Parte 2 · Secuencial vs R-Tree vs GiST (PostGIS)

_Generado por `python -m benchmarks.generate_report_tables` desde `benchmark_results/*.csv`. No editar a mano._

Entorno de la corrida: Linux-6.18.44-fc-v70-x86_64-with-glibc2.39 · Python 3.12.3 · PostgreSQL 16.15 (Ubuntu 16.15-0ubuntu0.24.04.1) + PostGIS 3.4.2.

**Rango (radio 1 km), promedio de 100 consultas**

| N | Secuencial | R-Tree propio | GiST/PostGIS | R-Tree vs secuencial | GiST vs secuencial | Más rápido (R-Tree vs GiST) |
|---|---|---|---|---|---|---|
| 1 000 | 0.817 ms | 0.038 ms | 0.163 ms | 21.3× | 5.0× | R-Tree 4.3× |
| 10 000 | 8.289 ms | 0.242 ms | 0.197 ms | 34.2× | 42.1× | GiST 1.2× |
| 100 000 | 88.545 ms | 2.055 ms | 0.342 ms | 43.1× | 258.7× | GiST 6.0× |

**Rango (radio 5 km)**

| N | Secuencial | R-Tree propio | GiST/PostGIS | R-Tree vs secuencial | GiST vs secuencial | Más rápido (R-Tree vs GiST) |
|---|---|---|---|---|---|---|
| 1 000 | 0.807 ms | 0.077 ms | 0.202 ms | 10.5× | 4.0× | R-Tree 2.6× |
| 10 000 | 8.337 ms | 0.778 ms | 0.588 ms | 10.7× | 14.2× | GiST 1.3× |
| 100 000 | 88.845 ms | 11.630 ms | 10.032 ms | 7.6× | 8.9× | GiST 1.2× |

**Rango (radio 10 km)**

| N | Secuencial | R-Tree propio | GiST/PostGIS | R-Tree vs secuencial | GiST vs secuencial | Más rápido (R-Tree vs GiST) |
|---|---|---|---|---|---|---|
| 1 000 | 0.838 ms | 0.188 ms | 0.290 ms | 4.5× | 2.9× | R-Tree 1.5× |
| 10 000 | 8.437 ms | 2.462 ms | 1.395 ms | 3.4× | 6.0× | GiST 1.8× |
| 100 000 | 89.167 ms | 38.093 ms | 43.485 ms | 2.3× | 2.1× | R-Tree 1.1× |

**k-NN (k = 10)**

| N | Secuencial | R-Tree propio | GiST/PostGIS | R-Tree vs secuencial | GiST vs secuencial | Más rápido (R-Tree vs GiST) |
|---|---|---|---|---|---|---|
| 1 000 | 0.904 ms | 0.418 ms | 0.220 ms | 2.2× | 4.1× | GiST 1.9× |
| 10 000 | 9.494 ms | 1.921 ms | 0.237 ms | 4.9× | 40.1× | GiST 8.1× |
| 100 000 | 116.289 ms | 11.350 ms | 0.258 ms | 10.2× | 451.2× | GiST 44.0× |

**k-NN (k = 50)**

| N | Secuencial | R-Tree propio | GiST/PostGIS | R-Tree vs secuencial | GiST vs secuencial | Más rápido (R-Tree vs GiST) |
|---|---|---|---|---|---|---|
| 1 000 | 0.899 ms | 0.550 ms | 0.352 ms | 1.6× | 2.6× | GiST 1.6× |
| 10 000 | 10.387 ms | 2.269 ms | 0.396 ms | 4.6× | 26.2× | GiST 5.7× |
| 100 000 | 148.088 ms | 11.033 ms | 0.433 ms | 13.4× | 341.8× | GiST 25.5× |

**k-NN (k = 100)**

| N | Secuencial | R-Tree propio | GiST/PostGIS | R-Tree vs secuencial | GiST vs secuencial | Más rápido (R-Tree vs GiST) |
|---|---|---|---|---|---|---|
| 1 000 | 0.903 ms | 0.658 ms | 0.512 ms | 1.4× | 1.8× | GiST 1.3× |
| 10 000 | 9.914 ms | 2.706 ms | 0.619 ms | 3.7× | 16.0× | GiST 4.4× |
| 100 000 | 174.897 ms | 12.949 ms | 0.633 ms | 13.5× | 276.5× | GiST 20.5× |

**Todas las consultas con 100 000 puntos**

| Consulta | Secuencial | R-Tree propio | GiST/PostGIS |
|---|---|---|---|
| Rango 1 km | 88.545 ms | 2.055 ms (43.1×) | 0.342 ms (258.7×) |
| Rango 5 km | 88.845 ms | 11.630 ms (7.6×) | 10.032 ms (8.9×) |
| Rango 10 km | 89.167 ms | 38.093 ms (2.3×) | 43.485 ms (2.1×) |
| k-NN k=10 | 116.289 ms | 11.350 ms (10.2×) | 0.258 ms (451.2×) |
| k-NN k=50 | 148.088 ms | 11.033 ms (13.4×) | 0.433 ms (341.8×) |
| k-NN k=100 | 174.897 ms | 12.949 ms (13.5×) | 0.633 ms (276.5×) |
| Polígono (4 vértices) | — | 11.127 ms | — |

**Tiempo de construcción y espacio del índice**

| N | Construcción R-Tree | Construcción GiST | Índice R-Tree (serializado) | Índice GiST (pg_relation_size) | R-Tree en memoria Python | Tabla PostgreSQL (contexto) |
|---|---|---|---|---|---|---|
| 1 000 | 4.5 ms | 9.5 ms | 42.0 KiB | 48.0 KiB | 515.0 KiB | 88.0 KiB |
| 10 000 | 52.2 ms | 49.0 ms | 419.4 KiB | 384.0 KiB | 4.29 MiB | 832.0 KiB |
| 100 000 | 715.5 ms | 287.0 ms | 4.09 MiB | 3.94 MiB | 42.92 MiB | 8.05 MiB |

**Lectura numérica (calculada del CSV)**

- Rango 1 km con 1 000 puntos: R-Tree 0.038 ms vs GiST 0.163 ms → el R-Tree es 4.3× más rápido que PostGIS.
- Escalabilidad del R-Tree (rango 1 km, de 10 000 a 100 000 puntos): 0.242 ms → 2.055 ms (8.5× más tiempo para 10× datos; los resultados por consulta también crecen 9.8× (6 → 59)).
- Escalabilidad del GiST (rango 1 km, de 10 000 a 100 000 puntos): 0.197 ms → 0.342 ms (1.7× más tiempo para 10× datos; los resultados por consulta también crecen 9.8× (6 → 59)).
- Con resultado de tamaño fijo (k-NN k=10) el R-Tree crece de forma sublineal: 1.921 ms → 11.350 ms (5.9× para 10× datos).
- Secuencial (rango 1 km) de 10 000 a 100 000: 8.289 ms → 88.545 ms (10.7×, lineal en N).
- k-NN del R-Tree con 100 000 puntos: k=10 11.350 ms y k=100 12.949 ms (apenas cambia con k: O(k log n)).
- k-NN k=10 con 100 000 puntos: GiST 0.258 ms vs R-Tree 11.350 ms → GiST 44× más rápido (C + operador <-> integrado en el optimizador).
- Rango 10 km con 100 000 puntos: R-Tree 38.093 ms vs GiST 43.485 ms (con resultados grandes domina el costo de devolver filas, no la búsqueda).
- Espacio con 100 000 puntos: R-Tree serializado 4.09 MiB (42.9 B/punto) vs GiST 3.94 MiB (41.3 B/punto).
